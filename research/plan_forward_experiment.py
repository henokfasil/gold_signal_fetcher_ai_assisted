#!/usr/bin/env python3
"""Estimate forward BUY-sweep power using historical weekly dependence.

This is a planning calculation, not evidence of an edge. Historical variance
and dependence may differ in the future, so the fixed six-month run is treated
as a pilot/falsification test rather than a guaranteed confirmatory test.
"""

import argparse
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from research.simulate_portfolio import simulate


Z_ALPHA = NormalDist().inv_cdf(.95)  # one-sided alpha 5%
Z_POWER = NormalDist().inv_cdf(.80)


def cluster_standard_error(opened):
    work = opened.copy()
    work["exit_time"] = pd.to_datetime(work.exit_time, utc=True)
    iso = work.exit_time.dt.isocalendar()
    work["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    grouped = work.groupby("week").net_return_pct.agg(["sum", "count"])
    mean = float(work.net_return_pct.mean())
    influence = grouped["sum"] - mean * grouped["count"]
    weeks, rows = len(grouped), len(work)
    standard_error = math.sqrt(
        weeks / (weeks - 1) * float(np.square(influence).sum()) / rows ** 2
    )
    return {
        "weeks": weeks, "rows": rows, "mean_net_return_pct": mean,
        "cluster_robust_standard_error": standard_error,
        "average_candidates_per_week": rows / weeks,
    }


def projected_power(effect, observed, target_weeks):
    projected_se = observed["cluster_robust_standard_error"] * math.sqrt(
        observed["weeks"] / target_weeks
    )
    return {
        "weeks": float(target_weeks),
        "expected_candidates": float(target_weeks * observed["average_candidates_per_week"]),
        "projected_standard_error": projected_se,
        "one_sided_power": float(1 - NormalDist().cdf(Z_ALPHA - effect / projected_se)),
    }


def plan(path, effects=(.03, .05, .08), pilot_weeks=26, candidate_target=200):
    frame = pd.read_csv(path)
    variant = frame[
        frame.direction.eq("BUY") & frame.liquidity_sweep_1h_present.eq(1)
    ].copy()
    events, portfolio = simulate(variant)
    opened = events[events.decision.eq("OPEN")].copy()
    observed = cluster_standard_error(opened)
    scenarios = {}
    for effect in effects:
        required_weeks = observed["weeks"] * (
            (Z_ALPHA + Z_POWER) * observed["cluster_robust_standard_error"] / effect
        ) ** 2
        candidate_weeks = candidate_target / observed["average_candidates_per_week"]
        scenarios[f"{effect:.3f}_pct_per_candidate"] = {
            "minimum_effect_net_return_pct": effect,
            "weeks_for_80pct_power": required_weeks,
            "months_for_80pct_power": required_weeks / 4.345,
            "candidates_for_80pct_power": (
                required_weeks * observed["average_candidates_per_week"]
            ),
            "power_at_fixed_26_week_pilot": projected_power(effect, observed, pilot_weeks),
            "power_at_200_candidates": projected_power(effect, observed, candidate_weeks),
        }
    return {
        "status": "PLANNING_ONLY_NOT_EDGE_EVIDENCE",
        "population": "BUY + point-in-time 1H liquidity sweep after lifecycle gates",
        "primary_estimand": "mean after-cost net_return_pct per eligible candidate",
        "test": "one-sided weekly-cluster-robust mean greater than zero, alpha=0.05",
        "target_power": .80,
        "historical_variance_reference": observed,
        "historical_portfolio_reference": portfolio,
        "effect_scenarios": scenarios,
        "recommendation": {
            "design": "fixed 26-week pilot with no interim outcome analysis",
            "purpose": "falsification and forward variance estimation, not guaranteed validation",
            "primary_cutoff_rule": (
                "include candidates assigned at or before the fixed cutoff; allow 48 hours "
                "for maturity; never extend because the observed result is inconvenient"
            ),
            "next_confirmation": (
                "use pilot variance to preregister a separately versioned, adequately powered test"
            ),
        },
        "limitations": [
            "Variance and weekly dependence are estimated from contaminated Dukascopy history.",
            "Normal cluster approximation can be inaccurate with regime shifts.",
            "Historical candidate frequency may not transfer to the future Dukascopy runtime window.",
            "Power does not correct hypothesis selection from inspected history.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--effects", type=float, nargs="+", default=[.03, .05, .08])
    parser.add_argument("--pilot-weeks", type=int, default=26)
    parser.add_argument("--candidate-target", type=int, default=200)
    args = parser.parse_args()
    report = plan(args.dataset, args.effects, args.pilot_weeks, args.candidate_target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "historical_variance_reference": report["historical_variance_reference"],
        "effect_scenarios": report["effect_scenarios"],
        "recommendation": report["recommendation"],
    }, indent=2))


if __name__ == "__main__":
    main()
