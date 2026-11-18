# -*- coding: utf-8 -*-
"""把成员A的真实数据转换为成员B管线输入格式（cleaned_data.jsonl + entity_dict.txt）"""
import csv, json, hashlib
from pathlib import Path

A_ROOT = Path("/tmp/a-repo/a")
B_DATA = Path("/tmp/bwork/run-real/data")

rows = list(csv.DictReader((A_ROOT/"data/processed/documents.csv").open(encoding="utf-8-sig", newline="")))
prov = {p["doc_id"]: p for p in json.loads((A_ROOT/"data/processed/provenance.json").read_text(encoding="utf-8"))}
type_map = {"official": "official_route", "travelogue": "traveler_note"}

out = []
for r in rows:
    p = prov.get(r["doc_id"], {})
    content = r["content"]
    out.append({
        "record_id": r["doc_id"],
        "attraction": r["scenic"],
        "text_type": type_map[r["doc_type"]],
        "title": p.get("title", ""),
        "source": r["source"],
        "source_url": r["url"],
        "content": content,
        "content_length": len(content),
        "content_hash": hashlib.md5(content.encode("utf-8")).hexdigest()[:12],
    })

with (B_DATA/"cleaned_data.jsonl").open("w", encoding="utf-8", newline="\n") as f:
    for row in out:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

# POI 词典：用 A 的实体结果
ents = json.loads((A_ROOT/"outputs/entities.json").read_text(encoding="utf-8"))
poi_terms = sorted({e["text"] for x in ents for e in x["entities"] if e["type"] == "POI"}, key=lambda t: (-len(t), t))
with (B_DATA/"entity_dict.txt").open("w", encoding="utf-8", newline="\n") as f:
    for t in poi_terms:
        f.write(f"{t}|POI\n")

print(f"records: {len(out)} | POI terms: {len(poi_terms)}")
from collections import Counter
print("attraction x text_type:", Counter((r['attraction'], r['text_type']) for r in out))
