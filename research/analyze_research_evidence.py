#!/usr/bin/env python3
"""Direction, dependence, bootstrap and SMC-ablation evidence report."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.simulate_portfolio import simulate


VARIANTS = {
    "structure_baseline": lambda d: pd.Series(True, index=d.index),
    "structure_plus_liquidity_sweep": lambda d: d.liquidity_sweep_1h_present == 1,
    "structure_plus_order_block": lambda d: d.price_at_ob == 1,
    "structure_plus_fvg": lambda d: d.fvg_1h_present == 1,
    "structure_plus_choch": lambda d: (d.choch_4h_present == 1) | (d.choch_15m_present == 1),
    "full_smc_candidate_universe": lambda d: pd.Series(True, index=d.index),
}


def label_uniqueness(frame: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Average inverse label concurrency on a 15-minute event grid."""
    starts = pd.to_datetime(frame.timestamp, utc=True).dt.floor("15min")
    ends = pd.to_datetime(frame.exit_time, utc=True).dt.ceil("15min")
    origin = starts.min()
    start_index = ((starts - origin).dt.total_seconds() // 900).astype(int).to_numpy()
    end_index = ((ends - origin).dt.total_seconds() // 900).astype(int).to_numpy()
    difference = np.zeros(int(end_index.max()) + 2, dtype=np.int32)
    np.add.at(difference, start_index, 1)
    np.add.at(difference, end_index + 1, -1)
    concurrency = np.cumsum(difference)[:-1]
    inverse = np.divide(1.0, concurrency, out=np.zeros_like(concurrency, dtype=float), where=concurrency > 0)
    prefix = np.concatenate(([0.0], np.cumsum(inverse)))
    weights = (prefix[end_index + 1] - prefix[start_index]) / (end_index - start_index + 1)
    series = pd.Series(weights, index=frame.index, name="label_uniqueness")
    kish = float(weights.sum() ** 2 / np.square(weights).sum())
    return series, {"rows": len(frame), "sum_uniqueness": float(weights.sum()),
                    "kish_effective_sample_size": kish,
                    "median_uniqueness": float(np.median(weights)),
                    "p05_uniqueness": float(np.quantile(weights, .05)),
                    "max_label_concurrency": int(concurrency.max())}


def weekly_block_bootstrap(opened: pd.DataFrame, starting_capital=10_000.0,
                           samples=2_000, seed=42) -> dict:
    data = opened.copy()
    if data.empty:
        return {"samples": samples, "weeks": 0}
    data["exit_time"] = pd.to_datetime(data.exit_time, utc=True)
    iso = data.exit_time.dt.isocalendar()
    data["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    weeks = []
    for _, group in data.groupby("week", sort=True):
        pnl = group.pnl_usd.to_numpy(float)
        weeks.append((pnl.sum(), pnl[pnl > 0].sum(), abs(pnl[pnl < 0].sum()), len(pnl)))
    values = np.asarray(weeks, dtype=float)
    rng = np.random.default_rng(seed)
    returns, factors, drawdowns, means = [], [], [], []
    for _ in range(samples):
        draw = values[rng.integers(0, len(values), len(values))]
        weekly_pnl = draw[:, 0]
        curve = starting_capital + np.cumsum(weekly_pnl)
        peaks = np.maximum.accumulate(np.concatenate(([starting_capital], curve)))
        full_curve = np.concatenate(([starting_capital], curve))
        returns.append(weekly_pnl.sum() / starting_capital * 100)
        factors.append(draw[:, 1].sum() / draw[:, 2].sum() if draw[:, 2].sum() else np.nan)
        drawdowns.append(np.max((peaks - full_curve) / peaks) * 100)
        means.append(weekly_pnl.sum() / draw[:, 3].sum())
    def interval(values):
        clean = np.asarray(values)[np.isfinite(values)]
        return {"median": float(np.median(clean)), "lower_95": float(np.quantile(clean, .025)),
                "upper_95": float(np.quantile(clean, .975))}
    return {"samples": samples, "weeks": len(values), "seed": seed,
            "return_pct": interval(returns), "profit_factor": interval(factors),
            "max_drawdown_pct": interval(drawdowns), "mean_pnl_usd_per_trade": interval(means)}


def opened_events(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    events, report = simulate(frame)
    return events[events.decision == "OPEN"].copy(), report


def analyze(frame: pd.DataFrame) -> dict:
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data.timestamp, utc=True)
    data["exit_time"] = pd.to_datetime(data.exit_time, utc=True, errors="coerce")
    eligible = data[(data.rr_ratio >= 2) & data.label_profitable.notna() & data.exit_time.notna()].copy()
    weights, dependence = label_uniqueness(eligible)
    eligible["label_uniqueness"] = weights
    directions = {}
    for direction in ("BUY", "SELL"):
        opened, report = opened_events(data[data.direction == direction])
        directions[direction] = {"portfolio": report,
                                 "weekly_block_bootstrap": weekly_block_bootstrap(opened)}
    ablations = {}
    for name, selector in VARIANTS.items():
        variant = data[selector(data)].copy()
        yearly = {}
        for year in sorted(variant.timestamp.dt.year.unique()):
            year_data = variant[variant.timestamp.dt.year == year]
            if len(year_data) < 100:
                continue
            _, report = opened_events(year_data)
            yearly[str(int(year))] = {"opened": report["opened"], "return_pct": report["return_pct"],
                                      "profit_factor": report["profit_factor"],
                                      "max_drawdown_pct": report["max_drawdown_pct"],
                                      "buy_pnl_usd": report["by_direction"].get("BUY", {}).get("pnl_usd", 0),
                                      "sell_pnl_usd": report["by_direction"].get("SELL", {}).get("pnl_usd", 0)}
        opened, overall = opened_events(variant)
        direction_bootstraps = {}
        for direction in ("BUY", "SELL"):
            direction_opened, direction_report = opened_events(
                variant[variant.direction == direction]
            )
            direction_bootstraps[direction] = {
                "portfolio": direction_report,
                "weekly_block_bootstrap": weekly_block_bootstrap(direction_opened),
            }
        ablations[name] = {"overall": overall,
                           "weekly_block_bootstrap": weekly_block_bootstrap(opened),
                           "by_direction": direction_bootstraps,
                           "yearly": yearly,
                           "positive_years": sum(v["return_pct"] > 0 for v in yearly.values()),
                           "evaluated_years": len(yearly)}
    return {"status": "DEVELOPMENT_DIAGNOSTIC_ONLY", "eligible_rows": len(eligible),
            "dependence": dependence, "directional_portfolios": directions,
            "smc_ablations": ablations,
            "limitations": ["2020-2026 influenced development and is not untouched.",
                            "Ablations filter the existing candidate universe; they do not regenerate omitted setups.",
                            "Bootstrap resamples calendar weeks and does not remove feed mismatch.",
                            "No result in this report authorizes a model or live trading."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(pd.read_csv(args.dataset))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
