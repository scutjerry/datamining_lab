"""Select a separate post-freeze review set without consulting extraction predictions."""
import random
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from member_a.common import ROOT, digest, read_csv, write_json
from member_a.entities import sentence_spans


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    rows = read_csv(ROOT/'data/processed/documents.csv')
    rng = random.Random(20261113)
    selected = []
    # Exclude every document used for iterative diagnostic regression cases.
    excluded = {'D001','D002','D003','D101','D103','D106','D201','D302','D304','D305'}
    for scenic in sorted({r['scenic'] for r in rows}):
        pool = []
        for row in rows:
            if row['scenic'] != scenic or row['doc_id'] in excluded:
                continue
            for i,(start,end) in enumerate(sentence_spans(row['content']),1):
                text = row['content'][start:end]
                if 25 <= len(text) <= 140:
                    pool.append({'doc_id':row['doc_id'],'scenic':scenic,'sentence_id':i,
                                 'document_start':start,'document_end':end,'text':text,
                                 'content_sha256':digest(row['content'])})
        samples = rng.sample(pool,min(6,len(pool)))
        for item in samples:
            item['sample_id'] = f'R{len(selected)+1:03}'
            item['human_confirmed'] = False
            selected.append(item)
            print(item['sample_id'],item['doc_id'],item['sentence_id'],repr(item['text']))
    write_json(ROOT/'evaluation/postfreeze_review_samples.json',selected)


if __name__=='__main__':
    main()
