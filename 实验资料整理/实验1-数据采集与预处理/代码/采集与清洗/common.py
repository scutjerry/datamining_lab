import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ['doc_id', 'scenic', 'doc_type', 'source', 'content', 'url']


def digest(value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='raise')
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))
