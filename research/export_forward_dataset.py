#!/usr/bin/env python3
"""Join immutable forward features, assignments and matured shadow outcomes."""

import argparse
from pathlib import Path
import pandas as pd

from agent.ml_feature_engineer_gold import GoldFeatureEngineer
from config import settings


def export(features_path: Path, outcomes_path: Path,
           assignments_path: Path = None) -> pd.DataFrame:
    features = pd.read_csv(features_path)
    outcomes = pd.read_csv(outcomes_path, dtype=str).fillna("")
    assignments = pd.read_csv(
        assignments_path or settings.FORWARD_VARIANT_ASSIGNMENTS_CSV, dtype=str
    ).fillna("")
    outcomes = outcomes[outcomes["status"].isin(["TP", "SL", "EXPIRY"])].copy()
    outcomes["label_profitable"] = pd.to_numeric(outcomes["label_profitable"], errors="coerce")
    outcome_keep = ["candidate_id", "status", "exit_time", "exit_price", "net_return_pct",
                    "label_note", "label_profitable"]
    assignment_keep = [
        "candidate_id", "experiment_version", "contract_sha256", "baseline_v1",
        "buy_liquidity_v1", "min_rr_eligible", "liquidity_sweep_1h_present",
        "strategy_config_version", "feature_schema_sha256", "ml_model_version",
        "claude_model", "claude_prompt_version", "paper_trading", "assignment_note",
    ]
    missing = [column for column in assignment_keep if column not in assignments]
    if missing:
        raise ValueError(f"variant assignment file missing columns: {', '.join(missing)}")
    assignment_rows = assignments[assignment_keep].rename(columns={
        "liquidity_sweep_1h_present": "assignment_liquidity_sweep_1h_present",
    })
    joined = features.merge(
        assignment_rows, on="candidate_id", how="inner", validate="one_to_one"
    ).merge(outcomes[outcome_keep], on="candidate_id", how="inner", validate="one_to_one")
    required = ["timestamp", "experiment_version", *GoldFeatureEngineer.FEATURE_COLS,
                "label_profitable"]
    return joined.dropna(subset=required).sort_values("timestamp")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--features", type=Path, default=settings.FORWARD_FEATURES_CSV)
    parser.add_argument("--outcomes", type=Path, default=settings.FORWARD_OUTCOMES_CSV)
    parser.add_argument("--assignments", type=Path,
                        default=settings.FORWARD_VARIANT_ASSIGNMENTS_CSV)
    args = parser.parse_args()
    result = export(args.features, args.outcomes, args.assignments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"exported {len(result)} matured forward observations to {args.output}")


if __name__ == "__main__":
    main()
