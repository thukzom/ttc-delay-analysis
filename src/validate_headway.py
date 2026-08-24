"""
Validate the headway estimator against known truth.

The whole wait-time model rests on one inference: that a route's scheduled
headway can be recovered from its own delay records as the median of
Min Gap - Min Delay. That inference is load-bearing and unverifiable on real
data, because the delay dataset does not publish schedules.

It IS verifiable on generated data, where the true headway is known. This module
rebuilds the expected headway for every route and time band directly from the
generator's own service rules, weighted by the actual mix of weekdays and
weekends the estimator saw, and compares.

The comparison is deliberately strict. An earlier, lazier version compared the
midday estimate against each route's weekday base headway and reported a small
positive bias; the bias was not in the estimator, it was in the test, which had
ignored that the midday band contains thinner weekend service. Measuring against
the correctly weighted expectation removes it.

Usage:  python -m src.validate_headway
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
import pandas as pd

from src.config import (
    DATA_DIR,
    MIN_INCIDENTS_FOR_HEADWAY,
    TIME_BANDS,
    WAREHOUSE_DB,
)
from src.sample_data import _headway_for

TRUTH_CSV = DATA_DIR / "sample_truth.csv"


def band_for(hour: int) -> str:
    for name, start, end in TIME_BANDS:
        if start <= hour < end:
            return name
    return "unknown"


WEEKDAY_INDEX = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


def expected_headways(observed: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the true headway per route and band from the generator's rules.

    Critically, each (hour, weekday) slot is weighted by the number of incidents
    the estimator actually SAW in it, not by how often that slot occurs in the
    calendar. The estimator takes a median over observations, and observations
    are concentrated where incidents happen - heavily in the peaks, sparsely
    overnight. Weighting the truth by calendar time instead compares the
    estimate against a mixture it was never drawn from, and manufactures an
    error that belongs to the test rather than the model.
    """
    truth = pd.read_csv(TRUTH_CSV, dtype={"route_number": str})
    base_by_route = dict(
        zip(truth.route_number, truth.true_base_headway_min)
    )

    weighted: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in observed.itertuples():
        base = base_by_route.get(row.route_number)
        if base is None or row.hour is None:
            continue
        weekday = WEEKDAY_INDEX.get(row.day_name)
        if weekday is None:
            continue
        headway = _headway_for(base, int(row.hour), weekday)
        weighted[(row.route_number, band_for(int(row.hour)))].append(
            (headway, float(row.n))
        )

    rows = []
    for (route_number, band), pairs in weighted.items():
        pairs.sort()
        total = sum(w for _, w in pairs)
        running = 0.0
        median = pairs[-1][0]
        for value, weight in pairs:
            running += weight
            if running >= total / 2:
                median = value
                break
        rows.append({
            "route_number": route_number,
            "time_band": band,
            "true_headway_min": round(median, 2),
            "true_base_headway_min": base_by_route[route_number],
        })
    return pd.DataFrame(rows)


def main() -> int:
    if not TRUTH_CSV.exists():
        print(
            "No ground truth available.\n"
            "This check only runs against generated data, where the true "
            "headway is known.\n"
            "Run `make sample` first, or skip it when building on real data."
        )
        return 0

    conn = sqlite3.connect(WAREHOUSE_DB)
    estimated = pd.read_sql(
        "SELECT route_number, time_band, headway_min, n_observations, "
        "headway_source FROM int_route_headway",
        conn,
    )
    # The exact mixture of hours and weekdays each estimate was drawn from.
    observed = pd.read_sql(
        "SELECT route_number, hour, day_name, COUNT(*) AS n "
        "FROM stg_incidents "
        "WHERE is_analysable = 1 AND implied_headway_min IS NOT NULL "
        "GROUP BY route_number, hour, day_name",
        conn,
    )
    conn.close()

    truth = expected_headways(observed)
    merged = estimated.merge(truth, on=["route_number", "time_band"], how="inner")
    merged["error_min"] = merged.headway_min - merged.true_headway_min
    merged["abs_error_min"] = merged.error_min.abs()
    merged["abs_error_pct"] = (
        merged.abs_error_min / merged.true_headway_min * 100
    )

    print("=" * 76)
    print("HEADWAY ESTIMATOR - VALIDATION AGAINST KNOWN TRUTH")
    print("=" * 76)
    print(
        "\nEstimator: median(Min Gap - Min Delay) per route and time band, from\n"
        "the delay records alone. No schedule data is used as an input.\n"
    )

    graded = merged[merged.headway_source != "default_assumed"]
    print(f"  {len(merged)} route-band estimates, of which {len(graded)} are "
          f"derived from data\n  and {len(merged) - len(graded)} fell back to "
          "the assumed default (excluded from accuracy below).\n")

    print("  ACCURACY (derived estimates only)")
    print(f"    median absolute error   {graded.abs_error_min.median():6.2f} min "
          f"({graded.abs_error_pct.median():.1f}%)")
    print(f"    mean absolute error     {graded.abs_error_min.mean():6.2f} min")
    print(f"    90th percentile error   {graded.abs_error_min.quantile(0.9):6.2f} min")
    print(f"    worst error             {graded.abs_error_min.max():6.2f} min")
    print(f"    median signed error     {graded.error_min.median():+6.2f} min  "
          "(bias: should sit near zero)")
    for tolerance in (0.5, 1.0, 2.0):
        share = (graded.abs_error_min <= tolerance).mean()
        print(f"    within {tolerance:>4.1f} min          {share:6.1%}")

    print("\n  BY TIME BAND")
    print(f"    {'band':<10}{'n':>5}{'med err':>10}{'p90 err':>10}{'med true':>10}")
    for band, group in graded.groupby("time_band"):
        print(f"    {band:<10}{len(group):>5}{group.abs_error_min.median():>10.2f}"
              f"{group.abs_error_min.quantile(0.9):>10.2f}"
              f"{group.true_headway_min.median():>10.1f}")

    worst = graded.nlargest(5, "abs_error_min")
    print("\n  WORST FIVE ESTIMATES")
    print(worst[[
        "route_number", "time_band", "true_headway_min", "headway_min",
        "error_min", "n_observations",
    ]].to_string(index=False))

    thin = merged[merged.headway_source == "default_assumed"]
    if len(thin):
        print(f"\n  {len(thin)} route-bands fell back to the assumed default "
              f"(fewer than {MIN_INCIDENTS_FOR_HEADWAY} usable observations,\n"
              "  or an implausible median). These are flagged in the marts as "
              "'assumed' and the\n  site marks affected routes as lower "
              "confidence.")

    ok = graded.abs_error_min.median() <= 1.0
    print("\n  RESULT: " + (
        "the estimator recovers headway to within a minute. Safe to use."
        if ok else
        "accuracy is worse than one minute - the wait-time model should not "
        "be trusted without revisiting the estimator."
    ))

    out = DATA_DIR / "headway_validation.json"
    out.write_text(json.dumps({
        "route_bands_total": int(len(merged)),
        "route_bands_derived": int(len(graded)),
        "median_abs_error_min": round(float(graded.abs_error_min.median()), 3),
        "mean_abs_error_min": round(float(graded.abs_error_min.mean()), 3),
        "p90_abs_error_min": round(float(graded.abs_error_min.quantile(0.9)), 3),
        "median_signed_error_min": round(float(graded.error_min.median()), 3),
        "within_1_min": round(float((graded.abs_error_min <= 1.0).mean()), 4),
        "within_2_min": round(float((graded.abs_error_min <= 2.0).mean()), 4),
        "passes": bool(ok),
    }, indent=2))
    print(f"  Written to {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
