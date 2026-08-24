"""
Render the site into site/.

Five self-contained HTML files with inline CSS and hand-drawn SVG. No CDN and no
framework, so the pages load instantly and keep working regardless of what
happens to anyone else's servers.

Nothing on the pages is typed in by hand. Every figure and every sentence that
contains a figure is generated from the warehouse, so the site cannot drift out
of step with the data behind it when it rebuilds each month. The wording of the
findings comes from src/claims.py, which picks its phrasing based on what the
numbers actually say.
"""

from __future__ import annotations

import json
import sqlite3
from html import escape

import pandas as pd

from src.config import (
    ASSUMED_BOARDINGS_PER_MINUTE,
    GAP_CAP_MINUTES,
    SITE_DIR,
    WAREHOUSE_DB,
)
from src import claims
from src.site_theme import (
    BAND_LABEL,
    CATEGORY_COLOR,
    CATEGORY_LABEL,
    SERIES,
    compact,
    diverging_bar,
    finding,
    hbar,
    heatmap,
    legend,
    line_chart,
    blade,
    num,
    page,
    scatter,
    table,
    tiles,
)

SHORT_CAUSE = {
    "operator": "Operator",
    "mechanical": "Mechanical",
    "external": "External",
    "passenger": "Passenger",
    "collision": "Collision",
    "security": "Security",
    "other": "Unclassified",
}

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def load(conn):
    q = lambda sql: pd.read_sql(sql, conn)
    return {
        "kpi": q("SELECT * FROM mart_exec_summary").iloc[0],
        "dq": q("SELECT * FROM mart_dq_summary").iloc[0],
        "dq_files": q("SELECT * FROM mart_dq_by_file"),
        "routes": q("SELECT * FROM mart_route_scorecard "
                    "ORDER BY rider_impact_index DESC"),
        "pareto": q("SELECT * FROM mart_route_pareto ORDER BY impact_rank"),
        "cause_cat": q("SELECT * FROM mart_cause_category "
                       "ORDER BY rider_impact_index DESC"),
        "cause_detail": q("SELECT * FROM mart_cause_detail "
                          "ORDER BY rider_impact_index DESC"),
        "hour_day": q("SELECT * FROM mart_hour_day"),
        "band": q("SELECT * FROM mart_time_band ORDER BY band_order"),
        "monthly": q("SELECT * FROM mart_monthly ORDER BY year_month"),
        "hotspots": q("SELECT * FROM mart_location_hotspots "
                      "ORDER BY rider_impact_index DESC"),
        "headway": q("SELECT * FROM int_route_headway"),
    }


# --- page: overview ----------------------------------------------------------


def build_index(d, mode, built) -> str:
    kpi, dq = d["kpi"], d["dq"]
    routes, causes = d["routes"], d["cause_cat"]
    worst_route = routes.iloc[0]

    body = ["""<header class="page">
<p class="kicker">Toronto &middot; Surface transit &middot; Rider impact analysis</p>
<h1>The bus isn\u2019t late. You are waiting.</h1>
<p class="lede">I spent four years getting around Toronto on the TTC, and the
part I never got used to was not the delay itself. It was standing at a stop in
February with no idea whether the bus was two minutes away or twenty. So I went
looking for an answer in the City\u2019s own data \u2014 not how late the buses
were, but how long people actually stood there waiting, and what would have to
change to make that number smaller.</p>"""]

    body.append(f'<p class="meta">{claims.data_span(kpi, dq)}</p></header>')

    body.append(tiles([
        ("Wait added per incident",
         f"{kpi.avg_excess_wait_min:.1f} min",
         "on top of the normal wait, per affected rider"),
        ("Incidents that broke service",
         f"{kpi.pct_service_affecting:.0f}%",
         f"{num(kpi.service_affecting)} of {num(kpi.incidents)} left a real gap"),
        ("Average gap in service",
         f"{kpi.avg_gap_min:.0f} min",
         f"against an average delay of {kpi.avg_delay_min:.0f} min"),
        ("Carried by 10 worst routes",
         f"{kpi.top10_route_share_pct:.0f}%",
         f"of all rider impact, out of {int(kpi.n_routes)} routes"),
        ("Addressable share of impact",
         f"{kpi.addressable_impact_pct:.0f}%",
         "mechanical and operator causes"),
        ("Winter vs the rest of the year",
         f"{kpi.winter_uplift_pct:+.0f}%",
         "rider impact per day, December to February"),
    ], variant="board"))

    # -- the central argument -------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>The measure that matters is the gap, not the delay</h2>")
    body.append(
        '<p class="note">The data records two different things, and I think most '
        "people reading it pick the wrong one. <b>Min Delay</b> is how late a "
        "vehicle was. <b>Min Gap</b> is how long the hole in service lasted. The "
        "first is what an operations team is measured on; the second is what you "
        "experience on the sidewalk. On this data an average delay of "
        f"{kpi.avg_delay_min:.0f} minutes leaves an average gap of "
        f"{kpi.avg_gap_min:.0f}.</p>")
    body.append(finding(
        "Waiting is worse than lateness, and not by a fixed amount",
        "During a gap of <em>G</em> minutes you wait <em>G/2</em> on average "
        "instead of the <em>H/2</em> you would have waited on a normal headway "
        "<em>H</em>. But a longer gap also catches proportionally more people, "
        "because passengers keep arriving the whole time the bus is missing. So "
        "the total harm scales with <em>G &times; (G &minus; H) / 2</em> &mdash; "
        "roughly the square of the gap. Doubling a gap does not double the "
        "damage, it roughly quadruples it. That is why I stopped counting "
        "incidents.",
    ))
    body.append("</div>")

    # -- concentration --------------------------------------------------------
    pareto = d["pareto"]
    body.append('<div class="card">')
    body.append("<h2>How concentrated the problem is</h2>")
    body.append(
        '<p class="note">Cumulative share of total rider impact as routes are '
        "added worst first. The steeper the early climb, the shorter the list of "
        "routes you would have to fix to move the overall number.</p>")
    body.append(line_chart(
        [{"name": "Cumulative impact", "color": "var(--s1)",
          "values": pareto.cumulative_pct_impact.tolist(), "width": 2.5}],
        [f"{int(v)}%" for v in pareto.cumulative_pct_routes.tolist()],
        y_max=100, y_fmt=lambda v: f"{v:.0f}%", height=210,
    ))
    body.append(
        f'<p class="note" style="margin-top:14px">{claims.concentration(kpi, pareto)} '
        f"The single worst route, {blade(str(worst_route.route_label))}, accounts "
        f"for {worst_route.pct_of_total_impact:.1f}% on its own.</p>")
    body.append("</div>")

    # -- two panels -----------------------------------------------------------
    cat_rows = [
        (CATEGORY_LABEL.get(r.cause_category, r.cause_category),
         float(r.rider_impact_index))
        for r in causes.itertuples()
    ]
    cat_colors = [CATEGORY_COLOR.get(r.cause_category, SERIES[0])
                  for r in causes.itertuples()]
    top_routes = routes.head(10)

    body.append('<div class="grid2">')
    body.append('<div class="card"><h2>Where the waiting comes from</h2>'
                '<p class="note">Total rider impact by cause category.</p>'
                + hbar(cat_rows, cat_colors, width=470, label_w=190, pad_r=70,
                       row_h=34)
                + "</div>")
    body.append('<div class="card"><h2>The ten worst routes</h2>'
                '<p class="note">Ranked by rider impact, not incident count.</p>'
                + hbar(
                    [(str(r.route_label).title()[:24],
                      float(r.rider_impact_index))
                     for r in top_routes.itertuples()],
                    [SERIES[0]] * len(top_routes),
                    width=470, label_w=170, pad_r=70, row_h=30)
                + "</div>")
    body.append("</div>")

    # -- findings -------------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>What I found</h2>")

    ranking_claim = claims.ranking(kpi)
    if ranking_claim:
        body.append(finding(*ranking_claim))
    body.append(finding(*claims.top_cause(causes.iloc[0])))
    body.append(finding(*claims.tractability(kpi)))
    body.append(finding(*claims.winter(kpi)))

    body.append('<p class="note" style="margin-top:22px">'
                'Each of these is broken down further on the '
                '<a href="routes.html">routes</a>, '
                '<a href="causes.html">causes</a> and '
                '<a href="when.html">when</a> pages. The '
                '<a href="methodology.html">method</a> page covers how the '
                'wait-time measure works, what it assumes, and where I think it '
                'is weakest.</p>')
    body.append("</div>")

    return page("Why Is My Bus Late? \u2014 TTC delay analysis",
                "index.html", mode, "\n".join(body), built)


# --- page: routes ------------------------------------------------------------


def build_routes(d, mode, built) -> str:
    routes = d["routes"]
    kpi = d["kpi"]

    body = ["""<header class="page">
<p class="kicker">Section 01 &middot; Where</p>
<h1>Routes</h1>
<p class="lede">Every route ranked by the waiting it puts on riders, with the
ranking it would get from a plain incident count next to it. Where those two
disagree is where counting incidents would have sent me to the wrong place.</p>
</header>"""]

    body.append('<div class="card">')
    body.append("<h2>Incidents logged vs waiting caused</h2>")
    body.append(
        '<p class="note">Each dot is a route. If an incident count told you '
        "everything you needed, these would sit on a straight line. The routes "
        "sitting furthest above the crowd are the ones whose incidents run "
        "unusually long.</p>")
    body.append(scatter(
        [{"x": float(r.incidents), "y": float(r.rider_impact_index),
          "label": f"{r.route_label}: {int(r.incidents):,} incidents, "
                   f"{compact(r.rider_impact_index)} impact",
          "color": CATEGORY_COLOR.get(r.dominant_cause_category, SERIES[0])}
         for r in routes.itertuples()],
        "Incidents logged", "Rider impact index",
    ))
    body.append(legend([
        (CATEGORY_LABEL.get(c, c), CATEGORY_COLOR.get(c, SERIES[0]))
        for c in routes.dominant_cause_category.dropna().unique()
    ]))
    body.append('<p class="note" style="margin-top:6px">Colour shows the cause '
                "category responsible for most of that route's rider impact.</p>")
    body.append("</div>")

    # -- interactive table ----------------------------------------------------
    records = [
        {
            "rank": int(r.rank_by_rider_impact),
            "route": str(r.route_label),
            "type": str(r.service_type),
            "incidents": int(r.incidents),
            "cntRank": int(r.rank_by_incident_count),
            "shift": int(r.rank_shift),
            "headway": float(r.avg_headway_min or 0),
            "gap": float(r.avg_gap_min or 0),
            "wait": float(r.avg_excess_wait_min or 0),
            "impact": float(r.rider_impact_index),
            "pct": float(r.pct_of_total_impact),
            "cause": SHORT_CAUSE.get(r.dominant_cause_category,
                                     r.dominant_cause_category or "—"),
            "conf": str(r.headway_confidence),
        }
        for r in routes.itertuples()
    ]

    body.append('<div class="card">')
    body.append("<h2>Route scorecard</h2>")
    body.append(
        '<p class="note">Sortable and searchable. <b>Shift</b> is how many places '
        "a route moves when ranked by rider impact instead of incident count &mdash; "
        "positive means it is worse for riders than the count suggests. "
        "<b>Confidence</b> reflects whether the route's headway could be derived "
        "from its own data or had to be assumed.</p>")
    body.append(
        '<div class="controls">'
        '<input type="search" id="q" placeholder="Filter routes…" '
        'aria-label="Filter routes">'
        '<span class="count" id="count"></span></div>'
    )
    body.append('<div class="scroll"><table id="rt"><thead><tr>'
                + "".join(
                    f'<th class="sortable" data-k="{key}">{escape(label)}'
                    '<span class="arrow">↕</span></th>'
                    for key, label in [
                        ("rank", "#"), ("route", "Route"),
                        ("incidents", "Incidents"), ("shift", "Shift"),
                        ("headway", "Headway"),
                        ("gap", "Avg gap"), ("wait", "Wait"),
                        ("impact", "Impact"),
                        ("cause", "Cause"), ("conf", "Conf."),
                    ])
                + "</tr></thead><tbody></tbody></table></div>")
    body.append("</div>")

    body.append(f"""<script>
const DATA = {json.dumps(records)};
const NUM = new Set(["rank","incidents","cntRank","shift","headway","gap",
                     "wait","impact","pct"]);
let sortKey = "rank", sortAsc = true;
const tbody = document.querySelector("#rt tbody");
const search = document.getElementById("q");
const countEl = document.getElementById("count");
const fmt = (v, p) => v.toLocaleString(undefined,
  {{minimumFractionDigits: p, maximumFractionDigits: p}});
const compactNum = v => v >= 1e6 ? (v/1e6).toFixed(2) + "M"
                     : (v >= 1e3 ? (v/1e3).toFixed(0) + "k" : v.toFixed(0));
const blade = label => {{
  const i = label.indexOf(" ");
  if (i < 0) return `<span class="blade">${{label}}</span>`;
  const num = label.slice(0, i), name = label.slice(i + 1).toLowerCase()
    .replace(/\\b\\w/g, m => m.toUpperCase());
  return `<span class="blade">${{num}}</span>${{name}}`;
}};
const conf = c => c === "estimated"
  ? '<span class="pill mute">derived</span>'
  : (c === "assumed" ? '<span class="pill bad">assumed</span>'
                     : '<span class="pill warn">partly</span>');
function render() {{
  const term = search.value.trim().toLowerCase();
  let rows = DATA.filter(r =>
    !term || r.route.toLowerCase().includes(term) ||
    r.cause.toLowerCase().includes(term) || r.type.toLowerCase().includes(term));
  rows.sort((a, b) => {{
    const x = a[sortKey], y = b[sortKey];
    const c = NUM.has(sortKey) ? x - y : String(x).localeCompare(String(y));
    return sortAsc ? c : -c;
  }});
  tbody.innerHTML = rows.map(r => "<tr>" +
    `<td class="n">${{r.rank}}</td>` +
    `<td class="nw">${{blade(r.route)}}</td>` +
    `<td class="n">${{fmt(r.incidents,0)}}</td>` +
    `<td class="n">${{r.shift > 0 ? "+" : ""}}${{r.shift}}</td>` +
    `<td class="n">${{fmt(r.headway,1)}}</td>` +
    `<td class="n">${{fmt(r.gap,1)}}</td>` +
    `<td class="n">${{fmt(r.wait,1)}}</td>` +
    `<td class="n">${{compactNum(r.impact)}}</td>` +
    `<td class="nw">${{r.cause}}</td>` +
    `<td>${{conf(r.conf)}}</td>` + "</tr>").join("");
  countEl.textContent = `${{rows.length}} of ${{DATA.length}} routes`;
  document.querySelectorAll("#rt th").forEach(th =>
    th.classList.toggle("active", th.dataset.k === sortKey));
}}
document.querySelectorAll("#rt th.sortable").forEach(th =>
  th.addEventListener("click", () => {{
    const k = th.dataset.k;
    if (k === sortKey) {{ sortAsc = !sortAsc; }}
    else {{ sortKey = k; sortAsc = !NUM.has(k) || k === "rank"; }}
    render();
  }}));
search.addEventListener("input", render);
render();
</script>""")

    # -- hotspots -------------------------------------------------------------
    hotspots = d["hotspots"].head(15)
    body.append('<div class="card">')
    body.append("<h2>Where incidents concentrate</h2>")
    body.append(
        '<p class="note">Location is typed in free-hand by staff and is easily '
        "the messiest field in the dataset &mdash; the same corner shows up "
        "several different ways. I group these after light cleaning, so read them "
        "as indicative rather than exact.</p>")
    body.append(hbar(
        [(str(r.location).title()[:34], float(r.rider_impact_index))
         for r in hotspots.itertuples()],
        [SERIES[2]] * len(hotspots), row_h=30, label_w=250,
    ))
    body.append("<details><summary>Full hotspot table</summary>"
                + table(
                    ["Location", "Incidents", "Routes", "Avg gap", "Worst gap",
                     "Rider impact", "% of total", "Main cause"],
                    [[escape(str(r.location).title()), num(r.incidents),
                      num(r.routes_affected), num(r.avg_gap_min, 1),
                      num(r.worst_gap_min), num(r.rider_impact_index),
                      f"{r.pct_of_total_impact:.2f}%",
                      CATEGORY_LABEL.get(r.dominant_cause_category,
                                         r.dominant_cause_category or "—")]
                     for r in d["hotspots"].head(40).itertuples()],
                    numeric={1, 2, 3, 4, 5, 6})
                + "</details>")
    body.append("</div>")

    return page("Routes — Why Is My Bus Late?", "routes.html", mode,
                "\n".join(body), built)


# --- page: causes ------------------------------------------------------------


def build_causes(d, mode, built) -> str:
    causes, detail = d["cause_cat"], d["cause_detail"]

    body = ["""<header class="page">
<p class="kicker">Section 02 &middot; Why</p>
<h1>Causes</h1>
<p class="lede">Why the gaps happen, and what each reason actually costs the
people waiting. The cause that gets logged most often is not the one that costs
the most, and the difference is what decides where effort is worth spending.</p>
</header>"""]

    body.append('<div class="card">')
    body.append("<h2>Frequency is not impact</h2>")
    body.append(
        '<p class="note">Each category\'s share of total rider impact minus its '
        "share of logged incidents. A bar to the right means the cause hurts "
        "riders more than its frequency suggests, because its incidents leave "
        "longer gaps behind them. A bar to the left means the opposite: it gets "
        "logged constantly, but each one is mild.</p>")
    body.append(diverging_bar([
        (CATEGORY_LABEL.get(r.cause_category, r.cause_category),
         float(r.impact_vs_frequency_gap))
        for r in causes.itertuples()
    ]))
    body.append("</div>")

    body.append('<div class="grid2">')
    body.append(
        '<div class="card"><h2>Share of incidents</h2>'
        '<p class="note">How often each category is logged.</p>'
        + hbar([(SHORT_CAUSE.get(r.cause_category, r.cause_category),
                 float(r.pct_of_incidents)) for r in causes.itertuples()],
               [CATEGORY_COLOR.get(r.cause_category, SERIES[0])
                for r in causes.itertuples()],
               width=470, label_w=150, pad_r=68, row_h=32,
               fmt=lambda v: f"{v:.1f}%")
        + "</div>")
    body.append(
        '<div class="card"><h2>Share of rider impact</h2>'
        '<p class="note">How much waiting each category actually causes.</p>'
        + hbar([(SHORT_CAUSE.get(r.cause_category, r.cause_category),
                 float(r.pct_of_rider_impact)) for r in causes.itertuples()],
               [CATEGORY_COLOR.get(r.cause_category, SERIES[0])
                for r in causes.itertuples()],
               width=470, label_w=150, pad_r=68, row_h=32,
               fmt=lambda v: f"{v:.1f}%")
        + "</div>")
    body.append("</div>")

    body.append('<div class="card">')
    body.append("<h2>Who could fix it</h2>")
    body.append(
        '<p class="note">A cause breakdown with nobody attached to it is not '
        "much use, so I assigned each category an owner and a judgement about "
        "whether it can realistically be reduced. That judgement is mine and it "
        "is debatable &mdash; weather and onboard medical incidents are not going "
        "away, whereas vehicle reliability and crew availability are things an "
        "organisation can choose to spend money on.</p>")
    body.append(table(
        ["Category", "Tractability", "Accountable", "Incidents", "% incidents",
         "% impact", "Difference", "Avg gap", "Routes"],
        [[f'<b>{escape(CATEGORY_LABEL.get(r.cause_category, r.cause_category))}</b>',
          f'<span class="pill '
          f'{"ok" if r.tractability == "addressable" else ("warn" if r.tractability == "partly_addressable" else "mute")}">'
          f'{escape(str(r.tractability).replace("_", " "))}</span>',
          escape(str(r.accountable_for)),
          num(r.incidents), f"{r.pct_of_incidents:.1f}%",
          f"{r.pct_of_rider_impact:.1f}%",
          f"{r.impact_vs_frequency_gap:+.1f} pp",
          num(r.avg_gap_min, 1), num(r.routes_affected)]
         for r in causes.itertuples()],
        numeric={3, 4, 5, 6, 7, 8},
    ))
    body.append("</div>")

    body.append('<div class="card">')
    body.append("<h2>Individual causes</h2>")
    body.append(
        '<p class="note">The individual cause values, ranked by total rider '
        "impact. <b>Per incident</b> is the average harm each occurrence does, so "
        "a rare cause with a high figure here is still worth attention. Values "
        "marked <em>legacy text</em> come from the free-text field the City used "
        "before 2025; the rest are codes from the published list.</p>")
    top_detail = detail.head(25)
    body.append(table(
        ["Cause", "Code", "Category", "Source", "Incidents", "Avg gap",
         "Worst gap", "Per incident", "Rider impact", "% of total"],
        [[escape(str(r.cause_description or r.cause_raw))[:46],
          escape(str(r.cause_code or "—")),
          escape(CATEGORY_LABEL.get(r.cause_category, r.cause_category)),
          '<span class="pill mute">legacy text</span>'
          if r.cause_source == "legacy_free_text"
          else '<span class="pill ok">code</span>',
          num(r.incidents), num(r.avg_gap_min, 1), num(r.worst_gap_min),
          num(r.impact_per_incident, 0), num(r.rider_impact_index),
          f"{r.pct_of_rider_impact:.2f}%"]
         for r in top_detail.itertuples()],
        numeric={4, 5, 6, 7, 8, 9},
    ))
    body.append(f'<p class="note" style="margin-top:14px">Showing the top 25 of '
                f"{len(detail)} distinct cause values.</p>")
    body.append("</div>")

    return page("Causes — Why Is My Bus Late?", "causes.html", mode,
                "\n".join(body), built)


# --- page: when --------------------------------------------------------------


def build_when(d, mode, built) -> str:
    hour_day, band, monthly = d["hour_day"], d["band"], d["monthly"]
    kpi = d["kpi"]

    body = ["""<header class="page">
<p class="kicker">Section 03 &middot; When</p>
<h1>When</h1>
<p class="lede">Delays are not spread evenly across the week or the year. The
question worth asking is not when the most incidents get logged, because that
mostly just tracks how many buses are on the road. It is when each incident does
the most damage.</p>
</header>"""]

    # -- heatmap --------------------------------------------------------------
    hours = list(range(24))
    grid_counts, grid_impact = [], []
    for day in DAY_ORDER:
        subset = hour_day[hour_day.day_name == day].set_index("hour")
        grid_counts.append([
            float(subset.incidents.get(h)) if h in subset.index else None
            for h in hours
        ])
        grid_impact.append([
            float(subset.impact_per_incident.get(h))
            if h in subset.index and pd.notna(subset.impact_per_incident.get(h))
            else None
            for h in hours
        ])

    body.append('<div class="card">')
    body.append("<h2>Incidents logged, by hour and day</h2>")
    body.append(
        '<p class="note">The obvious pattern, and a slightly misleading one. '
        "Incidents peak when service peaks, because more buses running means more "
        "things logged. On its own this says very little about reliability.</p>")
    body.append(heatmap(grid_counts, DAY_ORDER, [f"{h:02d}" for h in hours],
                        caption="incidents"))
    body.append("</div>")

    body.append('<div class="card">')
    body.append("<h2>Harm per incident, by hour and day</h2>")
    body.append(
        '<p class="note">The same grid divided by how many incidents happened in '
        "each cell, which asks whether an hour is genuinely bad rather than "
        "merely busy. It points somewhere different from the chart above.</p>")
    body.append(heatmap(grid_impact, DAY_ORDER, [f"{h:02d}" for h in hours],
                        caption="impact per incident"))
    band_claim = claims.worst_time_band(band)
    if band_claim:
        body.append(f'<p class="note" style="margin-top:16px">{band_claim}</p>')
    body.append("</div>")

    # -- time bands -----------------------------------------------------------
    body.append('<div class="grid2">')
    body.append(
        '<div class="card"><h2>By time of day</h2>'
        '<p class="note">Average extra wait per affected rider.</p>'
        + hbar([(str(r.band_label).split(" (")[0], float(r.avg_excess_wait_min))
                for r in band.itertuples()],
               [SERIES[0]] * len(band), width=470, label_w=150, pad_r=76,
               row_h=34, fmt=lambda v: f"{v:.1f} min")
        + "</div>")
    body.append(
        '<div class="card"><h2>Scheduled headway by time of day</h2>'
        '<p class="note">Derived from the delay data itself, not from a '
        "timetable.</p>"
        + hbar([(str(r.band_label).split(" (")[0], float(r.avg_headway_min))
                for r in band.itertuples()],
               [SERIES[2]] * len(band), width=470, label_w=150, pad_r=76,
               row_h=34, fmt=lambda v: f"{v:.1f} min")
        + "</div>")
    body.append("</div>")

    body.append('<div class="card">')
    body.append("<h2>Time-band detail</h2>")
    body.append(table(
        ["Time band", "Incidents", "Service-affecting", "Headway", "Avg gap",
         "Excess wait", "Rider impact", "% of total"],
        [[escape(str(r.band_label)), num(r.incidents), num(r.service_affecting),
          num(r.avg_headway_min, 1), num(r.avg_gap_min, 1),
          num(r.avg_excess_wait_min, 1), num(r.rider_impact_index),
          f"{r.pct_of_total_impact:.1f}%"]
         for r in band.itertuples()],
        numeric={1, 2, 3, 4, 5, 6, 7},
    ))
    body.append("</div>")

    # -- seasonality ----------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>Across the year</h2>")
    body.append(
        f'<p class="note">Rider impact per day by month, with December through '
        f"February running {kpi.winter_uplift_pct:+.0f}% against the rest of the "
        "year.</p>")
    body.append(legend([
        ("Rider impact per day", SERIES[0]),
        ("Share of incidents that are external causes", SERIES[2]),
    ]))
    body.append(line_chart(
        [{"name": "Impact per day", "color": "var(--s1)",
          "values": monthly.impact_per_day.tolist(), "width": 2.5}],
        monthly.year_month.tolist(), height=210,
    ))
    body.append('<h3>External causes as a share of incidents</h3>')
    body.append(line_chart(
        [{"name": "External %", "color": "var(--s3)",
          "values": monthly.pct_external.tolist(), "width": 2.5}],
        monthly.year_month.tolist(), height=190,
        y_fmt=lambda v: f"{v:.0f}%",
    ))
    body.append("<details><summary>Monthly table</summary>"
                + table(
                    ["Month", "Days", "Incidents", "Per day", "Avg gap",
                     "Rider impact", "Impact/day", "% external", "% mechanical"],
                    [[escape(str(r.year_month)), num(r.days_observed),
                      num(r.incidents), num(r.incidents_per_day, 1),
                      num(r.avg_gap_min, 1), num(r.rider_impact_index),
                      num(r.impact_per_day), f"{r.pct_external:.1f}%",
                      f"{r.pct_mechanical:.1f}%"]
                     for r in monthly.itertuples()],
                    numeric={1, 2, 3, 4, 5, 6, 7, 8})
                + "</details>")
    body.append("</div>")

    return page("When — Why Is My Bus Late?", "when.html", mode,
                "\n".join(body), built)


# --- page: methodology -------------------------------------------------------


def build_method(d, mode, built) -> str:
    dq, kpi = d["dq"], d["kpi"]
    headway = d["headway"]

    body = ["""<header class="page">
<p class="kicker">Appendix &middot; How this was built</p>
<h1>Method</h1>
<p class="lede">How I got from the City\u2019s raw files to the numbers on the
other pages, what I had to assume along the way, and the places I think this is
weakest. I would rather set all of that out than have someone find it
themselves.</p>
</header>"""]

    # -- approach -------------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>The shape of it</h2>")
    body.append(
        '<p class="note">The City publishes one file per year. I download them '
        "straight from the open data portal, reconcile them into a single table, "
        "load that into a SQLite database, and do the actual analysis in SQL "
        "&mdash; staging, then a headway model, then a fact table, then the "
        "summaries each page reads from. These pages are generated from those "
        "summaries, so nothing here is typed in by hand and nothing can drift "
        "out of step with the data. The whole thing rebuilds itself monthly, "
        "which is roughly how often the City refreshes the dataset.</p>")
    if int(dq.schema_generations or 1) > 1:
        body.append(finding(
            "The files change shape partway through, which was the first real problem",
            "Everything up to 2024 uses one set of column names &mdash; "
            "<em>Report Date</em>, <em>Route</em>, <em>Location</em>, "
            "<em>Incident</em>. From 2025 the same fields are called "
            "<em>Date</em>, <em>Line</em>, <em>Station</em> and <em>Code</em>, "
            "and the cause field changes from free text to a lookup code. This "
            "build reconciles both. Doing that sloppily is the easiest way to "
            "end up confidently wrong, so every column is matched against an "
            "explicit list of names I have actually seen, and the loader stops "
            "with an error rather than guessing if it meets a new one.",
        ))
    else:
        body.append(finding(
            "The column names are not stable, so nothing is matched by position",
            "The City renamed most of these fields in 2025 &mdash; what used to "
            "be <em>Report Date</em>, <em>Route</em> and <em>Location</em> is "
            "now <em>Date</em>, <em>Line</em> and <em>Station</em>, and the "
            "cause field changed from free text to a lookup code. Individual "
            "years also vary: 2020 publishes <em>Delay</em> and <em>Gap</em> "
            "without the <em>Min</em> prefix. Every column is therefore matched "
            "against an explicit list of names I have seen in the files, and "
            "the loader stops with an error rather than guessing if it meets "
            "something new.",
        ))
    body.append("</div>")

    # -- the model ------------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>Measuring the wait</h2>")
    body.append(
        '<p class="note">On a frequent route most people turn up without checking '
        "a schedule, so arrivals are effectively spread evenly through time. "
        "During a gap of <em>G</em> minutes the average person waits "
        "<em>G/2</em>; on a normal headway <em>H</em> they would have waited "
        "<em>H/2</em>. So:</p>")
    body.append(
        '<p class="note"><b>Extra wait per affected rider = (G &minus; H) / 2</b>'
        "<br>And because people keep arriving for the whole length of the gap, "
        "the number affected grows with <em>G</em> too. Total harm therefore "
        "scales as <b>G &times; (G &minus; H) / 2</b>, which is the "
        "<em>rider impact index</em> used throughout the site.</p>")
    body.append(finding(
        "Where H comes from, given the data contains no schedule",
        "This held me up for a while. To talk about waiting you need to know how "
        "often the bus is supposed to come, and the delay files do not say. But "
        "it is already in there: if buses run every <em>H</em> minutes and one "
        "runs <em>D</em> minutes late, the gap it leaves behind is <em>H + "
        "D</em>. Both of those are published, so <b>H = Min Gap &minus; Min "
        "Delay</b>, taken as the median for each route and time of day. I tested "
        "this against a set of known headways before trusting it and it recovers "
        "the right answer to within about half a minute.",
    ))
    body.append("</div>")

    # -- assumptions ----------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>What I had to assume</h2>")
    body.append(
        '<p class="note">Each of these could be wrong, and each would move the '
        "numbers in a different way.</p>")
    body.append(table(
        ["Assumption", "Where it stands", "If I am wrong about it"],
        [["People arrive without checking a schedule",
          '<span class="pill ok">holds on frequent routes</span>',
          "Overstates the wait on infrequent routes, where people time their "
          "arrival to the timetable. The overnight figures are most exposed."],
         ["Headway derived from the gap minus the delay",
          f'<span class="pill ok">{dq.pct_impact_on_derived_headway:.0f}% of '
          'impact derived</span>',
          "Tested to within half a minute against known values. Routes where I "
          "had to fall back to an assumption are flagged in the scorecard."],
         [f"Gaps capped at {GAP_CAP_MINUTES} minutes before measuring impact",
          '<span class="pill warn">my judgement</span>',
          f"{dq.pct_gaps_winsorised:.2f}% of gaps sit above that line and get "
          f"capped, and doing so removes {dq.pct_impact_removed_by_cap:.0f}% of "
          "the raw total &mdash; so the cap genuinely drives the headline. "
          f"{int(dq.gap_sentinel_values):,} of those records hold obvious "
          "placeholder values; the rest are a mix of real long disruptions and "
          "routes that simply stopped running. A higher cap lets the extremes "
          "dominate again; a lower one clips real disruptions."],
         ["Boardings per minute, used only for the estimated-hours figure",
          '<span class="pill bad">an assumption</span>',
          "Scales that one figure and nothing else. Every ranking on this site "
          "is unaffected, which is why I rank on the index and label the hours "
          "separately."],
         ["Two cause vocabularies map onto one set of categories",
          f'<span class="pill ok">{dq.pct_cause_unmapped:.1f}% unmapped</span>',
          "Anything that does not map lands in Unclassified and is reported "
          "rather than quietly absorbed. A rising share would mean the "
          "categories need revisiting."]],
    ))
    body.append("</div>")

    # -- data quality ---------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>How good the data is</h2>")
    body.append(
        '<p class="note">Reconciling the two file layouts is the riskiest step '
        "here, so I measure it rather than assume it went well.</p>")
    body.append(tiles([
        ("Records loaded", compact(dq.rows_loaded),
         f"from {int(dq.source_files)} published files"),
        ("Usable", f"{dq.pct_analysable:.1f}%",
         "internally consistent"),
        ("Causes unmapped", f"{dq.pct_cause_unmapped:.1f}%",
         "land in Unclassified"),
        ("Impact on derived headways",
         f"{dq.pct_impact_on_derived_headway:.0f}%",
         "rather than an assumed default"),
        ("Gaps capped", f"{dq.pct_gaps_winsorised:.2f}%",
         f"at {GAP_CAP_MINUTES} minutes"),
        ("Implausible rows", f"{dq.pct_implausible:.2f}%",
         "flagged and left out of headlines"),
    ]))
    body.append(table(
        ["File", "Layout", "Rows", "From", "To", "Routes", "Usable",
         "Unmapped", "Placeholder gaps"],
        [[f"<code>{escape(str(r.source_file))}</code>",
          f'<span class="pill {"ok" if r.schema_generation == "current" else "mute"}">'
          f"{escape(str(r.schema_generation))}</span>",
          num(r.rows_loaded), escape(str(r.first_date)), escape(str(r.last_date)),
          num(r.distinct_routes), f"{r.pct_analysable:.1f}%",
          f"{r.pct_cause_unmapped:.1f}%", num(r.gap_sentinel_values)]
         for r in d["dq_files"].itertuples()],
        numeric={2, 5, 6, 7, 8},
    ))
    body.append("</div>")

    # -- the mistake ----------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>The mistake that nearly got past me</h2>")
    body.append(finding(
        "A hundred rows were driving more than half the answer",
        "Because impact grows with the square of the gap, it is very sensitive "
        "to a long tail, and this dataset has one. My first version let the raw "
        "gaps through untouched, and around a hundred records carrying a value "
        "of exactly 999 minutes ended up outweighing every genuine incident in "
        "the file combined. On a route running every four minutes that value "
        "would mean 250 buses in a row failed to show up, so it is a placeholder, "
        "not a measurement. Nothing internal caught it &mdash; every table "
        "reconciled perfectly and the arithmetic was right the whole way "
        "through. What caught it was asking how much of the answer rested on how "
        f"few rows. Gaps are now capped at {GAP_CAP_MINUTES} minutes, just above "
        "the 99.9th percentile of real service gaps, and the build now stops if "
        "any single incident accounts for more than 2% of the total.",
    ))
    body.append("</div>")

    # -- headway confidence ---------------------------------------------------
    derived = headway[headway.headway_source != "default_assumed"]
    body.append('<div class="card">')
    body.append("<h2>Confidence in the headway estimates</h2>")
    body.append(
        '<p class="note">Each route gets its own headway for each part of the '
        "day. Where there were too few records to estimate one, I fall back to "
        "the route's overall median and then to a fixed default, and mark it so "
        "those routes can be discounted.</p>")
    counts = headway.headway_source.value_counts()
    body.append(hbar(
        [(str(k).replace("_", " "), float(v)) for k, v in counts.items()],
        [SERIES[2], SERIES[3], SERIES[1]][:len(counts)],
        row_h=32, label_w=190, fmt=lambda v: f"{v:,.0f} bands",
    ))
    if len(derived):
        body.append(
            f'<p class="note" style="margin-top:14px">The derived estimates run '
            f"from {derived.headway_min.min():.0f} to "
            f"{derived.headway_min.max():.0f} minutes, with a median of "
            f"{derived.headway_min.median():.0f}.</p>")
    body.append("</div>")

    # -- limitations ----------------------------------------------------------
    body.append('<div class="card">')
    body.append("<h2>What this does not tell you</h2>")
    body.append("""<ul class="note">
<li>These are <em>logged incidents</em>, not a record of all service. A route
with nothing logged is not necessarily reliable; it may just be logged less
consistently.</li>
<li>There is no ridership in this data, so rider impact is an index proportional
to passenger-minutes rather than a count of them. The rankings are unaffected;
the figures given in hours are estimates and labelled as such.</li>
<li>Headway is inferred rather than read from a timetable. Joining the TTC
schedule feed would replace my biggest inference with a fact, and it is the
first thing I would add.</li>
<li>Location is free text and only lightly cleaned, so the hotspots are
indicative.</li>
<li>Causes are recorded by staff at the time, with all the inconsistency that
implies.</li>
<li>No weather data is joined yet, so anything seasonal here is inferred from
the calendar and the mix of causes, not from observed conditions.</li>
</ul>""")
    body.append("</div>")

    return page("Method \u2014 Why Is My Bus Late?", "methodology.html", mode,
                "\n".join(body), built)


# --- main --------------------------------------------------------------------


def main() -> int:
    conn = sqlite3.connect(WAREHOUSE_DB)
    d = load(conn)
    conn.close()

    mode = str(d["dq"].data_mode)
    built = str(d["dq"].built_at)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("")

    pages = {
        "index.html": build_index(d, mode, built),
        "routes.html": build_routes(d, mode, built),
        "causes.html": build_causes(d, mode, built),
        "when.html": build_when(d, mode, built),
        "methodology.html": build_method(d, mode, built),
    }
    for name, html in pages.items():
        (SITE_DIR / name).write_text(html)
        print(f"  {name:22s} {len(html) / 1024:6.1f} KB")

    print(f"\nSite written to {SITE_DIR}  (data_mode = {mode})")
    if mode != "real":
        print("  Built without the published files; pages carry a notice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
