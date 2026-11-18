"""Provisional assistant-reviewed references, NOT independent human annotations.

Each selected real sentence is read and assigned explicit entity strings/types below.
Offsets are recovered from its unchanged text, not copied from model predictions.
These are diagnostic regression cases, not a randomly sampled population benchmark.
"""
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from member_a.common import ROOT, digest, read_csv, read_json, write_csv, write_json
from member_a.entities import extract, sentence_spans

# (document, one-based sentence, manually specified exhaustive target phrases by type)
CASES = [
 ('D001', 3, {}),
 ('D001', 9, {'POI': ['金銮殿','乾清宫','坤宁宫','御花园']}),
 ('D001',13, {'POI':['珍宝馆','钟表馆'], 'TIME':['11点','14点']}),
 ('D001',19, {'POI':['故宫'],'TIME':['两个小时左右']}),
 ('D002', 3, {}),
 ('D002', 4, {'POI':['昆明湖','万寿山','杭州西湖']}),
 ('D002',89, {'POI':['东宫门','文昌院门','北宫门','北如意门','新建宫门','南如意门','西门']}),
 ('D002',95, {'TIME':['上午11:00——下午2:30']}),
 ('D003', 3, {'POI':['天坛公园南门','圜丘','回音壁','回音壁西侧闸机','迎客柏月亮门','丹陛桥西侧下面古树区','祈年殿西门','祈年殿','祈年殿东门','长廊','天坛公园东门']}),
 ('D101',202, {}),
 ('D103',351, {'POI':['东华门','神武门']}),
 ('D106', 6, {}),
 ('D106',25, {'TRANSPORT':['步行','地铁']}),
 ('D106',27, {'POI':['故宫'],'TRANSPORT':['步行']}),
 ('D106',30, {'TIME':['半个小时']}),
 ('D106',76, {'TIME':['下午两点','18：23']}),
 ('D106',79, {'TIME':['四点'],'POI':['神武门']}),
 ('D106',85, {'POI':['神武门'],'TRANSPORT':['共享单车']}),
 ('D201',25, {'TIME':['四天']}),
 ('D201',27, {'TIME':['早上六点']}),
 ('D201',103,{'TIME':['中午','两个小时']}),
 ('D201',119,{'POI':['颐和园'],'TIME':['晚上']}),
 ('D302', 5, {}),
 ('D302', 7, {'POI':['祈谷坛','祈年殿']}),
 ('D302',10, {'POI':['东门','西门'],'TIME':['4-5小时']}),
 ('D304',21, {'TRANSPORT':['地铁'],'POI':[{'text':'东门','occurrence':2}]}),
 ('D304',22, {'TRANSPORT':['自驾','公共交通']}),
 ('D305', 3, {'POI':['天坛公园','天坛','东门'],'TIME':['11:15']}),
 ('D305', 4, {'POI':['天坛公园','东门','长廊','祈年殿','皇乾殿','具服台','丹陛桥','成贞门','皇穹宇','回音壁','圆丘','南门']}),
 ('D305', 9, {'POI':['东门','天坛公园'],'TIME':['13:20']}),
]


def reference_entities(text, labels):
    # Resolve only nested surface strings in manually assigned gold labels, e.g. 天坛/天坛公园.
    mentions = []
    for kind, words in labels.items():
        for item in words:
            word = item if isinstance(item,str) else item['text']
            assert word in text, (word, text)
            matches = list(re.finditer(re.escape(word),text))
            if isinstance(item,dict):
                matches = [matches[item['occurrence']-1]]
            mentions.extend((m.start(),m.end(),kind,word) for m in matches)
    keep = []
    for m in sorted(mentions, key=lambda m: -(m[1]-m[0])):
        if not any(m[0] < x[1] and x[0] < m[1] for x in keep):
            keep.append(m)
    return [{'start':a,'end':b,'type':kind,'text':word} for a,b,kind,word in sorted(keep)]


def main():
    rows = {r['doc_id']:r for r in read_csv(ROOT/'data/processed/documents.csv')}
    references = []
    worksheet = []
    for number,(doc_id,sentence_id,labels) in enumerate(CASES,1):
        row = rows[doc_id]
        a,b = sentence_spans(row['content'])[sentence_id-1]
        text = row['content'][a:b]
        gold = reference_entities(text,labels)
        record = {'sample_id':f'E{number:03}', 'doc_id':doc_id,'scenic':row['scenic'],
                  'sentence_id':sentence_id, 'document_start':a,'document_end':b,'text':text,
                  'content_sha256':digest(row['content']), 'entities':gold,
                  'annotation_origin':'assistant_reviewed_provisional', 'human_confirmed':False}
        references.append(record)
        worksheet.append({'sample_id':record['sample_id'],'doc_id':doc_id,'text':text,
                          'reference_entities':str([(e['text'],e['type']) for e in gold]),
                          'human_confirmed':'','corrections':''})
    write_json(ROOT/'evaluation/reference_samples.json', references)
    write_csv(ROOT/'evaluation/human_review.csv', worksheet,
              ['sample_id','doc_id','text','reference_entities','human_confirmed','corrections'])
    scores, errors = {}, []
    for version in (1,2,3,4,5):
        counts = {kind:collections.Counter(tp=0,fp=0,fn=0) for kind in ('POI','TRANSPORT','TIME')}
        for sample in references:
            predictions = extract(sample['text'],sample['scenic'],version)
            gold = {(e['start'],e['end'],e['type']) for e in sample['entities']}
            pred = {(e['start'],e['end'],e['type']) for e in predictions}
            for kind in counts:
                g = {x for x in gold if x[2]==kind}; p = {x for x in pred if x[2]==kind}
                counts[kind].update(tp=len(g&p), fp=len(p-g), fn=len(g-p))
            if gold != pred:
                errors.append({'version':version,'sample_id':sample['sample_id'],'doc_id':sample['doc_id'],
                               'text':sample['text'],
                               'false_positives':[{'text':sample['text'][a:b],'start':a,'end':b,'type':t} for a,b,t in sorted(pred-gold)],
                               'false_negatives':[{'text':sample['text'][a:b],'start':a,'end':b,'type':t} for a,b,t in sorted(gold-pred)]})
        counts['micro'] = sum(counts.values(), collections.Counter())
        scores[f'v{version}'] = {}
        for kind,c in counts.items():
            precision = c['tp']/(c['tp']+c['fp']) if c['tp']+c['fp'] else 0
            recall = c['tp']/(c['tp']+c['fn']) if c['tp']+c['fn'] else 0
            scores[f'v{version}'][kind] = {**{k:c[k] for k in ('tp','fp','fn')},'precision':precision,'recall':recall,
                'f1':2*precision*recall/(precision+recall) if precision+recall else 0}
    write_json(ROOT/'outputs/qa/reference_evaluation.json', {
        'sample_count':len(references), 'scope':'diagnostic regression samples, not an independent held-out benchmark',
        'annotation_origin':'assistant-reviewed provisional; team human review still pending',
        'matching':'exact type and complete character boundaries; all metrics computed from counts', 'scores':scores})
    write_json(ROOT/'outputs/qa/reference_errors.json',errors)
    print(scores)


if __name__ == '__main__':
    main()
