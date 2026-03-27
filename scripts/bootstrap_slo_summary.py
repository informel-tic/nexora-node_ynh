#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median


def load_records(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def build_summary(records: list[dict]) -> dict:
    total = len(records)
    if total == 0:
        return {
            "total_runs": 0,
            "success_rate": 0.0,
            "median_duration_seconds": 0,
            "top_failure_reasons": [],
        }

    successes = [r for r in records if r.get("status") == "success"]
    durations = [int(r.get("duration_seconds", 0)) for r in records]
    failures = [r for r in records if r.get("status") == "failure"]
    reasons = Counter(
        str(r.get("reason", "unknown") or "unknown")
        for r in failures
    )

    return {
        "total_runs": total,
        "success_rate": round((len(successes) / total) * 100, 2),
        "median_duration_seconds": int(median(durations)),
        "top_failure_reasons": [
            {"reason": reason, "count": count}
            for reason, count in reasons.most_common(5)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Nexora bootstrap SLO logs")
    parser.add_argument("--log", default="/var/log/nexora/bootstrap-slo.jsonl", help="Path to bootstrap SLO jsonl log")
    parser.add_argument("--output", default="", help="Optional output path for JSON summary")
    args = parser.parse_args()

    log_path = Path(args.log)
    summary = build_summary(load_records(log_path))
    payload = json.dumps(summary, indent=2, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
