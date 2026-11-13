"""Deterministic site-aware extraction, conservative cleaning, and provenance."""
import collections
from contextlib import closing
import html
import re
import sqlite3
import unicodedata

from bs4 import BeautifulSoup, NavigableString, Tag

from .common import ROOT, FIELDS, digest, read_json, write_csv, write_json

BLOCKS = {'p', 'div', 'section', 'article', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'tr', 'blockquote', 'br'}
SELECTORS = {
    'visitbeijing': '.mod-content article',
    'visitbeijing_scenic': '.moreDesc',
    'government': '#div_zhengwen',
    'dpm': '.visit2, .visit3 > .s-wrap > div > .desc, .visit6',
    'summerpalace': '.visit',
    'tiantan': '.x-container',
    'autohome': '.youji-page-content',
    'blog': '.post-content',
}


def render_text(node):
    """Keep block boundaries while joining inline anchor/strong/span fragments."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ''
    if node.name in ('script', 'style', 'noscript', 'svg', 'button', 'input', 'img'):
        return ''
    text = ''.join(render_text(child) for child in node.children)
    return '\n' + text + '\n' if node.name in BLOCKS else text


def extract_html(page, source, version=2):
    soup = BeautifulSoup(page, 'html.parser')
    title = soup.title.get_text(strip=True) if soup.title else ''
    for node in soup.select('script, style, noscript, svg, iframe, .yj_content, .tools, .share, .img'):
        node.decompose()
    parser = source['parser']
    if parser == 'ctrip':
        nodes = soup.select('.travel-content-wrapper') or soup.select('.rich-text-container > .content')
        selector = '.travel-content-wrapper OR .rich-text-container > .content'
    else:
        selector = SELECTORS[parser]
        nodes = soup.select(selector)
    if not nodes:
        raise ValueError(f"{source['doc_id']}: selector {selector} found no body; refuse whole-page fallback")
    # Baseline deliberately uses common get_text separator; v2 preserves inline words.
    raw = '\n'.join(n.get_text('\n', strip=False) if version == 1 else render_text(n) for n in nodes)
    if source.get('section_start'):
        marker = source['section_start']
        match = re.search(r'\s*'.join(re.escape(c) for c in marker), raw)
        if match is None:
            raise ValueError(f"{source['doc_id']}: missing section marker")
        raw = raw[match.start():]
    if source.get('section_end'):
        match = re.search(r'\s*'.join(re.escape(c) for c in source['section_end']), raw)
        if match is None:
            raise ValueError(f"{source['doc_id']}: missing section end marker")
        raw = raw[:match.start()]
    return title.strip(), raw, selector


def normalize(text):
    # NFC does not fold scenic names or simplify traditional Chinese.
    text = unicodedata.normalize('NFC', html.unescape(text)).replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[\u200b-\u200d\ufeff\u2060]', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Keep punctuation, arrows, numbers and travel times; remove explicit web links only.
    text = re.sub(r'https?://[^\s<>，。；）)]+', '', text)
    text = text.replace('\xa0', ' ').replace('\u3000', ' ')
    lines = [re.sub(r'[\t ]+', ' ', line).strip() for line in text.split('\n')]
    return '\n'.join(line for line in lines if line)


def clean_all():
    sources = read_json(ROOT / 'config/sources.json')
    manifest = {m['doc_id']: m for m in read_json(ROOT / 'data/raw/manifest.json')}
    rows, provenance, comparisons, quarantine = [], [], [], []
    original_records = []
    for source in sources:
        doc_id = source['doc_id']
        meta = manifest[doc_id]
        page = (ROOT / meta['raw_path']).read_bytes()
        if digest(page) != meta['sha256']:
            raise ValueError(f'{doc_id}: raw checksum mismatch')
        decoded = page.decode(meta['encoding'], errors='strict')
        title, raw, selector = extract_html(decoded, source, version=2)
        _, baseline, _ = extract_html(decoded, source, version=1)
        content = normalize(raw)
        record = {**source, 'title': title, 'raw_content': raw, 'selector': selector,
                  'raw_sha256': meta['sha256'], 'retrieved_at': meta['retrieved_at']}
        original_records.append(record)
        issues = []
        if source.get('exclude_reason'):
            issues.append(source['exclude_reason'])
        if len(content) < 100:
            issues.append('body_less_than_100_characters')
        if '\ufffd' in content:
            issues.append('replacement_character')
        if source['scenic'].replace('公园', '') not in content and source['scenic'] != '故宫博物院':
            issues.append('scenic_name_absent')
        if issues:
            quarantine.append({'doc_id': doc_id, 'issues': issues})
            continue
        rows.append({key: content if key == 'content' else source[key] for key in FIELDS})
        provenance.append({**record, 'clean_sha256': digest(content), 'clean_characters': len(content),
                           'raw_content': raw, 'content_version': 'clean-v2',
                           'notes': source.get('note', ''), 'short_body_warning': len(content) < 300})
        comparisons.append({'doc_id': doc_id, 'baseline_v1': normalize(baseline),
                            'extracted_before_cleaning': raw, 'clean_v2': content,
                            'baseline_lines': len(normalize(baseline).splitlines()),
                            'final_lines': len(content.splitlines())})
        print(doc_id, title[:40], len(content), flush=True)
    write_csv(ROOT / 'data/processed/documents.csv', rows, FIELDS)
    write_json(ROOT / 'data/processed/documents.json', rows)
    write_json(ROOT / 'data/raw/extracted_records.json', original_records)
    write_json(ROOT / 'data/processed/provenance.json', provenance)
    write_json(ROOT / 'outputs/qa/cleaning_comparisons.json', comparisons)
    write_json(ROOT / 'outputs/qa/quarantine.json', quarantine)
    # Rebuilt exclusively from immutable source snapshots; not an incremental append database.
    db_path = ROOT / 'data/foundation.sqlite'
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.executescript('''
            DROP TABLE IF EXISTS clean_documents;
            DROP TABLE IF EXISTS raw_documents;
            CREATE TABLE raw_documents (doc_id TEXT PRIMARY KEY, scenic TEXT NOT NULL,
                doc_type TEXT NOT NULL, source TEXT NOT NULL, url TEXT NOT NULL,
                title TEXT, raw_content TEXT, raw_path TEXT, raw_sha256 TEXT, retrieved_at TEXT);
            CREATE TABLE clean_documents (doc_id TEXT PRIMARY KEY REFERENCES raw_documents(doc_id),
                scenic TEXT NOT NULL, doc_type TEXT NOT NULL CHECK(doc_type IN ('official','travelogue')),
                source TEXT NOT NULL, content TEXT NOT NULL, url TEXT NOT NULL, content_sha256 TEXT NOT NULL);
        ''')
        for r in original_records:
            connection.execute('INSERT INTO raw_documents VALUES (?,?,?,?,?,?,?,?,?,?)',
                tuple(r[k] for k in ('doc_id', 'scenic', 'doc_type', 'source', 'url', 'title', 'raw_content')) +
                (manifest[r['doc_id']]['raw_path'], r['raw_sha256'], r['retrieved_at']))
        connection.executemany('INSERT INTO clean_documents VALUES (?,?,?,?,?,?,?)',
            [tuple(r[k] for k in FIELDS) + (digest(r['content']),) for r in rows])
    counts = collections.Counter((r['scenic'], r['doc_type']) for r in rows)
    write_json(ROOT / 'outputs/qa/data_quality.json', {
        'raw_records': len(sources), 'accepted_records': len(rows), 'quarantined_records': len(quarantine),
        'counts': [{'scenic': s, 'doc_type': t, 'count': n} for (s, t), n in sorted(counts.items())],
        'total_characters': sum(len(r['content']) for r in rows),
        'duplicate_content_groups': [ids for ids in _groups(rows).values() if len(ids) > 1],
        'rules': ['site-specific main content', 'NFC', 'invisible controls removed',
                  'URLs removed', 'whitespace normalized', 'paragraph/route/time punctuation retained'],
    })
    print(f'Accepted {len(rows)}; quarantined {len(quarantine)} (excluded from downstream outputs)', flush=True)


def _groups(rows):
    groups = collections.defaultdict(list)
    for row in rows:
        groups[digest(row['content'])].append(row['doc_id'])
    return groups
