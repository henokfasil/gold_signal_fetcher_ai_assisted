#!/usr/bin/env python3
"""Join immutable forward features to matured paper-ledger outcomes."""

import argparse
from pathlib import Path
import pandas as pd

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from config import settings


def export(features_path: Path, ledger_path: Path) -> pd.DataFrame:
    features = pd.read_csv(features_path)
    ledger = pd.read_csv(ledger_path, dtype=str).fillna("")
    outcomes = ledger[ledger["status"].isin(["WIN", "LOSS", "EXPIRED"])].copy()
    outcomes["label_profitable"] = pd.to_numeric(outcomes["pnl_pct"], errors="coerce") > 0
    keep = ["candidate_id", "status", "exit_time", "exit_reason", "pnl_pct", "pnl_usd", "label_profitable"]
    joined = features.merge(outcomes[keep], on="candidate_id", how="inner", validate="one_to_one")
    required = ["timestamp", *GoldFeatureEngineer.FEATURE_COLS, "label_profitable"]
    return joined.dropna(subset=required).sort_values("timestamp")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--features", type=Path, default=settings.FORWARD_FEATURES_CSV)
    parser.add_argument("--ledger", type=Path, default=settings.PAPER_TRADES_CSV)
    args = parser.parse_args()
    result = export(args.features, args.ledger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"exported {len(result)} matured forward observations to {args.output}")


if __name__ == "__main__":
    main()
