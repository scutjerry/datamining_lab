# -*- coding: utf-8 -*-
"""Cross-file checks for experiment outputs and source text spans."""

from __future__ import annotations

from collections import Counter

from .common import DATA, OUT, ROOT, read_json, read_jsonl


def validate() -> dict:
    schema = read_json(ROOT / "schemas" / "experiment_3_4_5.schema.json")
    assert schema.get("$schema", "").endswith("2020-12/schema")
    sources = {row["record_id"]: row for row in read_jsonl(DATA / "cleaned_data.jsonl")}

    route_records = read_json(OUT / "exp3" / "route_records.json")
    route_steps = read_json(OUT / "exp3" / "route_steps.json")
    hierarchy = read_json(OUT / "exp3" / "route_hierarchy.json")
    comparisons = read_json(OUT / "exp3" / "route_comparisons.json")
    record_map = {item["route_id"]: item for item in route_records}
    assert len(record_map) == len(route_records)
    step_map = {item["step_id"]: item for item in route_steps}
    assert len(step_map) == len(route_steps)
    for step in route_steps:
        text = sources[step["route_id"]]["content"]
        span = step["source_span"]
        evidence = step["evidence_span"]
        assert text[span["start"] : span["end"]] == step["poi_surface"]
        assert text[evidence["start"] : evidence["end"]] == evidence["text"]
    for record in route_records:
        assert record["step_count"] == len(record["steps"])
        assert all(step_id in step_map and step_map[step_id]["route_id"] == record["route_id"] for step_id in record["steps"])
    for item in hierarchy:
        assert item["route_id"] in record_map
        assert all(step_id in step_map and step_map[step_id]["route_id"] == item["route_id"] for block in item["time_blocks"] for step_id in block["step_ids"])
    assert all(item["official_route_id"] in record_map and item["traveler_route_id"] in record_map for item in comparisons)
    fixtures = read_json(OUT / "exp3" / "format_fixture_results.json")
    assert fixtures and all(item["passed"] for item in fixtures)

    coref = read_json(OUT / "exp4" / "pronoun_mentions.json")
    gold_ids = {item["mention_id"] for item in read_json(OUT / "exp4" / "coreference_annotations.json")}
    assert len({item["mention_id"] for item in coref}) == len(coref)
    for item in coref:
        text = sources[item["record_id"]]["content"]
        pspan, sspan = item["pronoun_span"], item["sentence_span"]
        assert text[pspan["start"] : pspan["end"]] == item["pronoun"]
        assert text[sspan["start"] : sspan["end"]] == item["sentence"]
        if item["annotation_status"] == "preannotated_pending_student_review":
            assert item["annotation_origin"] == "assistant_preannotation_pending_student_review"
    evaluation = read_json(OUT / "exp4" / "evaluation.json")
    assert evaluation["student_confirmed_mentions"] == 0
    assert evaluation["formal_student_verified_accuracy"] is None

    mappings = read_json(OUT / "exp5" / "condition_advice_mappings.json")
    assert len({item["mapping_id"] for item in mappings}) == len(mappings)
    dedup_keys = [
        (item["attraction"], item["condition_type"], item["condition"]["normalized"], item["advice"]["normalized"])
        for item in mappings
    ]
    assert len(set(dedup_keys)) == len(dedup_keys)
    evidence_count = 0
    for mapping in mappings:
        assert mapping["evidence_count"] == len(mapping["evidence"])
        assert mapping["student_review"]["status"] == "pending_student_confirmation"
        for evidence in mapping["evidence"]:
            text = sources[evidence["record_id"]]["content"]
            cspan, aspan, sspan = evidence["condition_span"], evidence["advice_span"], evidence["sentence_span"]
            assert text[cspan["start"] : cspan["end"]] == evidence["condition_text"]
            assert text[aspan["start"] : aspan["end"]] == evidence["advice_text"]
            assert text[sspan["start"] : sspan["end"]] == evidence["evidence_sentence"]
            evidence_count += 1
    review_queue = read_json(OUT / "exp5" / "student_review_queue.json")
    assert len(review_queue) == len(mappings) - read_json(OUT / "exp5" / "summary.json")["student_review"]["assistant_precheck_candidates"]

    return {
        "json_schema_parsed": True,
        "route_records": len(route_records),
        "route_step_mentions": len(route_steps),
        "route_comparisons": len(comparisons),
        "route_format_fixtures_passed": len(fixtures),
        "coreference_mentions": len(coref),
        "condition_advice_mappings": len(mappings),
        "condition_evidence_spans_checked": evidence_count,
        "all_reference_and_span_checks_passed": True,
    }


if __name__ == "__main__":
    print(validate())
