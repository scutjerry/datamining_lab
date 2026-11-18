"""Unseen sentences for genuine team annotation; no labels or predictions prefilled."""
import random
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from member_a.common import ROOT, digest, read_csv, read_json, write_csv
from member_a.entities import sentence_spans


def main():
    used = {(r['doc_id'],r['sentence_id']) for name in ['reference_samples.json','postfreeze_review_samples.json']
            for r in read_json(ROOT/'evaluation'/name)}
    rng = random.Random(20261114)
    rows = read_csv(ROOT/'data/processed/documents.csv')
    selected=[]
    for scenic in sorted({r['scenic'] for r in rows}):
        pool=[]
        for row in rows:
            if row['scenic']!=scenic: continue
            for i,(start,end) in enumerate(sentence_spans(row['content']),1):
                if (row['doc_id'],i) in used or not 25<=end-start<=160: continue
                pool.append({'doc_id':row['doc_id'],'scenic':scenic,'sentence_id':i,'document_start':start,
                    'text':row['content'][start:end],'content_sha256':digest(row['content']),
                    'human_entities_json':'','reviewer':'','notes':''})
        for row in rng.sample(pool,min(12,len(pool))):
            selected.append({'sample_id':f'T{len(selected)+1:03}',**row})
    write_csv(ROOT/'evaluation/team_review_unseen.csv',selected,
        ['sample_id','doc_id','scenic','sentence_id','document_start','text','content_sha256','human_entities_json','reviewer','notes'])
    print(f'Prepared {len(selected)} unlabelled team-review sentences')


if __name__=='__main__': main()
