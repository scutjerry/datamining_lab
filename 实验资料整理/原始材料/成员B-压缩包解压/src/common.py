# -*- coding: utf-8 -*-
"""Common input, text-offset, and JSON helpers for experiments 3-5."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "outputs"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_poi_terms() -> list[str]:
    terms = []
    for line in (DATA / "entity_dict.txt").read_text(encoding="utf-8").splitlines():
        if line.strip().endswith("|POI"):
            terms.append(line.rsplit("|", 1)[0].strip())
    return sorted(set(terms), key=lambda item: (-len(item), item))


POI_ALIASES = {
    "断桥残雪": "断桥",
    "迪士尼城堡": "奇幻童话城堡",
}


def canonical_poi(surface: str) -> str:
    return POI_ALIASES.get(surface, surface)


def iter_poi_mentions(text: str, terms: list[str]) -> list[dict[str, Any]]:
    if not terms:
        return []
    pattern = re.compile("|".join(re.escape(term) for term in terms))
    return [
        {
            "surface": match.group(),
            "canonical": canonical_poi(match.group()),
            "start": match.start(),
            "end": match.end(),
        }
        for match in pattern.finditer(text)
    ]


def split_sentences_with_offsets(text: str) -> list[tuple[int, int, str]]:
    parts = []
    start = 0
    for match in re.finditer(r"[。！？!?；;\n]+", text):
        end = match.end()
        raw = text[start:end]
        sentence = raw.strip()
        if sentence:
            left = start + len(raw) - len(raw.lstrip())
            right = end - (len(raw) - len(raw.rstrip()))
            parts.append((left, right, text[left:right]))
        start = end
    if text[start:].strip():
        left = start + len(text[start:]) - len(text[start:].lstrip())
        parts.append((left, len(text), text[left:].strip()))
    return parts


def normalize_surface(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    return text.strip(" ，,。；;：:")


def load_sources() -> dict[str, dict[str, Any]]:
    return {row["record_id"]: row for row in read_jsonl(DATA / "cleaned_data.jsonl")}


def ensure_outputs() -> None:
    for number in (3, 4, 5):
        (OUT / f"exp{number}").mkdir(parents=True, exist_ok=True)
