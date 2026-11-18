# -*- coding: utf-8 -*-
"""Run only the independently scoped experiments 3, 4, and 5."""

from __future__ import annotations

import json
from pathlib import Path

from src.common import OUT, ensure_outputs, write_json
from src.exp3_routes import run as run_exp3
from src.exp4_coref import run as run_exp4
from src.exp5_conditions import run as run_exp5
from src.build_delivery_docs import build_examples, build_report
from src.validate_outputs import validate


def main() -> None:
    ensure_outputs()
    results = {
        "experiment_3": run_exp3(),
        "experiment_4": run_exp4(),
        "experiment_5": run_exp5(),
    }
    results["output_validation"] = validate()
    build_examples()
    build_report()
    write_json(OUT / "run_summary.json", results)
    for name, value in results.items():
        print(f"[SUCCESS] {name}: {json.dumps(value, ensure_ascii=False)}")
    print("Experiments 3, 4, and 5 completed.")


if __name__ == "__main__":
    main()
