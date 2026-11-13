"""Dictionary + rules extraction with occurrence offsets and five reproducible versions."""
import bisect
import collections
import re

import jieba

from .common import ROOT, digest, read_csv, read_json, write_csv, write_json

TYPES = ('POI', 'TRANSPORT', 'TIME')
NUM = r'[零〇一二两三四五六七八九十百\d]+'
CLOCK = r'(?<!\d)(?:[01]?\d|2[0-3])[:：][0-5]\d(?:分)?(?!\d)'
PERIOD = r'凌晨|清晨|早晨|早上|上午|中午|午后|下午|傍晚|晚上|夜间|夜晚'
V1_TIME = re.compile(rf'{CLOCK}|上午|中午|下午|晚上')
V2_TIME = re.compile(
    rf'{CLOCK}(?:\s*[-—–~～至到]\s*{CLOCK})?'
    rf'|(?:{PERIOD})?(?:[01]?\d|2[0-3]|[零〇一二两三四五六七八九十]{{1,3}})[点时](?:半|一刻|三刻|{NUM}分)?'
    rf'|{NUM}(?:\.\d+)?(?:个)?(?:小时|分钟)(?:左右|以上|以内)?'
    rf'|半小时|半天|一天|两天|一日|两日'
    rf'|{PERIOD}'
)
V3_TIME = re.compile(
    rf'(?:{PERIOD})?{CLOCK}(?:\s*[-—–~～至到]{{1,2}}\s*(?:{PERIOD})?{CLOCK})?'
    rf'|(?:{PERIOD})?(?:[01]?\d|2[0-3]|[零〇一二两三四五六七八九十]{{1,3}})[点时](?:半|一刻|三刻|{NUM}分)?'
    rf'|{NUM}(?:\.\d+)?(?:\s*[-—–~～至到]\s*{NUM}(?:\.\d+)?)?(?:个)?(?:小时|分钟|天|日)(?:半|左右|以上|以内)?'
    rf'|半(?:个)?小时|半天|{PERIOD}'
)


def sentence_spans(text):
    # Dot and colon are not sentence boundaries: decimal durations / clock expressions survive.
    spans = []
    start = 0
    for match in re.finditer(r'[。！？!?；;\n]+', text):
        end = match.end()
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def candidates(text, words, entity_type):
    if not words:
        return []
    pattern = re.compile('|'.join(re.escape(w) for w in sorted(set(words), key=lambda w: (-len(w), w))))
    return [(m.start(), m.end(), entity_type) for m in pattern.finditer(text)]


def extract(text, scenic, version=5):
    lexicon = read_json(ROOT / 'config/poi_lexicon.json')
    words = [r['text'] for r in lexicon if r['scenic'] in (scenic, '*') and r['added_in'] <= version]
    transport = read_json(ROOT / 'config/transport_lexicon.json')
    modes = transport['v1'] + (transport['v2'] if version >= 2 else []) + (transport['v3'] if version >= 3 else [])
    occurrences = candidates(text, words, 'POI') + candidates(text, modes, 'TRANSPORT')
    for match in (V1_TIME if version == 1 else V2_TIME if version == 2 else V3_TIME).finditer(text):
        occurrences.append((match.start(), match.end(), 'TIME'))
    if version >= 3:
        occurrences = [c for c in occurrences if keep_candidate(text, c, version)]
    # Resolve overlapping entities globally. Longest span first; POI wins equal-length ties.
    accepted = []
    for start, end, kind in sorted(set(occurrences), key=lambda x: (-(x[1] - x[0]), TYPES.index(x[2]), x[0])):
        if any(start < other_end and other_start < end for other_start, other_end, _ in accepted):
            continue
        accepted.append((start, end, kind))
    starts = [s for s, e in sentence_spans(text)]
    entities = []
    for start, end, kind in sorted(accepted):
        entities.append({'text': text[start:end], 'type': kind, 'start': start, 'end': end,
                         'sentence_id': bisect.bisect_right(starts, start)})
    return entities


def keep_candidate(text, candidate, version=3):
    start, end, kind = candidate
    value = text[start:end]
    if kind == 'POI' and version >= 4:
        if re.match(r'[东西南北]?站', text[end:end+2]):
            return False
        if value == '西门' and text[end:end+1] == '庆':
            return False
        if version >= 5 and value in ('祈年殿','天坛') and re.match(r'大展|展览|主题展', text[end:end+4]):
            return False
    if kind == 'TRANSPORT':
        # Explicit station names are facilities, not a mention of using a transport mode.
        if value in ('地铁', '火车') and text[end:end+1] == '站':
            return False
        if value in ('游船', '画舫') and re.search(r'(雕|模型|形状|形制|石制)', text[max(0,start-10):end+8]):
            return False
    if kind == 'TIME':
        # Avoid numerical suffix matches in architectural dates/measurements and quantities.
        if value.endswith('时') and not value.endswith('小时') and text[end:end+1] in ('期', '代', '候'):
            return False
        if start and text[start-1].isdigit() and value[0].isdigit():
            return False
        if value == '一点' and not re.match(r'钟|左右|前|后|多|半', text[end:end+2]):
            return False
        if re.fullmatch(r'[零〇一二两三四五六七八九十\d]+[点时]', value):
            if re.match(r'水|间|候|期|代|点|滴|儿', text[end:end+1]):
                return False
        if value.endswith(('天','日')) and text[max(0,start-1):start] == '月':
            return False
        if value == '下午' and text[end:end+1] == '茶':
            return False
    return True


def make_document(row, version):
    return {'doc_id': row['doc_id'], 'scenic': row['scenic'], 'source': row['doc_type'],
            'entities': extract(row['content'], row['scenic'], version)}


def extract_all():
    rows = read_csv(ROOT / 'data/processed/documents.csv')
    all_versions = {}
    counts = {}
    for version in (1, 2, 3, 4, 5):
        documents = [make_document(row, version) for row in rows]
        all_versions[version] = documents
        counts[f'v{version}'] = dict(collections.Counter(e['type'] for d in documents for e in d['entities']))
        write_json(ROOT / f'outputs/iterations/entities_v{version}.json', documents)
    write_json(ROOT / 'outputs/entities.json', all_versions[5])
    write_json(ROOT / 'outputs/entities.meta.json', {
        'schema_version': 'member-c-v1.0', 'algorithm_version': 'v5',
        'text_source': 'data/processed/documents.csv:content',
        'offsets': 'zero-based Unicode code point offsets; [start,end); not UTF-8 bytes or UTF-16 units',
        'sentence_id': 'one-based; sentence ends at Chinese punctuation, ; or newline; see sentences.json',
        'source': 'official or travelogue, deliberately mapped from documents.doc_type per member C example',
        'normalization': 'entity text is unchanged content slice; alias merging reserved for member C',
        'content_sha256': {r['doc_id']: digest(r['content']) for r in rows},
    })
    write_json(ROOT / 'outputs/sentences.json', [
        {'doc_id': r['doc_id'], 'sentences': [{'sentence_id': i+1, 'start': start, 'end': end,
          'text': r['content'][start:end]} for i,(start,end) in enumerate(sentence_spans(r['content']))]}
        for r in rows])
    write_json(ROOT / 'outputs/iterations/entity_counts.json', counts)
    tokenizer = jieba.Tokenizer()
    for record in read_json(ROOT / 'config/poi_lexicon.json'):
        tokenizer.add_word(record['text'], freq=10000, tag='ns')
    samples = []
    for row in rows:
        sentence = next((row['content'][s:e] for s,e in sentence_spans(row['content'])
                         if any(x in row['content'][s:e] for x in ('步行','地铁','路线'))), row['content'][:150])
        samples.append({'doc_id': row['doc_id'], 'sentence': sentence,
                        'tokens': [{'text': w, 'start': s, 'end': e} for w,s,e in tokenizer.tokenize(sentence)]})
    write_json(ROOT / 'outputs/jieba_tokenization_samples.json', samples)
    frequency_rows = []
    for version, docs in all_versions.items():
        frequencies = collections.Counter((d['scenic'], e['type'], e['text']) for d in docs for e in d['entities'])
        for (scenic,kind,word), count in sorted(frequencies.items()):
            frequency_rows.append({'version': version, 'scenic': scenic, 'type': kind, 'text': word, 'count': count})
    write_csv(ROOT / 'outputs/entity_frequencies.csv', frequency_rows, ['version','scenic','type','text','count'])
    plot_frequencies(frequency_rows)
    print('Entity counts:', counts, flush=True)


def plot_frequencies(rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    folder = ROOT / 'outputs/figures'
    folder.mkdir(parents=True, exist_ok=True)
    for version in (1, 5):
        fig, axes = plt.subplots(1, 3, figsize=(16, 6), layout='constrained')
        for ax, kind in zip(axes, TYPES):
            freq = collections.Counter()
            for row in rows:
                if row['version'] == version and row['type'] == kind:
                    freq[row['text']] += row['count']
            top = freq.most_common(12)[::-1]
            ax.barh([x[0] for x in top], [x[1] for x in top], color='#2978a0')
            ax.set_title(f'{kind} 词频 TOP12')
            ax.set_xlabel('出现次数（保留原文写法）')
        fig.suptitle(f'实体识别 v{version} — 三景区合计')
        fig.savefig(folder / f'entity_frequency_v{version}.png', dpi=160)
        plt.close(fig)
