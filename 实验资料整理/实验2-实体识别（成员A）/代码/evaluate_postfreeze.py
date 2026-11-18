"""Score the separately sampled post-freeze review; reference labels remain provisional."""
import collections
import argparse
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from member_a.common import ROOT, read_json, write_json
from member_a.entities import extract
from evaluate_member_a import reference_entities

LABELS = {
 'R001': {},
 'R002': {'POI':['天坛公园','祈年殿','大享殿']},
 'R003': {'POI':['天坛'],'TIME':['中午']},
 'R004': {},
 'R005': {'POI':[{'text':'祈年殿','occurrence':1}]},
 'R006': {'POI':['祈年殿']},
 'R007': {'POI':['南三所','撷（念邪）芳殿']},
 'R008': {}, 'R009': {}, 'R010': {}, 'R011': {},
 'R012': {'POI':['御花园','钦安殿']},
 'R013': {'POI':['知鱼桥']},
 'R014': {'POI':['万寿山','香山','玉泉山','清漪园','静宜园','静明园','畅春园','圆明园']},
 'R015': {},
 'R016': {'POI':['万寿山','佛香阁']},
 'R017': {'POI':['畅春园','排云门']},
 'R018': {},
}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',type=int,choices=[4,5],default=5)
    version=parser.parse_args().version
    samples = read_json(ROOT/'evaluation/postfreeze_review_samples.json')
    counts = {kind:collections.Counter(tp=0,fp=0,fn=0) for kind in ('POI','TRANSPORT','TIME')}
    errors = []
    references = []
    for sample in samples:
        text = sample['text']
        references.append({**sample,'annotation_origin':'assistant_reviewed_provisional',
                           'entities':reference_entities(text,LABELS[sample['sample_id']])})
        gold = {(e['start'],e['end'],e['type']) for e in references[-1]['entities']}
        pred = {(e['start'],e['end'],e['type']) for e in extract(text,sample['scenic'],version=version)}
        for kind in counts:
            g={x for x in gold if x[2]==kind};p={x for x in pred if x[2]==kind}
            counts[kind].update(tp=len(g&p),fp=len(p-g),fn=len(g-p))
        if gold!=pred:
            errors.append({'sample_id':sample['sample_id'],'doc_id':sample['doc_id'],'text':text,
                'false_positives':[{'text':text[a:b],'type':k} for a,b,k in sorted(pred-gold)],
                'false_negatives':[{'text':text[a:b],'type':k} for a,b,k in sorted(gold-pred)]})
    counts['micro']=sum(counts.values(),collections.Counter())
    scores={}
    for kind,c in counts.items():
        p=c['tp']/(c['tp']+c['fp']) if c['tp']+c['fp'] else None
        r=c['tp']/(c['tp']+c['fn']) if c['tp']+c['fn'] else None
        f=2*c['tp']/(2*c['tp']+c['fp']+c['fn']) if 2*c['tp']+c['fp']+c['fn'] else None
        scores[kind]={**{k:c[k] for k in ('tp','fp','fn')},'precision':p,'recall':r,'f1':f}
    write_json(ROOT/'evaluation/postfreeze_reference.json',references)
    write_json(ROOT/f'outputs/qa/postfreeze_review_v{version}.json',{
        'seed':20261113,'samples':len(samples),'algorithm':f'v{version}',
        'scope':'separately sampled after v4; reviewed failures used to develop v5; v5 is an in-sample regression score',
        'sampling':'six sentences per scenic; length 25..140; exclude all regression-case source documents; no prediction-based selection',
        'annotation_origin':'assistant-reviewed provisional; not confirmed by a human',
        'limitations':'small, mostly POI/negative sample; no TRANSPORT gold mentions; not evidence of general accuracy',
        'scores':scores,'errors':errors})
    print(scores)


if __name__=='__main__':
    main()
