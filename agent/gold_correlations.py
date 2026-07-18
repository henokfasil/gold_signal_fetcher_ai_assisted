"""Point-in-time macro validation for XAUUSD paper signals."""

import json
from datetime import datetime, timezone

from config import settings


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class GoldCorrelationValidator:
    """Validate a signal only from a fresh, externally produced macro snapshot.

    Expected JSON fields are ``timestamp``, ``dxy_return_pct``,
    ``real_yield_change_bps`` and ``vix_return_pct``. Missing or stale data is
    reported as unavailable rather than replaced with invented constants.
    """

    def load_snapshot(self) -> dict:
        path = settings.MACRO_SNAPSHOT_PATH
        if not path.exists():
            return {"available": False, "reason": "macro snapshot missing"}
        try:
            snapshot = json.loads(path.read_text())
            timestamp = _parse_utc(str(snapshot["timestamp"]))
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
            if age < 0 or age > settings.SNAPSHOT_MAX_AGE_SECONDS:
                return {"available": False, "reason": f"macro snapshot stale ({age:.0f}s)"}
            values = {
                "dxy_return_pct": float(snapshot["dxy_return_pct"]),
                "real_yield_change_bps": float(snapshot["real_yield_change_bps"]),
                "vix_return_pct": float(snapshot["vix_return_pct"]),
            }
            return {"available": True, "timestamp": timestamp.isoformat(), **values}
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            return {"available": False, "reason": f"invalid macro snapshot: {exc}"}

    def validate_signal(self, signal_direction: str) -> dict:
        snapshot = self.load_snapshot()
        if not snapshot["available"]:
            return {
                "available": False,
                "is_confirmed": False,
                "is_blocked": False,
                "score": None,
                "reasoning": snapshot["reason"],
                "snapshot": None,
            }

        direction = signal_direction.upper()
        if direction not in {"BUY", "SELL"}:
            return {"available": True, "is_confirmed": False, "is_blocked": True,
                    "score": 0, "reasoning": "invalid signal direction", "snapshot": snapshot}

        # Score directional alignment without claiming these relationships are
        # invariant. Thresholds must later be estimated in walk-forward tests.
        multiplier = 1 if direction == "BUY" else -1
        supports = [
            (-snapshot["dxy_return_pct"] * multiplier) > 0,
            (-snapshot["real_yield_change_bps"] * multiplier) > 0,
            (snapshot["vix_return_pct"] * multiplier) > 0,
        ]
        score = 25 + 25 * sum(supports)
        strong_conflict = (
            direction == "BUY"
            and snapshot["dxy_return_pct"] >= 0.5
            and snapshot["real_yield_change_bps"] >= 5
        ) or (
            direction == "SELL"
            and snapshot["dxy_return_pct"] <= -0.5
            and snapshot["real_yield_change_bps"] <= -5
        )
        return {
            "available": True,
            "is_confirmed": score >= 50 and not strong_conflict,
            "is_blocked": strong_conflict,
            "score": score,
            "reasoning": f"{sum(supports)}/3 macro factors align" + ("; strong conflict" if strong_conflict else ""),
            "snapshot": snapshot,
        }
