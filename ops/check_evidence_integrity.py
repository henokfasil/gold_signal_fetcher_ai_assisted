#!/usr/bin/env python3
"""Write an atomic, non-performance evidence-integrity status artifact."""

import json
import os
from pathlib import Path

from agent.evidence_integrity import build_evidence_integrity_report


OUTPUT = Path(os.getenv(
    "EVIDENCE_INTEGRITY_STATUS_PATH", "data/evidence_integrity_status.json",
))


def main() -> int:
    report = build_evidence_integrity_report()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(OUTPUT)
    print(json.dumps({
        "monitor_version": report["monitor_version"],
        "generated_at": report["generated_at"],
        "status": report["status"],
        "pilot_candidates": report["pilot_candidates"],
        "context_scope_candidates": report["context_scope_candidates"],
        "issues": report["issues"],
        "performance_columns_read": report["performance_columns_read"],
        "output": str(OUTPUT),
    }))
    return 2 if report["status"] == "DEGRADED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
