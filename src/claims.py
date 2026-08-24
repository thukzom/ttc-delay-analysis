"""
Turn mart numbers into sentences that stay true whatever the data says.

Every claim on the site is generated here rather than typed into the page. That
matters because the site rebuilds itself each month against whatever the City
has published. A sentence like "winter is worse" hard-coded into a template is
true until the year it isn't, and then the page is confidently wrong with no
warning.

So each function below inspects the figure first and picks the wording to match,
including the wording for "this effect isn't there". If a pattern disappears
from the data, the site says so.
"""

from __future__ import annotations


def _pct(value: float, places: int = 0) -> str:
    return f"{value:.{places}f}%"


def winter(kpi) -> tuple[str, str]:
    """Seasonal effect, in whichever direction it actually runs."""
    uplift = float(kpi.winter_uplift_pct or 0)
    winter_day = float(kpi.winter_impact_per_day or 0)
    other_day = float(kpi.other_impact_per_day or 0)

    if uplift >= 8:
        return (
            f"Winter costs riders {_pct(uplift)} more waiting per day",
            f"December through February averages {winter_day:,.0f} on the impact "
            f"index per day against {other_day:,.0f} across the rest of the year. "
            "The cold stop and the late bus turn out to be the same problem, "
            "which is roughly what I expected to find and the reason I started "
            "here.",
        )
    if uplift <= -8:
        return (
            f"Winter is actually {_pct(abs(uplift))} better than the rest of the year",
            f"December through February averages {winter_day:,.0f} on the impact "
            f"index per day against {other_day:,.0f} the rest of the year. That is "
            "the opposite of what I expected. Winter service is often run to a "
            "reduced schedule, and a thinner timetable produces fewer logged "
            "incidents even when the service riders get is worse.",
        )
    return (
        "Winter is not meaningfully worse than the rest of the year",
        f"December through February averages {winter_day:,.0f} on the impact index "
        f"per day against {other_day:,.0f} the rest of the year, a difference of "
        f"{uplift:+.1f}%. I expected a clear winter penalty and the data does not "
        "show one at this level. It may still be there inside particular routes "
        "or particular causes.",
    )


def ranking(kpi) -> tuple[str, str] | None:
    """How far the impact ranking departs from a plain incident count."""
    moving = int(kpi.routes_moving_5plus or 0)
    largest = int(kpi.largest_rank_shift or 0)
    total = int(kpi.n_routes or 0)

    if moving == 0 and largest < 5:
        return (
            "Counting incidents and measuring waiting give the same answer here",
            f"Across {total} routes, none moves more than five places when ranked "
            f"by rider impact instead of incident count, and the largest shift is "
            f"{largest}. On this dataset the simpler measure would have been good "
            "enough. I still prefer the impact measure because it is the one that "
            "corresponds to something a person experiences, but I am not going to "
            "claim it changed the answer when it didn't.",
        )
    return (
        "Counting incidents points at different routes than measuring waiting",
        f"{moving} of {total} routes move more than five places when I rank by "
        f"rider impact instead of by how many incidents they log, and the largest "
        f"single shift is {largest} places. A route with many brief incidents can "
        "be almost unnoticeable to a rider; a route with fewer, longer gaps is the "
        "one people remember. That gap between the two rankings is the whole "
        "reason I built the impact measure.",
    )


def tractability(kpi) -> tuple[str, str]:
    addressable = float(kpi.addressable_impact_pct or 0)
    irreducible = float(kpi.irreducible_impact_pct or 0)

    if addressable >= irreducible:
        return (
            f"About {_pct(addressable)} of the waiting comes from causes the TTC controls",
            f"Mechanical failures and operator or scheduling problems together "
            f"account for {_pct(addressable)} of rider impact, against "
            f"{_pct(irreducible)} from causes largely outside the agency's hands "
            "— weather, traffic, and onboard medical incidents. That first number "
            "is the part where spending money could actually move the result.",
        )
    return (
        f"Most of the waiting comes from causes the TTC does not control",
        f"Weather, traffic and onboard incidents account for {_pct(irreducible)} "
        f"of rider impact, against {_pct(addressable)} from mechanical and "
        "operator causes. That is an uncomfortable finding for anyone hoping for "
        "a simple fix, and it argues for building slack into the schedule rather "
        "than trying to eliminate the incidents themselves.",
    )


def top_cause(row) -> tuple[str, str]:
    gap = float(row.impact_vs_frequency_gap or 0)
    label = str(row.cause_category).replace("_", " ")

    if gap >= 2:
        detail = (
            f"It is {_pct(float(row.pct_of_incidents))} of logged incidents but "
            f"{_pct(float(row.pct_of_rider_impact))} of rider impact "
            f"({gap:+.1f} points), because its incidents run to an average gap of "
            f"{float(row.avg_gap_min):.0f} minutes."
        )
    elif gap <= -2:
        detail = (
            f"It is {_pct(float(row.pct_of_incidents))} of logged incidents and "
            f"only {_pct(float(row.pct_of_rider_impact))} of rider impact "
            f"({gap:+.1f} points) — it is logged constantly, but each occurrence "
            f"is mild, averaging {float(row.avg_gap_min):.0f} minutes."
        )
    else:
        detail = (
            f"It is {_pct(float(row.pct_of_incidents))} of logged incidents and "
            f"{_pct(float(row.pct_of_rider_impact))} of rider impact, so here "
            "frequency and severity line up."
        )
    return (
        f"{label.capitalize()} causes the largest share of the waiting",
        f"Responsibility sits with {row.accountable_for.lower()}. {detail}",
    )


def concentration(kpi, pareto) -> str:
    quarter = pareto[pareto.cumulative_pct_routes <= 25].cumulative_pct_impact.max()
    half = pareto[pareto.cumulative_pct_routes <= 50].cumulative_pct_impact.max()
    quarter = float(quarter) if quarter == quarter else 0.0
    half = float(half) if half == half else 0.0

    if quarter >= 45:
        shape = ("The problem is concentrated: a short list of routes would "
                 "cover most of it.")
    elif quarter >= 32:
        shape = ("The problem is moderately concentrated — worth prioritising, "
                 "but there is no handful of routes that explains everything.")
    else:
        shape = ("The problem is spread fairly evenly across the network, which "
                 "argues against a route-by-route fix.")
    return (
        f"The worst quarter of routes carry <b>{quarter:.0f}%</b> of all rider "
        f"impact; the worst half carry <b>{half:.0f}%</b>. {shape}"
    )


def worst_time_band(band_frame) -> str:
    """Which part of the day does the most damage per incident, and why."""
    usable = band_frame.dropna(subset=["avg_excess_wait_min"])
    if usable.empty:
        return ""
    worst = usable.loc[usable.avg_excess_wait_min.idxmax()]
    busiest = band_frame.loc[band_frame.incidents.idxmax()]
    worst_name = str(worst.band_label).split(" (")[0].lower()
    busy_name = str(busiest.band_label).split(" (")[0].lower()

    if str(worst.band_label) == str(busiest.band_label):
        return (
            f"The {worst_name} is both the busiest period for incidents and the "
            f"one that adds the most waiting per rider "
            f"({float(worst.avg_excess_wait_min):.1f} minutes), so here the two "
            "views agree."
        )
    return (
        f"The most incidents are logged in the {busy_name}, but the worst waiting "
        f"per rider happens in the {worst_name}: "
        f"{float(worst.avg_excess_wait_min):.1f} extra minutes against "
        f"{float(busiest.avg_excess_wait_min):.1f}. Service is thinner outside the "
        "peaks, so one missing bus leaves a much longer hole."
    )


def data_span(kpi, dq) -> str:
    generations = int(dq.schema_generations or 1)
    if generations > 1:
        schema_note = (
            f"{int(dq.rows_legacy_schema):,} rows came from the pre-2025 file "
            f"layout and {int(dq.rows_current_schema):,} from the current one"
        )
    else:
        schema_note = "all rows share one file layout"
    return (
        f"{int(kpi.incidents):,} delay records &middot; {int(kpi.routes)} routes "
        f"&middot; {kpi.first_date} to {kpi.last_date} &middot; "
        f"{int(kpi.days):,} days &middot; {schema_note}"
    )
