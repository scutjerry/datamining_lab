"""Build a documented lexicon from official guide labels plus curated in-domain names."""
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from member_a.common import ROOT, write_json

BASE = {
 '故宫博物院': '故宫博物院 故宫 紫禁城 午门 太和门 太和殿 中和殿 保和殿 乾清宫 交泰殿 坤宁宫 御花园 神武门 珍宝馆 钟表馆',
 '颐和园': '颐和园 万寿山 昆明湖 东宫门 北宫门 新建宫门 仁寿殿 玉澜堂 宜芸馆 乐寿堂 长廊 佛香阁 石舫 十七孔桥 苏州街',
 '天坛公园': '天坛公园 天坛 祈年殿 皇乾殿 圜丘 皇穹宇 回音壁 丹陛桥 斋宫 神乐署 长廊 七星石',
}
ADDITIONAL = {
 '故宫博物院': '保和殿西庑 保和殿东庑 乾清门 文华殿 武英殿 弘义阁 奉先殿 养心殿 西六宫区 东六宫区 宁寿宫区 宁寿宫区前朝 宁寿宫区后寝 慈宁宫 寿康宫 慈宁宫花园 内金水桥 外金水桥 金水桥 东华门 西华门 冰窖 冰窖餐厅 冰窖书店 故宫角楼咖啡馆 军机处',
 '颐和园': '文昌院 文昌阁 德和园 南湖岛 铜牛 东堤 西堤 排云门 排云殿 耕织图景区 如意门 南如意门 北如意门 西门 南湖岛北码头 玉带桥 界湖桥 半壁桥 柳桥 景明楼 绣漪桥 廓如亭 廊如亭 宿云檐 宿云檐城关 谐趣园 紫气东来城关 寅辉城关 四大部洲 智慧海 祗树林 眺远斋 团城湖 昆仑石碑 乐寿宫 邀月门 知春亭 藕香榭 清晏舫 画中游 听鹂馆 乐农轩 景福阁 澄爽斋 多宝琉璃塔 排云殿码头 石舫码头 铜牛码头 文昌阁码头 玉澜堂码头 八方亭 石丈亭',
 '天坛公园': '圜丘坛 祈谷坛 七十二长廊 七十二连房 天坛公园东门 天坛公园南门 天坛公园北门 天坛公园西门 天坛东门 天坛南门 天坛北门 天坛西门 祈年殿东门 祈年殿西门 回音壁西侧闸机 迎客柏月亮门 丹陛桥西侧下面古树区 三座门 北神厨 北宰牲亭 皇乾殿 祈年门 斋宫无梁殿 无梁殿 双环万寿亭 九龙柏 宰牲亭 神厨 神库 具服台 成贞门 昭亨门 泰元门 广利门 北天门 东天门 西天门 祈年殿西配殿 祈年殿东配殿',
}


def main():
    records = []
    for scenic, words in BASE.items():
        doc_id = {'故宫博物院': 'D004', '颐和园': 'D002', '天坛公园': 'D003'}[scenic]
        for word in words.split():
            records.append({'scenic': scenic, 'text': word, 'type': 'POI', 'added_in': 1,
                            'evidence': doc_id, 'origin': 'curated core scenic vocabulary'})
        extra = set(ADDITIONAL[scenic].split()) - set(words.split())
        if scenic == '故宫博物院':
            soup = BeautifulSoup((ROOT / 'data/raw/pages/D004.html').read_bytes(), 'html.parser')
            for node in soup.select('option[data-name="palace"]'):
                term = node.get_text(strip=True).replace('\xa0', '').strip()
                # Parent area labels remain POIs; no history/event labels are imported.
                if term and term not in words.split():
                    extra.add(term)
        for word in sorted(extra):
            records.append({'scenic': scenic, 'text': word, 'type': 'POI', 'added_in': 2,
                            'evidence': doc_id, 'origin': 'official labels or curated source-attested name; not normalization'})
    for term in ['圆丘', '宰牲亭北', '宰牲亭南', '神厨北', '神厨南']:
        records.append({'scenic': '天坛公园', 'text': term, 'type': 'POI', 'added_in': 3,
                        'evidence': 'D305' if term == '圆丘' else 'D302',
                        'origin': 'source surface-form variant; retained literally for C'})
    for scenic, terms, evidence in [
        ('故宫博物院', '金銮殿 雁翅楼 东南角楼 西北角楼 故宫餐厅', 'D001,D106'),
        ('颐和园', '文昌院门 排云殿东九间', 'D002'),
        ('*', '天安门 天安门广场 景山公园 景山 北海公园 北海 圆明园 法源寺 白云观 地坛 日坛 月坛', 'D106,D305'),
    ]:
        for term in terms.split():
            records.append({'scenic': scenic, 'text': term, 'type': 'POI', 'added_in': 3,
                            'evidence': evidence, 'origin': 'source-attested surface form; * denotes external POI, not scenic membership'})
    records.append({'scenic':'*','text':'杭州西湖','type':'POI','added_in':4,'evidence':'D002',
                    'origin':'explicit comparison POI; external location, no scenic membership assertion'})
    for scenic in BASE:
        existing = {r['text'] for r in records if r['scenic']==scenic}
        for term in ['东门','南门','西门','北门']:
            if term not in existing:
                records.append({'scenic':scenic,'text':term,'type':'POI','added_in':4,
                                'evidence':'D106,D201,D302,D305',
                                'origin':'local gate surface form; resolve names only downstream with scenic/context'})
    for scenic, terms, evidence in [
        ('天坛公园', ['大享殿'], 'D301'),
        ('故宫博物院', ['南三所','撷（念邪）芳殿'], 'D105'),
        ('颐和园', ['知鱼桥','清漪园'], 'D202,D205'),
        ('*', ['香山','玉泉山','静宜园','静明园','畅春园'], 'D202,D206'),
    ]:
        for term in terms:
            records.append({'scenic':scenic,'text':term,'type':'POI','added_in':5,
                            'evidence':evidence,'origin':'v4 error review; literal historical/external name, not canonical alignment'})
    # Audit the lexicon's provenance against actual visible raw snapshots, rather
    # than attributing all curated names to one convenient official document.
    visible = {}
    for source in json.loads((ROOT/'config/sources.json').read_text(encoding='utf-8')):
        soup = BeautifulSoup((ROOT/f"data/raw/pages/{source['doc_id']}.html").read_bytes(),'html.parser')
        for node in soup.select('script,style,noscript'):
            node.decompose()
        visible[source['doc_id']] = soup.get_text('',strip=True)
    unique = {}
    unattested = []
    for record in records:
        evidence = [doc_id for doc_id,text in visible.items() if record['text'] in text]
        if not evidence:
            unattested.append(record)
            continue
        record['evidence'] = evidence
        record['origin'] += '; evidence audited against visible raw page text'
        key = (record['scenic'],record['text'])
        if key not in unique or record['added_in'] < unique[key]['added_in']:
            unique[key] = record
    records = list(unique.values())
    write_json(ROOT / 'config/poi_lexicon.json', records)
    write_json(ROOT / 'outputs/qa/unattested_lexicon_candidates.json', unattested)
    write_json(ROOT / 'config/transport_lexicon.json', {
        'v1': ['步行', '公交', '地铁', '出租车', '游船', '自驾', '火车', '飞机'],
        'v2': ['走路', '公交车', '公交汽车', '公共汽车', '公共交通', '打车', '乘船', '坐船', '轮渡',
               '索道', '缆车', '骑行', '骑车', '自行车', '电瓶车', '观光车', '旅游大巴', '大巴', '高铁', '电动船', '脚踏船', '手划船', '画舫'],
        'v3': ['共享单车'],
    })
    print(f'Built {len(records)} POI lexicon records')


if __name__ == '__main__':
    main()
