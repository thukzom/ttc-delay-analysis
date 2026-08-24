"""
Shared presentation layer for the site: palette, CSS, page shell, chart helpers.

Kept separate from the page builders so that every page is guaranteed to use the
same colours, spacing and chart mechanics. The palette is validated for
colour-vision deficiency and every chart pairs colour with a direct label or a
table view, so nothing depends on hue alone.
"""

from __future__ import annotations

from html import escape

# --- palette -----------------------------------------------------------------

# Emitted as CSS custom properties so charts follow the theme. The underlying
# hexes live in the stylesheet and are validated for colour-vision deficiency
# against both the light (#ffffff) and dark (#101010) surfaces.
SERIES = ["var(--s1)", "var(--s2)", "var(--s3)",
          "var(--s4)", "var(--s5)", "var(--s6)"]

# Sequential ramp for heatmaps, applied by class so the dark mode can invert
# direction: on a dark ground "near zero" must recede into the surface, which
# means starting dark rather than light.
SEQ_STEPS = 11

CATEGORY_COLOR = {
    "operator": SERIES[0],
    "mechanical": SERIES[1],
    "external": SERIES[2],
    "passenger": SERIES[3],
    "collision": SERIES[4],
    "security": SERIES[5],
    "other": "var(--ink-3)",
}

CATEGORY_LABEL = {
    "operator": "Operator & scheduling",
    "mechanical": "Mechanical",
    "external": "External (weather, traffic, events)",
    "passenger": "Passenger incidents",
    "collision": "Collisions",
    "security": "Security",
    "other": "Unclassified",
}

BAND_LABEL = {
    "early": "Overnight",
    "am_peak": "AM peak",
    "midday": "Midday",
    "pm_peak": "PM peak",
    "evening": "Evening",
    "unknown": "Unknown",
}

CSS = """
/* ===========================================================================
   Transit editorial.

   Three typefaces doing three different jobs, which is what keeps this from
   looking like a default dashboard:

     serif      prose and headlines - editorial, meant to be read
     condensed  labels, kickers, nav, table headers - transit signage
     monospace  every number, always tabular - timetable

   Layout is ruled, not boxed: 2px ink rules open each block instead of rounded
   cards on a tinted ground. Colour is ink-on-paper with a single signal red
   used only for emphasis; the chart series palette is separate and validated
   for colour-vision deficiency against both surfaces below.
   =========================================================================== */

:root{
  --paper:#ffffff;
  --band:#f2efe7;
  --ink:#141412;
  --ink-2:#55534b;
  --ink-3:#8b887e;
  --hair:rgba(20,20,18,.15);
  --rule:#141412;
  --signal:#c8241c;
  --masthead:#141412;
  --masthead-ink:#f5f2ea;

  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --s5:#e87ba4; --s6:#008300;
  --good:#0ca30c; --warn:#b07800; --crit:#c8241c;

  --f-serif:Georgia,"Iowan Old Style","Palatino Linotype",Palatino,
            "Times New Roman",serif;
  --f-cond:"Arial Narrow","Helvetica Neue Condensed",
           "Roboto Condensed",Helvetica,Arial,sans-serif;
  --f-sans:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;
  --f-mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;

  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    --paper:#101010;
    --band:#1a1a18;
    --ink:#f2efe7;
    --ink-2:#b5b2a8;
    --ink-3:#7c7a71;
    --hair:rgba(242,239,231,.18);
    --rule:#f2efe7;
    --signal:#ff5b45;
    --masthead:#000000;
    --masthead-ink:#f5f2ea;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
    --s5:#d55181; --s6:#008300;
    --good:#0ca30c; --warn:#c98500; --crit:#ff5b45;
    color-scheme:dark;
  }
}

*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);
  font:16px/1.65 var(--f-serif);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:underline;text-decoration-color:var(--signal);
  text-underline-offset:3px;text-decoration-thickness:1.5px}
a:hover{color:var(--signal)}

.wrap{max-width:1080px;margin:0 auto;padding:0 26px 96px}

/* ---- masthead ---------------------------------------------------------- */
.masthead{background:var(--masthead);color:var(--masthead-ink);
  border-bottom:3px solid var(--signal)}
.masthead .inner{max-width:1080px;margin:0 auto;padding:0 26px;
  display:flex;align-items:stretch;flex-wrap:wrap;gap:0;min-height:56px}
.brand{font-family:var(--f-cond);font-weight:700;text-transform:uppercase;
  letter-spacing:.14em;font-size:15px;display:flex;align-items:center;
  padding-right:26px;margin-right:auto;white-space:nowrap}
.brand em{font-style:normal;color:var(--signal)}
.masthead nav{display:flex;align-items:stretch}
.masthead nav a{font-family:var(--f-cond);text-transform:uppercase;
  letter-spacing:.12em;font-size:12.5px;text-decoration:none;
  display:flex;align-items:center;padding:0 15px;color:var(--masthead-ink);
  opacity:.72;border-bottom:3px solid transparent;margin-bottom:-3px}
.masthead nav a:hover{opacity:1;color:var(--masthead-ink)}
.masthead nav a.on{opacity:1;border-bottom-color:var(--signal);font-weight:700}
@media(max-width:620px){
  .masthead .inner{padding:0 16px}
  .brand{width:100%;padding:12px 0 6px}
  .masthead nav{flex-wrap:wrap;padding-bottom:2px}
  .masthead nav a{padding:8px 13px 8px 0}
}

/* ---- notice ------------------------------------------------------------ */
.banner{border-left:4px solid var(--signal);background:var(--band);
  padding:14px 18px;margin:26px 0 0;font-size:14.5px;line-height:1.55}
.banner b{font-weight:700}

/* ---- page head --------------------------------------------------------- */
header.page{padding:44px 0 30px;border-bottom:2px solid var(--rule);
  margin-bottom:34px}
.kicker{font-family:var(--f-cond);text-transform:uppercase;
  letter-spacing:.18em;font-size:12px;color:var(--signal);font-weight:700;
  margin:0 0 14px}
h1{font-family:var(--f-serif);font-size:clamp(34px,5.2vw,52px);font-weight:400;
  line-height:1.06;letter-spacing:-.02em;margin:0 0 18px;max-width:19ch}
.lede{font-size:18.5px;line-height:1.6;color:var(--ink-2);max-width:60ch;
  margin:0}
.meta{font-family:var(--f-mono);font-size:12px;color:var(--ink-3);
  margin-top:24px;line-height:1.95;letter-spacing:-.01em;max-width:86ch;
  border-top:1px solid var(--hair);padding-top:16px}

/* ---- blocks ------------------------------------------------------------ */
.card{border-top:2px solid var(--rule);padding:22px 0 30px;margin:0 0 6px}
/* the page header already closes with a rule; don't double it */
header.page + .card{border-top:none;padding-top:2px}
header.page + .grid2 > .card:first-child{border-top:none;padding-top:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 44px}
@media(max-width:860px){.grid2{grid-template-columns:1fr;gap:0}}

h2{font-family:var(--f-cond);text-transform:uppercase;letter-spacing:.14em;
  font-size:13.5px;font-weight:700;margin:0 0 12px;color:var(--ink)}
h3{font-family:var(--f-cond);text-transform:uppercase;letter-spacing:.12em;
  font-size:12px;font-weight:700;margin:30px 0 10px;color:var(--ink-3)}
.note{font-size:15.5px;line-height:1.62;color:var(--ink-2);margin:0 0 22px;
  max-width:66ch}
.note b{color:var(--ink);font-weight:700}

/* ---- departure board (hero stats) -------------------------------------- */
.board{background:var(--masthead);color:var(--masthead-ink);
  display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  margin:0 0 34px;border-top:3px solid var(--signal)}
.board .tile{padding:19px 17px 21px;border-right:1px solid rgba(245,242,234,.16);
  border-bottom:1px solid rgba(245,242,234,.16)}
.board .label{font-family:var(--f-cond);text-transform:uppercase;
  letter-spacing:.13em;font-size:10.5px;opacity:.66;margin-bottom:12px;
  line-height:1.4;min-height:4.2em}
.board .value{font-family:var(--f-mono);font-size:31px;font-weight:600;
  letter-spacing:-.035em;line-height:1;font-variant-numeric:tabular-nums;
  color:#fff}
.board .foot{font-size:12.5px;opacity:.6;margin-top:11px;line-height:1.45;
  font-family:var(--f-sans)}

/* ---- plain stat row ---------------------------------------------------- */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  border-top:1px solid var(--hair);margin:0 0 28px}
.tiles .tile{padding:16px 18px 18px;border-bottom:1px solid var(--hair);
  border-right:1px solid var(--hair)}
.tiles .label{font-family:var(--f-cond);text-transform:uppercase;
  letter-spacing:.13em;font-size:10.5px;color:var(--ink-3);margin-bottom:10px;
  line-height:1.4;min-height:4.2em}
.tiles .value{font-family:var(--f-mono);font-size:24px;font-weight:600;
  letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}
.tiles .foot{font-family:var(--f-sans);font-size:12px;color:var(--ink-3);
  margin-top:9px;line-height:1.45}

/* ---- charts ------------------------------------------------------------ */
svg{display:block;width:100%;height:auto;overflow:visible}
.gl{stroke:var(--hair);stroke-width:1}
.ax{stroke:var(--ink-3);stroke-width:1}
.tk{fill:var(--ink-3);font-size:11px;font-family:var(--f-mono);
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.dl{fill:var(--ink);font-size:11.5px;font-weight:600;font-family:var(--f-mono);
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.al{fill:var(--ink-2);font-size:12.5px;font-family:var(--f-sans)}
.bar{transition:opacity .12s}
.bar:hover{opacity:.7}

.legend{display:flex;flex-wrap:wrap;gap:8px 20px;margin:0 0 16px;
  font-family:var(--f-sans);font-size:12px;color:var(--ink-2)}
.legend span{display:flex;align-items:center;gap:8px}
.sw{width:13px;height:13px;flex:none}

/* ---- tables ------------------------------------------------------------ */
table{width:100%;border-collapse:collapse;font-family:var(--f-sans);
  font-size:13px}
th{text-align:left;font-family:var(--f-cond);font-weight:700;color:var(--ink);
  font-size:11px;text-transform:uppercase;letter-spacing:.11em;
  padding:9px 9px;border-bottom:2px solid var(--rule);white-space:nowrap;
  background:var(--paper)}
th.sortable{cursor:pointer;user-select:none}
th.sortable:hover{color:var(--signal)}
th .arrow{opacity:.3;margin-left:3px;font-size:9px}
th.active{color:var(--signal)}
th.active .arrow{opacity:1}
td{padding:8px 9px;border-bottom:1px solid var(--hair);vertical-align:baseline}
td.n{text-align:right;font-family:var(--f-mono);
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
td.nw{white-space:nowrap}
tbody tr:hover{background:var(--band)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}

/* route number blade, after the signage on a bus stop pole */
.blade{display:inline-block;background:var(--rule);color:var(--paper);
  font-family:var(--f-cond);font-weight:700;letter-spacing:.06em;
  font-size:11.5px;padding:2px 6px;margin-right:8px;min-width:30px;
  text-align:center;vertical-align:1px}

.pill{display:inline-block;padding:2px 8px;font-family:var(--f-cond);
  font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;
  border:1px solid;white-space:nowrap}
.pill.ok{color:var(--good);border-color:var(--good)}
.pill.warn{color:var(--warn);border-color:var(--warn)}
.pill.bad{color:var(--crit);border-color:var(--crit)}
.pill.mute{color:var(--ink-3);border-color:var(--hair)}

/* ---- controls ---------------------------------------------------------- */
input[type=search]{width:100%;max-width:300px;padding:9px 12px;font-size:14px;
  border:1px solid var(--ink-3);background:var(--paper);color:var(--ink);
  font-family:var(--f-sans);border-radius:0}
input[type=search]:focus{outline:2px solid var(--signal);outline-offset:1px;
  border-color:var(--signal)}
.controls{display:flex;gap:16px;flex-wrap:wrap;align-items:center;
  margin-bottom:16px}
.count{font-family:var(--f-mono);font-size:12px;color:var(--ink-3)}

details{margin-top:20px;border-top:1px solid var(--hair);padding-top:6px}
summary{cursor:pointer;font-family:var(--f-cond);text-transform:uppercase;
  letter-spacing:.12em;font-size:11.5px;color:var(--ink-3);padding:8px 0;
  user-select:none;font-weight:700}
summary:hover{color:var(--signal)}
details table{margin-top:12px}

/* ---- pull-out finding -------------------------------------------------- */
.finding{border-left:4px solid var(--signal);padding:4px 0 4px 20px;
  margin:26px 0}
.finding h3{font-family:var(--f-serif);text-transform:none;letter-spacing:-.01em;
  font-size:20px;font-weight:400;line-height:1.25;color:var(--ink);
  margin:0 0 10px}
.finding p{margin:0;color:var(--ink-2);font-size:15.5px;line-height:1.62;
  max-width:64ch}
.finding em{font-style:italic}

ul.note{padding-left:20px}
ul.note li{margin-bottom:9px}

footer{border-top:2px solid var(--rule);margin-top:56px;padding-top:22px;
  font-family:var(--f-sans);font-size:12.5px;color:var(--ink-3);
  line-height:1.75;max-width:78ch}

code{font-family:var(--f-mono);font-size:.88em;background:var(--band);
  padding:2px 5px;letter-spacing:-.02em}
.board code,.masthead code{background:rgba(255,255,255,.14)}

/* ---- heatmap ramp ------------------------------------------------------ */
.hm-na{fill:var(--hair)}
.hm-0{fill:#eff5fd}
.hm-1{fill:#d8e8fb}
.hm-2{fill:#c1dbf8}
.hm-3{fill:#a9cdf5}
.hm-4{fill:#91bff1}
.hm-5{fill:#78b0ed}
.hm-6{fill:#5fa1e8}
.hm-7{fill:#4691e2}
.hm-8{fill:#2f80d9}
.hm-9{fill:#1f6ec2}
.hm-10{fill:#155aa4}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){}
  :root:where(:not([data-theme="light"])) .hm-0{fill:#16202b} :root:where(:not([data-theme="light"])) .hm-1{fill:#1a2a3b} :root:where(:not([data-theme="light"])) .hm-2{fill:#1d354c} :root:where(:not([data-theme="light"])) .hm-3{fill:#20405e} :root:where(:not([data-theme="light"])) .hm-4{fill:#224b70} :root:where(:not([data-theme="light"])) .hm-5{fill:#245683} :root:where(:not([data-theme="light"])) .hm-6{fill:#256296} :root:where(:not([data-theme="light"])) .hm-7{fill:#256ea9} :root:where(:not([data-theme="light"])) .hm-8{fill:#2d7bbb} :root:where(:not([data-theme="light"])) .hm-9{fill:#4189cc} :root:where(:not([data-theme="light"])) .hm-10{fill:#5d98d9}
}
"""

PAGES = [
    ("index.html", "Overview"),
    ("routes.html", "Routes"),
    ("causes.html", "Causes"),
    ("when.html", "When"),
    ("methodology.html", "Method"),
]


def nav(current: str) -> str:
    links = "".join(
        f'<a href="{href}" class="{"on" if href == current else ""}">{escape(label)}</a>'
        for href, label in PAGES
    )
    return (
        '<div class="masthead"><div class="inner">'
        '<span class="brand"><span>Why Is My Bus <em>Late</em>?</span></span>'
        f"<nav>{links}</nav></div></div>"
    )


def sample_banner(mode: str) -> str:
    if mode == "real":
        return ""
    # Only ever appears on a local build made without the published files.
    # The deployed site is built from the real data or it is not built at all.
    return (
        '<div class="banner"><b>Placeholder build.</b> This page was generated '
        "without the published TTC files, so the figures below stand in for the "
        "real ones and should <b>not</b> be read as findings about the TTC.</div>"
    )


def page(title: str, current: str, mode: str, body: str, built: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="An analysis of TTC bus delays measured as the
waiting time riders actually experience, not how late the vehicles were.">
<meta name="color-scheme" content="light dark">
<style>{CSS}</style></head><body>
{nav(current)}
<div class="wrap">
{sample_banner(mode)}
{body}
<footer>
<b>Source.</b> City of Toronto Open Data, TTC Bus Delay Data, used under the
Open Government Licence &ndash; Toronto. Independent analysis; not affiliated
with or endorsed by the TTC.<br>
<b>Method.</b> The published files are reconciled into one table and analysed in
SQL; these pages are generated from the result and rebuild monthly. Last built
{escape(built)}. Figures marked <em>estimated</em> rest on an assumption about
boarding rates, set out on the <a href="methodology.html">method</a> page.
</footer>
</div></body></html>"""


# --- formatting --------------------------------------------------------------


def num(value, places: int = 0) -> str:
    try:
        return f"{float(value):,.{places}f}"
    except (TypeError, ValueError):
        return "&mdash;"


def compact(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "&mdash;"
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= limit:
            return f"{value / limit:.1f}{suffix}"
    return f"{value:,.0f}"


def tiles(items: list[tuple[str, str, str]], variant: str = "plain") -> str:
    """Stat row. `variant="board"` renders the dark departure-board treatment."""
    cls = "board" if variant == "board" else "tiles"
    return f'<div class="{cls}">' + "".join(
        f'<div class="tile"><div class="label">{escape(label)}</div>'
        f'<div class="value">{value}</div>'
        f'<div class="foot">{foot}</div></div>'
        for label, value, foot in items
    ) + "</div>"


def blade(route_label: str) -> str:
    """Render a route as a signage blade: number chip plus name."""
    text = str(route_label).strip()
    number, _, name = text.partition(" ")
    if not name:
        return f'<span class="blade">{escape(number)}</span>'
    return (f'<span class="blade">{escape(number)}</span>'
            f'{escape(name.title())}')


def legend(items: list[tuple[str, str]]) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i class="sw" style="background:{color}"></i>{escape(name)}</span>'
        for name, color in items
    ) + "</div>"


def table(
    headers: list[str], rows: list[list[str]],
    numeric: set[int] | None = None, nowrap: set[int] | None = None,
) -> str:
    numeric = numeric or set()
    nowrap = nowrap or set()

    def cell(index: int, content: str) -> str:
        classes = " ".join(
            name for name, ok in (("n", index in numeric), ("nw", index in nowrap))
            if ok
        )
        return f'<td class="{classes}">{content}</td>'

    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(cell(i, c) for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    return (
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def finding(heading: str, text: str) -> str:
    return f'<div class="finding"><h3>{escape(heading)}</h3><p>{text}</p></div>'


# --- charts ------------------------------------------------------------------


def hbar(
    rows: list[tuple[str, float]], colors: list[str] | None = None,
    width: int = 900, label_w: int = 210, pad_r: int = 96,
    row_h: int = 34, fmt=compact,
) -> str:
    """Horizontal bars with a direct value label on every bar.

    The direct labels are what discharge the palette's low-contrast warning on
    the lighter hues: magnitude never rests on colour alone.
    """
    if not rows:
        return "<p class='note'>No data.</p>"
    plot_w = width - label_w - pad_r
    height = row_h * len(rows) + 8
    vmax = max(abs(v) for _, v in rows) or 1
    out = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for index, (label, value) in enumerate(rows):
        y = index * row_h + 6
        bar_w = max(plot_w * abs(value) / vmax, 2)
        color = (colors[index] if colors else SERIES[0])
        out.append(
            f'<text class="al" x="{label_w - 12}" y="{y + 15}" '
            f'text-anchor="end">{escape(label)}</text>'
        )
        out.append(
            f'<rect class="bar" x="{label_w}" y="{y + 3}" width="{bar_w:.1f}" '
            f'height="18" rx="4" fill="{color}">'
            f"<title>{escape(label)}: {fmt(value)}</title></rect>"
        )
        out.append(
            f'<text class="dl" x="{label_w + bar_w + 9:.1f}" y="{y + 16.5}">'
            f"{fmt(value)}</text>"
        )
    out.append("</svg>")
    return "".join(out)


def diverging_bar(
    rows: list[tuple[str, float]], width: int = 900,
    label_w: int = 230, pad_r: int = 70, row_h: int = 36,
) -> str:
    """Bars either side of a zero line, for signed differences."""
    if not rows:
        return "<p class='note'>No data.</p>"
    plot_w = width - label_w - pad_r
    height = row_h * len(rows) + 26
    vmax = max(abs(v) for _, v in rows) or 1
    mid = label_w + plot_w / 2
    # Cap the bar so its value label always has room between the bar end and the
    # category name. Without this the longest negative bar runs its label into
    # the label column and the two overlap.
    max_bar = plot_w / 2 - 62
    out = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    out.append(
        f'<line class="ax" x1="{mid}" y1="4" x2="{mid}" y2="{height - 22}"/>'
    )
    for index, (label, value) in enumerate(rows):
        y = index * row_h + 8
        bar_w = max_bar * abs(value) / vmax
        positive = value >= 0
        x = mid if positive else mid - bar_w
        color = "var(--crit)" if positive else "var(--s1)"
        out.append(
            f'<text class="al" x="{label_w - 14}" y="{y + 15}" '
            f'text-anchor="end">{escape(label)}</text>'
        )
        out.append(
            f'<rect class="bar" x="{x:.1f}" y="{y + 3}" width="{max(bar_w, 1.5):.1f}" '
            f'height="18" rx="4" fill="{color}">'
            f"<title>{escape(label)}: {value:+.1f} pp</title></rect>"
        )
        anchor_x = (x + bar_w + 8) if positive else (x - 8)
        anchor = "start" if positive else "end"
        out.append(
            f'<text class="dl" x="{anchor_x:.1f}" y="{y + 16.5}" '
            f'text-anchor="{anchor}">{value:+.1f} pp</text>'
        )
    out.append(
        f'<text class="al" x="{mid - 8}" y="{height - 6}" text-anchor="end" '
        'style="font-size:11.5px;opacity:.75">'
        "hurts riders less than its frequency suggests</text>"
    )
    out.append(
        f'<text class="al" x="{mid + 8}" y="{height - 6}" '
        'style="font-size:11.5px;opacity:.75">'
        "hurts riders more</text>"
    )
    out.append("</svg>")
    return "".join(out)


def line_chart(
    series: list[dict], x_labels: list[str], width: int = 900,
    height: int = 230, y_fmt=lambda v: f"{v:,.0f}", y_max: float | None = None,
) -> str:
    if not series or not x_labels:
        return "<p class='note'>No data.</p>"
    pad_l, pad_r, pad_t, pad_b = 58, 16, 12, 32
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    top = y_max or max(max(s["values"]) for s in series) * 1.12 or 1
    n = len(x_labels)
    x = lambda i: pad_l + plot_w * i / max(n - 1, 1)
    y = lambda v: pad_t + plot_h - plot_h * v / top

    out = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for frac in (0, 0.25, 0.5, 0.75, 1):
        yy = pad_t + plot_h * (1 - frac)
        out.append(f'<line class="gl" x1="{pad_l}" y1="{yy:.1f}" '
                   f'x2="{width - pad_r}" y2="{yy:.1f}"/>')
        out.append(f'<text class="tk" x="{pad_l - 8}" y="{yy + 3.5:.1f}" '
                   f'text-anchor="end">{y_fmt(top * frac)}</text>')
    out.append(f'<line class="ax" x1="{pad_l}" y1="{pad_t + plot_h}" '
               f'x2="{width - pad_r}" y2="{pad_t + plot_h}"/>')
    step = max(n // 8, 1)
    for i in range(0, n, step):
        out.append(f'<text class="tk" x="{x(i):.1f}" y="{height - 10}" '
                   f'text-anchor="middle">{escape(str(x_labels[i]))}</text>')
    for s in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s["values"]))
        out.append(
            f'<polyline fill="none" stroke="{s["color"]}" '
            f'stroke-width="{s.get("width", 2)}" stroke-linejoin="round" '
            f'stroke-linecap="round" points="{pts}"/>'
        )
        for i, v in enumerate(s["values"]):
            out.append(
                f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="7" fill="transparent">'
                f'<title>{escape(str(x_labels[i]))}: {y_fmt(v)}</title></circle>'
            )
    out.append("</svg>")
    return "".join(out)


def heatmap(
    matrix: list[list[float]], row_labels: list[str], col_labels: list[str],
    width: int = 900, cell_h: int = 30, fmt=lambda v: f"{v:,.0f}",
    caption: str = "",
) -> str:
    """Sequential single-hue heatmap. Values are also available on hover."""
    if not matrix:
        return "<p class='note'>No data.</p>"
    label_w, pad_r, pad_t = 92, 8, 22
    cols = len(col_labels)
    cell_w = (width - label_w - pad_r) / cols
    height = pad_t + cell_h * len(row_labels) + 26
    flat = [v for row in matrix for v in row if v is not None]
    vmax = max(flat) if flat else 1
    vmin = min(flat) if flat else 0

    out = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for index, label in enumerate(col_labels):
        if cols > 14 and index % 2:
            continue
        out.append(
            f'<text class="tk" x="{label_w + cell_w * (index + 0.5):.1f}" '
            f'y="{pad_t - 8}" text-anchor="middle">{escape(str(label))}</text>'
        )
    for r, row_label in enumerate(row_labels):
        y = pad_t + r * cell_h
        out.append(
            f'<text class="al" x="{label_w - 10}" y="{y + cell_h / 2 + 4:.1f}" '
            f'text-anchor="end">{escape(row_label)}</text>'
        )
        for c, value in enumerate(matrix[r]):
            x = label_w + c * cell_w
            if value is None:
                cls = "hm-na"
                title = f"{row_label} {col_labels[c]}: no data"
            else:
                span = (vmax - vmin) or 1
                step = int((value - vmin) / span * (SEQ_STEPS - 1))
                cls = f"hm-{max(0, min(step, SEQ_STEPS - 1))}"
                title = f"{row_label} {col_labels[c]}: {fmt(value)}"
            out.append(
                f'<rect class="{cls}" x="{x:.1f}" y="{y}" '
                f'width="{cell_w - 2:.1f}" height="{cell_h - 2}">'
                f"<title>{escape(title)}</title></rect>"
            )
    # Scale key, so the ramp is readable without hovering every cell.
    key_y = height - 16
    key_w = 150
    for index in range(SEQ_STEPS):
        out.append(
            f'<rect class="hm-{index}" '
            f'x="{label_w + index * key_w / SEQ_STEPS:.1f}" y="{key_y}" '
            f'width="{key_w / SEQ_STEPS:.1f}" height="9"/>'
        )
    out.append(f'<text class="tk" x="{label_w - 10}" y="{key_y + 8}" '
               f'text-anchor="end">{fmt(vmin)}</text>')
    out.append(f'<text class="tk" x="{label_w + key_w + 8}" y="{key_y + 8}">'
               f"{fmt(vmax)}{('  ' + caption) if caption else ''}</text>")
    out.append("</svg>")
    return "".join(out)


def scatter(
    points: list[dict], x_label: str, y_label: str,
    width: int = 900, height: int = 340,
) -> str:
    """points: {x, y, label, color}"""
    if not points:
        return "<p class='note'>No data.</p>"
    pad_l, pad_r, pad_t, pad_b = 62, 18, 16, 46
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    xmax = max(p["x"] for p in points) * 1.08 or 1
    ymax = max(p["y"] for p in points) * 1.08 or 1
    fx = lambda v: pad_l + plot_w * v / xmax
    fy = lambda v: pad_t + plot_h - plot_h * v / ymax

    out = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for frac in (0, 0.25, 0.5, 0.75, 1):
        yy = pad_t + plot_h * (1 - frac)
        out.append(f'<line class="gl" x1="{pad_l}" y1="{yy:.1f}" '
                   f'x2="{width - pad_r}" y2="{yy:.1f}"/>')
        out.append(f'<text class="tk" x="{pad_l - 8}" y="{yy + 3.5:.1f}" '
                   f'text-anchor="end">{compact(ymax * frac)}</text>')
    for frac in (0, 0.25, 0.5, 0.75, 1):
        xx = pad_l + plot_w * frac
        out.append(f'<text class="tk" x="{xx:.1f}" y="{pad_t + plot_h + 18}" '
                   f'text-anchor="middle">{compact(xmax * frac)}</text>')
    out.append(f'<line class="ax" x1="{pad_l}" y1="{pad_t + plot_h}" '
               f'x2="{width - pad_r}" y2="{pad_t + plot_h}"/>')
    for point in points:
        out.append(
            f'<circle class="bar" cx="{fx(point["x"]):.1f}" cy="{fy(point["y"]):.1f}" '
            f'r="6" fill="{point.get("color", SERIES[0])}" '
            f'stroke="var(--surface)" stroke-width="1.5">'
            f'<title>{escape(point["label"])}</title></circle>'
        )
    out.append(f'<text class="tk" x="{pad_l + plot_w / 2:.1f}" y="{height - 8}" '
               f'text-anchor="middle">{escape(x_label)}</text>')
    out.append(
        f'<text class="tk" transform="translate(14,{pad_t + plot_h / 2:.1f}) '
        f'rotate(-90)" text-anchor="middle">{escape(y_label)}</text>'
    )
    out.append("</svg>")
    return "".join(out)
