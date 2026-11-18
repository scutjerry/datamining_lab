# -*- coding: utf-8 -*-
"""Tests for atomic condition-to-advice extraction and source spans."""

import unittest

from src.exp5_conditions import extract_sentence


class ConditionGranularityTests(unittest.TestCase):
    def test_conjoined_recommendations_become_atomic_records(self):
        sentence = "如果下雨，建议穿防滑鞋并带轻便雨衣。"
        row = {
            "attraction": "故宫博物院",
            "record_id": "condition_fixture_01",
            "text_type": "traveler_note",
        }
        mentions = extract_sentence(sentence, row, 1, 0)
        self.assertEqual(len(mentions), 2)
        self.assertEqual({item["condition_text"] for item in mentions}, {"下雨"})
        self.assertEqual({item["advice_text"] for item in mentions}, {"穿防滑鞋", "带轻便雨衣"})
        for item in mentions:
            cspan = item["condition_span"]
            aspan = item["advice_span"]
            self.assertEqual(sentence[cspan["start"] : cspan["end"]], item["condition_text"])
            self.assertEqual(sentence[aspan["start"] : aspan["end"]], item["advice_text"])


if __name__ == "__main__":
    unittest.main()
