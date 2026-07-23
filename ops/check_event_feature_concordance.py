#!/usr/bin/env python3
"""Write the atomic, outcome-blind event-feature concordance status."""

import json
import os
from pathlib import Path

from agent.event_feature_concordance import (
    build_event_feature_concordance_report,
)
from config import settings


OUTPUT = settings.EVENT_FEATURE_CONCORDANCE_STATUS_PATH


def main() -> int:
    report = build_event_feature_concordance_report()
    Path(OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(OUTPUT).with_suffix(Path(OUTPUT).suffix + ".tmp")
    with temporary.open("w") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(OUTPUT)
    print(json.dumps({
        "monitor_version": report["monitor_version"],
        "generated_at": report["generated_at"],
        "status": report["status"],
        "runtime_scans": report["runtime_scans"],
        "self_replay_decisions": report["archived_self_replay_decisions"],
        "compared_decision_times": report["compared_decision_times"],
        "compared_events": report["compared_events"],
        "shadow_registration_eligible": report["shadow_registration_eligible"],
        "feature_use_authorized": report["feature_use_authorized"],
        "performance_columns_read": report["performance_columns_read"],
        "issues": report["issues"],
        "output": str(OUTPUT),
    }))
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
