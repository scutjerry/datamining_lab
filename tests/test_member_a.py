import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bs4 import BeautifulSoup
from member_a.clean import normalize, render_text
from member_a.entities import extract
from member_a.validate import validate_all


class PipelineTests(unittest.TestCase):
    def test_inline_entities_survive_html_extraction(self):
        node = BeautifulSoup('<div><p>上午9:30乘船到<a>南湖岛</a>→<b>十七孔桥</b>。</p><p>下午步行。</p></div>','html.parser').div
        text = normalize(render_text(node))
        self.assertEqual(text,'上午9:30乘船到南湖岛→十七孔桥。\n下午步行。')

    def test_no_route_or_conditional_information_removed(self):
        text = normalize(' 如果下雨，建议步行。\r\n\u200b午门→太和殿\xa0 9:30—11:00 ')
        self.assertEqual(text,'如果下雨，建议步行。\n午门→太和殿 9:30—11:00')

    def test_ambiguous_time_and_full_duration_range(self):
        text = '稍微大一点，三点水。第一时间预约下午茶。上午九点出发，预计4-5小时，排队半个小时。'
        times = [e['text'] for e in extract(text,'天坛公园') if e['type']=='TIME']
        self.assertEqual(times,['上午九点','4-5小时','半个小时'])

    def test_gate_station_and_surface_form(self):
        text = '天坛东门站下车，从东门进入天坛公园，再去圆丘。'
        pois = [e['text'] for e in extract(text,'天坛公园') if e['type']=='POI']
        self.assertEqual(pois,['东门','天坛公园','圆丘'])

    def test_repeated_mentions_and_unicode_offsets(self):
        text = '🌈午门→太和殿。午门。'
        mentions = extract(text,'故宫博物院')
        self.assertEqual([(e['text'],e['start']) for e in mentions],[('午门',1),('太和殿',4),('午门',8)])
        for e in mentions:
            self.assertEqual(text[e['start']:e['end']],e['text'])
        self.assertEqual([e['sentence_id'] for e in mentions],[1,1,2])

    def test_all_delivered_data_interfaces(self):
        self.assertTrue(validate_all()['passed'])


if __name__=='__main__':
    unittest.main()
