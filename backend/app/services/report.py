import datetime as dt
import html

import plotly.graph_objects as go

CSS = """body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:960px;margin:32px auto;padding:0 20px;color:#1d2433}
h1{margin-bottom:4px}h2{margin-top:32px;border-bottom:1px solid #dde3ee;padding-bottom:6px}
.muted{color:#667}.kpi{display:flex;gap:12px;flex-wrap:wrap}.k{background:#f4f6fb;border-radius:10px;padding:12px 16px;min-width:120px}
.k b{display:block;font-size:22px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dde3ee;padding:6px 8px;text-align:left}
code{background:#f4f6fb;padding:2px 5px;border-radius:4px;font-size:12px}.chart{margin:16px 0}@media print{.chart{break-inside:avoid}}"""


SVG_LOGO = """<svg width='32' height='32' viewBox='0 0 40 40' fill='none' xmlns='http://www.w3.org/2000/svg' style='vertical-align:middle;margin-right:10px'><rect width='40' height='40' rx='10' fill='#2563EB'/><path d='M20 7L31 29L20 24L9 29L20 7Z' fill='white'/><circle cx='20' cy='20' r='3.5' fill='#38BDF8'/></svg>"""


def build_html(title, ds_name, prof, insights, narrative, narrated_by, figures):
    q = prof["quality"]
    esc = html.escape
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>",
             "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>", f"<style>{CSS}</style></head><body>",
             f"<div style='display:flex;align-items:center;margin-bottom:8px'>{SVG_LOGO}<span style='font-weight:700;font-size:20px;letter-spacing:-0.02em;color:#0F172A'>DataPilot</span></div>",
             f"<h1>{esc(title)}</h1><div class='muted'>Dataset: {esc(ds_name)} · Generated {dt.date.today():%d %b %Y} by DataPilot</div>",
             "<h2>Data quality</h2><div class='kpi'>"]
    for label, val in [("Quality score", q["score"]), ("Completeness", q["completeness"]), ("Uniqueness", q["uniqueness"]),
                       ("Validity", q["validity"]), ("Consistency", q["consistency"])]:
        parts.append(f"<div class='k'><b>{val}</b>{label}</div>")
    parts.append(f"<div class='k'><b>{prof['rows']:,}</b>Rows</div><div class='k'><b>{prof['cols']}</b>Columns</div></div>")
    parts.append(f"<h2>Key findings</h2><p class='muted'>Narrative by: {esc(narrated_by)}. Every finding below cites an insight ID with a verifiable SQL query.</p>")
    parts.append("".join(f"<p>{esc(line)}</p>" for line in narrative.splitlines() if line.strip()))
    if insights:
        parts.append("<h2>Evidence</h2><table><tr><th>ID</th><th>Type</th><th>Finding</th><th>Verifying SQL</th></tr>")
        for i in insights:
            parts.append(f"<tr><td>{i['id']}</td><td>{esc(i['type'])}</td><td><b>{esc(i['title'])}</b><br>{esc(i['detail'])}</td>"
                         f"<td><code>{esc(i['evidence_sql'])}</code></td></tr>")
        parts.append("</table>")
    if figures:
        parts.append("<h2>Charts</h2>")
        for k, f in enumerate(figures):
            fig_data = f.get("figure", f) if isinstance(f, dict) else f
            meta = (f.get("datapilot_meta", {}) if isinstance(f, dict) else {}) or (fig_data.get("datapilot_meta", {}) if isinstance(fig_data, dict) else {})
            chart_title = (f.get("title") if isinstance(f, dict) else "") or meta.get("title", "")
            if chart_title:
                parts.append(f"<h3 style='margin-top:18px;margin-bottom:6px;font-size:16px;color:#0F1B2D'>{esc(chart_title)}</h3>")
            fig = go.Figure(fig_data)
            parts.append(f"<div class='chart'>{fig.to_html(full_html=False, include_plotlyjs=False, div_id=f'c{k}')}</div>")
    parts.append("</body></html>")
    return "".join(parts)
