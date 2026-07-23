#!/usr/bin/env python3
"""Collect one delayed, native-timeframe concordance reference snapshot."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agent.event_feature_concordance import DelayedNativeReferenceArchive
from ops.collect_dukascopy_snapshot import collect


STAGING_PATH = Path(os.getenv(
    "EVENT_CONCORDANCE_REFERENCE_STAGING_PATH",
    "/tmp/event_concordance_reference_snapshot.json",
))
REFERENCE_BAR_COUNT = 400


def main() -> int:
    collected_at = datetime.now(timezone.utc)
    cutoff = collected_at.replace(hour=0, minute=0, second=0, microsecond=0)
    payload = collect(
        STAGING_PATH,
        captured_at=cutoff,
        bar_count=REFERENCE_BAR_COUNT,
    )
    archived = DelayedNativeReferenceArchive().store(
        payload,
        collected_at=collected_at,
    )
    print(json.dumps({
        "status": archived["status"],
        "reference_cutoff": archived["reference_cutoff"],
        "latest_decision_time": archived["latest_decision_time"],
        "snapshot_content_sha256": archived["snapshot_content_sha256"],
        "snapshot_path": archived["snapshot_path"],
        "manifest_path": archived["manifest_path"],
        "paper_research_only": True,
        "performance_columns_read": [],
        "decision_effect": "NONE_OBSERVATION_ONLY",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
