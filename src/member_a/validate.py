"""Checks the actual A→B/C files, database, raw checksums and all entity occurrences."""
import collections
from contextlib import closing
import sqlite3

from jsonschema import Draft202012Validator

from .common import ROOT, FIELDS, digest, read_csv, read_json, write_json


def validate_all():
    rows = read_csv(ROOT / 'data/processed/documents.csv')
    documents = read_json(ROOT / 'outputs/entities.json')
    meta = read_json(ROOT / 'outputs/entities.meta.json')
    sentences = {d['doc_id']: d['sentences'] for d in read_json(ROOT / 'outputs/sentences.json')}
    Draft202012Validator(read_json(ROOT / 'schemas/entities.schema.json')).validate(documents)
    assert rows and list(rows[0]) == FIELDS, 'CSV header does not match member C contract'
    by_id = {r['doc_id']: r for r in rows}
    assert len(by_id) == len(rows), 'duplicate doc_id'
    assert len(documents) == len(rows), 'missing or extra entity document'
    assert {d['doc_id'] for d in documents} == set(by_id), 'cross-file join mismatch'
    assert len({d['doc_id'] for d in documents}) == len(documents), 'duplicate entity document'
    assert read_json(ROOT / 'data/processed/documents.json') == rows, 'CSV/JSON content mismatch'
    counts = collections.Counter((r['scenic'], r['doc_type']) for r in rows)
    assert len({r['scenic'] for r in rows}) == 3, 'must contain three scenic areas'
    for scenic in {r['scenic'] for r in rows}:
        assert counts[scenic, 'official'] >= 1 and counts[scenic, 'travelogue'] >= 5, scenic
    assert len({digest(r['content']) for r in rows}) == len(rows), 'exact duplicate documents'
    total = 0
    for doc in documents:
        row = by_id[doc['doc_id']]
        text = row['content']
        assert doc['scenic'] == row['scenic'] and doc['source'] == row['doc_type']
        assert all(value.strip() for value in row.values()), f"empty required field: {doc['doc_id']}"
        assert '\ufffd' not in text and '\r' not in text and len(text) >= 100
        assert meta['content_sha256'][doc['doc_id']] == digest(text)
        seen = set()
        previous_end = 0
        for entity in doc['entities']:
            start, end = entity['start'], entity['end']
            assert 0 <= start < end <= len(text)
            assert text[start:end] == entity['text'], f"offset mismatch: {doc['doc_id']} {entity}"
            assert start >= previous_end, f"overlapping/out-of-order entity: {doc['doc_id']}"
            previous_end = end
            key = (start, end, entity['type'])
            assert key not in seen
            seen.add(key)
            sentence = sentences[doc['doc_id']][entity['sentence_id'] - 1]
            assert sentence['start'] <= start < end <= sentence['end']
            assert text[sentence['start']:sentence['end']] == sentence['text']
            total += 1
    for raw in read_json(ROOT / 'data/raw/manifest.json'):
        assert digest((ROOT / raw['raw_path']).read_bytes()) == raw['sha256']
    with closing(sqlite3.connect(ROOT / 'data/foundation.sqlite')) as connection:
        stored = connection.execute('SELECT doc_id,scenic,doc_type,source,content,url FROM clean_documents ORDER BY doc_id').fetchall()
        expected = sorted(tuple(r[k] for k in FIELDS) for r in rows)
        assert stored == expected, 'SQLite/CSV mismatch'
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    result = {'passed': True, 'documents': len(rows), 'entities_checked': total,
              'scenic_counts': [{'scenic':s,'official': counts[s,'official'], 'travelogue':counts[s,'travelogue']}
                                for s in sorted({r['scenic'] for r in rows})],
              'checks': ['strict entity JSON Schema', 'exact six-column CSV contract', 'global unique doc_id',
                         'cross-file joins', 'source/doc_type mapping', 'all entity offset slices',
                         'all sentence references', 'no entity overlap/duplicates', 'three scenic quotas',
                         'raw SHA256', 'clean content SHA256', 'SQLite integrity and CSV equality']}
    write_json(ROOT / 'outputs/qa/interface_validation.json', result)
    print(result, flush=True)
    return result
