#!/usr/bin/env python3
"""Evaluate the frozen candidate-generation v2 setup taxonomy.

This is a fixed-rule, development-history experiment.  It fits no model and
selects no threshold.  Every variant is defined from candidate-time SMC fields,
then replayed with the runtime-aligned cooldown and portfolio gates.  The only
promotable development hypothesis is fixed in the hash-locked contract; all
other variants are controls or secondary diagnostics.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.analyze_research_evidence import label_uniqueness
from research.simulate_portfolio import simulate


CONTRACT_PATH = Path("config/candidate_generation_v2.json")
EXPECTED_CONTRACT_SHA256 = (
    "484246c8c1c4cc464a7da9059fac9da1235ebf4d5ad90442fbb2c68642130da9"
)
REGISTERED_BOOTSTRAP_SAMPLES = 2000
REGISTERED_SEED = 42
PRIMARY_VARIANT = "sweep_value_retest_primary"
PRIMARY_COMPARATORS = ("trade_all_control", "liquidity_sweep_control")
VARIANT_EXPRESSIONS = {
    "trade_all_control": "all eligible candidates",
    "smc_score_85_control": "high_smc_score",
    "liquidity_sweep_control": "liquidity_sweep",
    "value_zone_only": "directional_value_zone",
    "zone_retest_only": "zone_retest",
    "change_of_character_only": "change_of_character",
    "multi_timeframe_alignment_only": "multi_timeframe_alignment",
    "sweep_and_change_of_character": "liquidity_sweep and change_of_character",
    "sweep_and_value": "liquidity_sweep and directional_value_zone",
    "sweep_and_retest": "liquidity_sweep and zone_retest",
    "sweep_value_retest_primary": (
        "liquidity_sweep and directional_value_zone and zone_retest"
    ),
}
REQUIRED_COLUMNS = {
    "timestamp", "direction", "entry", "executable_entry", "exit_time",
    "stop_loss", "take_profit", "rr_ratio", "label_profitable",
    "label_status", "net_return_pct", "smc_score", "structure_1d_encoded",
    "structure_1h_encoded", "choch_4h_present", "choch_15m_present",
    "liquidity_sweep_1h_present", "price_at_ob", "fvg_1h_present",
    "premium_discount_position",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    contract = json.loads(raw)
    if digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("candidate-generation contract hash mismatch; register a new version")
    variants = contract.get("registered_variants", {})
    expressions = {name: item.get("expression") for name, item in variants.items()}
    evaluation = contract.get("evaluation_contract", {})
    if (contract.get("schema_version") != 1 or
            contract.get("contract_version") != "candidate-generation-20260719-v2" or
            contract.get("paper_research_only") is not True or
            expressions != VARIANT_EXPRESSIONS or
            evaluation.get("primary_variant") != PRIMARY_VARIANT or
            tuple(evaluation.get("primary_comparators", [])) != PRIMARY_COMPARATORS or
            evaluation.get("secondary_variants_cannot_select_a_new_primary_rule") is not True):
        raise RuntimeError("candidate-generation contract schema mismatch")
    return contract, digest


def _validate_registered_evaluation(contract: dict, bootstrap_samples: int,
                                    seed: int) -> None:
    evaluation = contract.get("evaluation_contract", {})
    candidate = contract.get("candidate_contract", {})
    portfolio = candidate.get("runtime_aligned_portfolio", {})
    gates = contract.get("primary_direction_promotion_gates", {})
    checks = {
        "bootstrap samples": bootstrap_samples == REGISTERED_BOOTSTRAP_SAMPLES,
        "bootstrap seed": seed == REGISTERED_SEED,
        "evaluation years": evaluation.get("primary_evaluation_candidate_years") == [
            2022, 2023, 2024, 2025, 2026,
        ],
        "no training": evaluation.get("training_or_threshold_selection") ==
        "NONE_FIXED_RULES_ONLY",
        "base slippage": float(evaluation.get("base_slippage_points_per_side", -1)) == 0.10,
        "stress slippage": float(evaluation.get("stress_slippage_points_per_side", -1)) == 0.25,
        "cooldown": float(candidate.get("setup_cooldown_hours", -1)) == 4.0,
        "nearby entry": float(candidate.get("nearby_entry_fraction", -1)) == 0.001,
        "minimum rr": float(candidate.get("minimum_risk_reward_ratio", -1)) == 2.0,
        "starting capital": float(portfolio.get("starting_capital_usd", -1)) == 10_000.0,
        "paper notional": float(portfolio.get("paper_notional_per_trade_usd", -1)) == 5_000.0,
        "max open": int(portfolio.get("maximum_open_positions", -1)) == 15,
        "daily cap": float(portfolio.get("daily_realized_loss_cap_pct", -1)) == 3.0,
        "weekly cap": float(portfolio.get("weekly_realized_loss_cap_pct", -1)) == 6.0,
        "opened gate": int(gates.get("minimum_opened_candidates", -1)) == 300,
        "weeks gate": int(gates.get("minimum_calendar_weeks", -1)) == 100,
        "kish gate": float(gates.get("minimum_kish_effective_sample_size", -1)) == 200,
        "fold gate": int(gates.get("minimum_positive_calendar_folds", -1)) == 3,
        "drawdown gate": float(gates.get("maximum_historical_drawdown_pct", -1)) == 25.0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "candidate-generation implementation differs from registered evaluation: "
            + ", ".join(failed)
        )


def variant_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Return the frozen, candidate-time-only setup membership masks."""
    required = REQUIRED_COLUMNS - {
        "timestamp", "entry", "executable_entry", "exit_time", "stop_loss",
        "take_profit", "label_profitable", "label_status", "net_return_pct",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"candidate setup fields missing {sorted(missing)}")
    direction = frame["direction"].astype(str).str.upper()
    expected = direction.map({"BUY": 1.0, "SELL": -1.0})
    sweep = pd.to_numeric(frame["liquidity_sweep_1h_present"], errors="coerce").eq(1)
    value = (
        direction.eq("BUY") &
        pd.to_numeric(frame["premium_discount_position"], errors="coerce").le(0.5)
    ) | (
        direction.eq("SELL") &
        pd.to_numeric(frame["premium_discount_position"], errors="coerce").ge(0.5)
    )
    retest = (
        pd.to_numeric(frame["price_at_ob"], errors="coerce").eq(1) |
        pd.to_numeric(frame["fvg_1h_present"], errors="coerce").eq(1)
    )
    change = (
        pd.to_numeric(frame["choch_4h_present"], errors="coerce").eq(1) |
        pd.to_numeric(frame["choch_15m_present"], errors="coerce").eq(1)
    )
    aligned = (
        pd.to_numeric(frame["structure_1d_encoded"], errors="coerce").eq(expected) &
        pd.to_numeric(frame["structure_1h_encoded"], errors="coerce").eq(expected)
    )
    high_score = pd.to_numeric(frame["smc_score"], errors="coerce").ge(85)
    all_rows = pd.Series(True, index=frame.index)
    return {
        "trade_all_control": all_rows,
        "smc_score_85_control": high_score,
        "liquidity_sweep_control": sweep,
        "value_zone_only": value,
        "zone_retest_only": retest,
        "change_of_character_only": change,
        "multi_timeframe_alignment_only": aligned,
        "sweep_and_change_of_character": sweep & change,
        "sweep_and_value": sweep & value,
        "sweep_and_retest": sweep & retest,
        "sweep_value_retest_primary": sweep & value & retest,
    }


def _prepare(path: Path, contract: dict) -> pd.DataFrame:
    lineage = contract["lineage"]
    manifest_path = Path(lineage["candidate_manifest"])
    if (_sha256(path) != lineage["candidate_dataset_sha256"] or
            _sha256(manifest_path) != lineage["candidate_manifest_sha256"]):
        raise RuntimeError("candidate-generation source lineage hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("dataset_sha256") != lineage["candidate_dataset_sha256"]:
        raise RuntimeError("candidate-generation source manifest does not match dataset")
    frame = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"candidate dataset missing {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
    numeric = [
        "entry", "executable_entry", "rr_ratio", "net_return_pct", "smc_score",
        "structure_1d_encoded", "structure_1h_encoded", "choch_4h_present",
        "choch_15m_present", "liquidity_sweep_1h_present", "price_at_ob",
        "fvg_1h_present", "premium_discount_position",
    ]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame = frame[
        frame["direction"].isin(["BUY", "SELL"]) &
        frame["rr_ratio"].ge(contract["candidate_contract"]["minimum_risk_reward_ratio"]) &
        frame["label_profitable"].notna() & frame["exit_time"].notna() &
        frame["net_return_pct"].notna() & frame["executable_entry"].gt(0)
    ].copy()
    years = contract["evaluation_contract"]["primary_evaluation_candidate_years"]
    frame = frame[frame["timestamp"].dt.year.isin(years)]
    return frame.sort_values("timestamp").reset_index(drop=True)


def _simulation_kwargs(contract: dict) -> dict:
    candidate = contract["candidate_contract"]
    portfolio = candidate["runtime_aligned_portfolio"]
    return {
        "starting_capital": portfolio["starting_capital_usd"],
        "notional": portfolio["paper_notional_per_trade_usd"],
        "cooldown_hours": candidate["setup_cooldown_hours"],
        "max_open": portfolio["maximum_open_positions"],
        "min_rr": candidate["minimum_risk_reward_ratio"],
        "daily_loss_cap_pct": portfolio["daily_realized_loss_cap_pct"],
        "weekly_loss_cap_pct": portfolio["weekly_realized_loss_cap_pct"],
    }


def _opened(frame: pd.DataFrame, contract: dict) -> tuple[pd.DataFrame, dict]:
    events, report = simulate(frame, **_simulation_kwargs(contract))
    if events.empty:
        return events, report
    return events[events["decision"].eq("OPEN")].copy(), report


def _stress_returns(frame: pd.DataFrame, contract: dict) -> pd.DataFrame:
    evaluation = contract["evaluation_contract"]
    incremental_points = 2 * (
        evaluation["stress_slippage_points_per_side"] -
        evaluation["base_slippage_points_per_side"]
    )
    stressed = frame.copy()
    stressed["net_return_pct"] = (
        stressed["net_return_pct"] -
        incremental_points / stressed["executable_entry"] * 100
    )
    return stressed


def _week_key(values: pd.Series) -> pd.Series:
    timestamp = pd.to_datetime(values, utc=True)
    iso = timestamp.dt.isocalendar()
    return iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)


def _weekly_interval(opened: pd.DataFrame, samples: int, seed: int,
                     starting_capital: float, notional: float) -> dict:
    if opened.empty:
        return {
            "method": "calendar-week block bootstrap", "samples": samples,
            "weeks": 0, "seed": seed, "mean_net_return_pct": None,
            "portfolio_return_pct": None, "profit_factor": None,
        }
    work = opened.copy()
    work["week"] = _week_key(work["exit_time"])
    blocks = []
    for _, group in work.groupby("week", sort=True):
        returns = group["net_return_pct"].to_numpy(float)
        pnl = notional * returns / 100
        blocks.append((returns.sum(), len(returns), pnl[pnl > 0].sum(),
                       abs(pnl[pnl < 0].sum())))
    values = np.asarray(blocks, dtype=float)
    rng = np.random.default_rng(seed)
    means, portfolio_returns, factors = [], [], []
    for _ in range(samples):
        draw = values[rng.integers(0, len(values), len(values))]
        count = draw[:, 1].sum()
        means.append(draw[:, 0].sum() / count)
        portfolio_returns.append(
            (notional * draw[:, 0].sum() / 100) / starting_capital * 100
        )
        losses = draw[:, 3].sum()
        factors.append(draw[:, 2].sum() / losses if losses else np.nan)

    def interval(items):
        clean = np.asarray(items, dtype=float)
        clean = clean[np.isfinite(clean)]
        if not len(clean):
            return None
        return {
            "median": float(np.median(clean)),
            "lower_97_5_one_sided": float(np.quantile(clean, 0.025)),
            "upper_97_5": float(np.quantile(clean, 0.975)),
        }

    return {
        "method": "calendar-week block bootstrap",
        "samples": samples,
        "weeks": len(blocks),
        "seed": seed,
        "mean_net_return_pct": interval(means),
        "portfolio_return_pct": interval(portfolio_returns),
        "profit_factor": interval(factors),
    }


def _paired_mean_interval(primary: pd.DataFrame, control: pd.DataFrame,
                          samples: int, seed: int) -> dict:
    def aggregate(frame):
        if frame.empty:
            return {}
        work = frame.copy()
        work["week"] = _week_key(work["exit_time"])
        return {
            week: (float(group["net_return_pct"].sum()), len(group))
            for week, group in work.groupby("week", sort=True)
        }

    left, right = aggregate(primary), aggregate(control)
    weeks = sorted(set(left) | set(right))
    values = np.asarray([
        (*left.get(week, (0.0, 0)), *right.get(week, (0.0, 0)))
        for week in weeks
    ], dtype=float)
    if not weeks:
        return {"method": "paired calendar-week block bootstrap", "weeks": 0,
                "samples": samples, "seed": seed, "mean_difference_pct": None}
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(samples):
        draw = values[rng.integers(0, len(values), len(values))]
        left_count, right_count = draw[:, 1].sum(), draw[:, 3].sum()
        if left_count and right_count:
            differences.append(
                draw[:, 0].sum() / left_count - draw[:, 2].sum() / right_count
            )
    difference = np.asarray(differences, dtype=float)
    return {
        "method": "paired calendar-week block bootstrap of mean return per opened trade",
        "weeks": len(weeks), "samples": len(difference), "seed": seed,
        "mean_difference_pct": {
            "median": float(np.median(difference)),
            "lower_97_5_one_sided": float(np.quantile(difference, 0.025)),
            "upper_97_5": float(np.quantile(difference, 0.975)),
        },
    }


def _dependence(opened: pd.DataFrame) -> dict:
    if opened.empty:
        return {
            "rows": 0, "sum_uniqueness": 0.0,
            "kish_effective_sample_size": 0.0, "median_uniqueness": None,
            "p05_uniqueness": None, "max_label_concurrency": 0,
        }
    intervals = opened[["timestamp", "exit_time"]]
    _, report = label_uniqueness(intervals)
    return report


def _fold_reports(frame: pd.DataFrame, contract: dict) -> list[dict]:
    reports = []
    years = contract["evaluation_contract"]["primary_evaluation_candidate_years"]
    for year in years:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        fold = frame[(frame["timestamp"] >= start) & (frame["timestamp"] < end)]
        if year != years[-1]:
            fold = fold[fold["exit_time"] < end]
        opened, report = _opened(fold, contract)
        reports.append({
            "candidate_year": year,
            "membership_rows": len(fold),
            "opened": len(opened),
            "mean_net_return_pct": (
                float(opened["net_return_pct"].mean()) if len(opened) else None
            ),
            "return_pct": report["return_pct"],
            "profit_factor": report["profit_factor"],
            "max_drawdown_pct": report["max_drawdown_pct"],
        })
    return reports


def benchmark(path: Path, bootstrap_samples: int = REGISTERED_BOOTSTRAP_SAMPLES,
              seed: int = REGISTERED_SEED,
              contract_path: Path = CONTRACT_PATH) -> dict:
    contract, contract_sha = load_contract(contract_path)
    _validate_registered_evaluation(contract, bootstrap_samples, seed)
    frame = _prepare(path, contract)
    masks = variant_masks(frame)
    starting_capital = contract["candidate_contract"]["runtime_aligned_portfolio"][
        "starting_capital_usd"
    ]
    notional = contract["candidate_contract"]["runtime_aligned_portfolio"][
        "paper_notional_per_trade_usd"
    ]
    results, opened_cache = {}, {}
    for variant_offset, (name, mask) in enumerate(masks.items()):
        variant_frame = frame[mask].copy()
        variant_results = {}
        for direction_offset, direction in enumerate(("BUY", "SELL"), start=1):
            side = variant_frame[variant_frame["direction"].eq(direction)].copy()
            opened, portfolio = _opened(side, contract)
            stressed_opened, stressed_portfolio = _opened(
                _stress_returns(side, contract), contract,
            )
            opened_cache[(name, direction)] = opened
            interval_seed = seed + variant_offset * 100 + direction_offset
            folds = _fold_reports(side, contract)
            variant_results[direction] = {
                "membership_rows": len(side),
                "opened_rows": len(opened),
                "calendar_weeks": (
                    int(_week_key(opened["exit_time"]).nunique()) if len(opened) else 0
                ),
                "portfolio": portfolio,
                "weekly_block_interval": _weekly_interval(
                    opened, bootstrap_samples, interval_seed, starting_capital, notional,
                ),
                "dependence": _dependence(opened),
                "folds": folds,
                "positive_calendar_folds": sum(
                    item["mean_net_return_pct"] is not None and
                    item["mean_net_return_pct"] > 0 for item in folds
                ),
                "cost_stress_0_25_points_per_side": {
                    "portfolio": stressed_portfolio,
                    "weekly_block_interval": _weekly_interval(
                        stressed_opened, bootstrap_samples, interval_seed + 50_000,
                        starting_capital, notional,
                    ),
                },
                "primary_gate_eligible": name == PRIMARY_VARIANT,
            }
        results[name] = {
            "role": contract["registered_variants"][name]["role"],
            "expression": VARIANT_EXPRESSIONS[name],
            "directions": variant_results,
        }

    gates = contract["primary_direction_promotion_gates"]
    passing_directions = []
    primary = results[PRIMARY_VARIANT]["directions"]
    for direction_offset, direction in enumerate(("BUY", "SELL"), start=1):
        item = primary[direction]
        comparisons = {}
        for comparator_offset, comparator in enumerate(PRIMARY_COMPARATORS, start=1):
            comparisons[comparator] = _paired_mean_interval(
                opened_cache[(PRIMARY_VARIANT, direction)],
                opened_cache[(comparator, direction)],
                bootstrap_samples,
                seed + 1_000_000 + direction_offset * 100 + comparator_offset,
            )
        item["paired_comparisons"] = comparisons
        base = item["weekly_block_interval"]
        stress = item["cost_stress_0_25_points_per_side"]["weekly_block_interval"]
        direction_gates = {
            "opened_candidates_at_least_300": (
                item["opened_rows"] >= gates["minimum_opened_candidates"]
            ),
            "calendar_weeks_at_least_100": (
                item["calendar_weeks"] >= gates["minimum_calendar_weeks"]
            ),
            "kish_effective_sample_size_at_least_200": (
                item["dependence"]["kish_effective_sample_size"] >=
                gates["minimum_kish_effective_sample_size"]
            ),
            "positive_calendar_folds_at_least_3": (
                item["positive_calendar_folds"] >= gates["minimum_positive_calendar_folds"]
            ),
            "maximum_drawdown_at_most_25_pct": (
                item["portfolio"]["max_drawdown_pct"] <=
                gates["maximum_historical_drawdown_pct"]
            ),
            "base_mean_return_lower_97_5_above_zero": (
                base["mean_net_return_pct"] is not None and
                base["mean_net_return_pct"]["lower_97_5_one_sided"] > 0
            ),
            "base_profit_factor_lower_97_5_above_one": (
                base["profit_factor"] is not None and
                base["profit_factor"]["lower_97_5_one_sided"] > 1
            ),
            "stress_mean_return_lower_97_5_above_zero": (
                stress["mean_net_return_pct"] is not None and
                stress["mean_net_return_pct"]["lower_97_5_one_sided"] > 0
            ),
            "paired_improvement_vs_trade_all_lower_97_5_above_zero": (
                comparisons["trade_all_control"]["mean_difference_pct"]
                ["lower_97_5_one_sided"] > 0
            ),
            "paired_improvement_vs_liquidity_sweep_lower_97_5_above_zero": (
                comparisons["liquidity_sweep_control"]["mean_difference_pct"]
                ["lower_97_5_one_sided"] > 0
            ),
        }
        item["primary_direction_promotion_gates"] = direction_gates
        item["all_primary_direction_promotion_gates_pass"] = all(direction_gates.values())
        if item["all_primary_direction_promotion_gates_pass"]:
            passing_directions.append(direction)

    return {
        "status": (
            "CANDIDATE_GENERATION_V2_DEVELOPMENT_GATES_PASS"
            if passing_directions else "REJECT_CANDIDATE_GENERATION_V2"
        ),
        "scope": "CONTAMINATED_DEVELOPMENT_HISTORY_NO_RUNTIME_OR_EDGE_AUTHORIZATION",
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_sha,
        "dataset_sha256": _sha256(path),
        "dataset_manifest_sha256": _sha256(Path(contract["lineage"]["candidate_manifest"])),
        "benchmark_script_sha256": _sha256(Path(__file__)),
        "eligible_evaluation_rows": len(frame),
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "primary_variant": PRIMARY_VARIANT,
        "primary_comparators": list(PRIMARY_COMPARATORS),
        "primary_passing_directions": passing_directions,
        "model_artifact_created": False,
        "runtime_changed": False,
        "telegram_changed": False,
        "secondary_selection_permitted": False,
        "variants": results,
        "limitations": [
            "The full historical period has influenced research and is not untouched evidence.",
            "Rules filter the existing SMC candidate universe; they do not regenerate omitted market setups.",
            "Weekly blocks and cooldown reduce dependence but do not create independent observations.",
            "A development pass can only authorize registration of a future shadow hypothesis.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int,
                        default=REGISTERED_BOOTSTRAP_SAMPLES)
    parser.add_argument("--seed", type=int, default=REGISTERED_SEED)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    report = benchmark(
        args.dataset, args.bootstrap_samples, args.seed, args.contract,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({
        "status": report["status"],
        "contract_version": report["contract_version"],
        "primary_variant": report["primary_variant"],
        "primary_passing_directions": report["primary_passing_directions"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
