# -*- coding: utf-8 -*-
"""Parser regression tests for numbered and arrow-chain route formats."""

import unittest

from src.common import load_poi_terms
from src.exp3_routes import parse_route


class RouteFormatTests(unittest.TestCase):
    def setUp(self):
        self.poi_terms = load_poi_terms()

    def parse(self, text):
        return parse_route(
            {
                "record_id": "test_route",
                "attraction": "故宫博物院",
                "text_type": "official_route",
                "title": "parser test",
                "source": "synthetic_fixture",
                "source_url": "",
                "content": text,
            },
            self.poi_terms,
        )

    def test_arrow_chain_preserves_order_and_mentions(self):
        route, steps = self.parse("午门 -> 太和门 -> 太和殿")
        self.assertIn("arrow_chain", route["format_detected"])
        self.assertEqual([step["poi_canonical"] for step in steps], ["午门", "太和门", "太和殿"])
        for step in steps:
            span = step["source_span"]
            self.assertEqual(route["source_text"][span["start"] : span["end"]], step["poi_surface"])

    def test_numbered_route_preserves_order_and_time(self):
        route, steps = self.parse("1. 上午从午门入馆。2. 随后参观太和殿。")
        self.assertIn("numbered", route["format_detected"])
        self.assertEqual([step["poi_canonical"] for step in steps], ["午门", "太和殿"])
        self.assertEqual([step["time_bucket"] for step in steps], ["上午", "上午"])


if __name__ == "__main__":
    unittest.main()
