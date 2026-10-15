"""
Console UI: tokens, CSS, and HTML renderers used by app.py.

Everything here is presentation. It reads run records and reference data and
returns HTML strings for st.markdown(unsafe_allow_html=True).
"""
import html

from pipeline import config

STATUS = {"Approve": "#3DDC97", "Hold": "#FFB454", "Reject": "#FF5C7A", "Not decided": "#8FA1BD"}
STAGE_STATUS = {"ok": "#3DDC97", "warn": "#FFB454", "failed": "#FF5C7A", "skipped": "#5B6B85", "running": "#7AA2FF"}
SOURCE_LABEL = {"rules": "rules", "ai": "AI", "both": "rules + AI"}
CONF_TICKS = {"high": 3, "medium": 2, "low": 1}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
:root{--bg:#0E1726;--panel:#152238;--raised:#1C2D47;--line:#223554;--ink:#E6ECF5;--muted:#8FA1BD;--dim:#5B6B85;
      --accent:#7AA2FF;--ok:#3DDC97;--warn:#FFB454;--bad:#FF5C7A;--mono:'IBM Plex Mono',ui-monospace,Menlo,monospace;--sans:'IBM Plex Sans',-apple-system,Segoe UI,sans-serif}
html,body,.stApp,.stApp p,.stApp div,.stApp label,.stApp button,.stApp input,.stApp textarea,.stApp select,.stApp li,.stApp td,.stApp th,.stApp h1,.stApp h2,.stApp h3,.stApp small,.stApp summary{font-family:var(--sans)}
.stApp span[data-testid="stIconMaterial"],.stApp [class*="material-symbols"],.stApp span[translate="no"]{font-family:"Material Symbols Rounded"!important}
[data-testid="stAppViewContainer"]{background:var(--bg)}
[data-testid="stHeader"]{background:var(--bg);height:2.75rem}
[data-testid="stToolbar"],[data-testid="stDecoration"],.stDeployButton{display:none}
[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapseButton"],[data-testid="stSidebar"] button[kind="headerNoPadding"]{display:none!important}
[data-testid="stSidebar"]{min-width:300px!important;max-width:300px!important;transform:none!important;visibility:visible!important}
[data-testid="stSidebar"][aria-expanded="false"]{display:block!important;margin-left:0!important}
[data-testid="stSidebar"]{background:#0B1320;border-right:1px solid var(--line)}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:var(--muted)}
.block-container{padding-top:1.6rem;padding-bottom:3rem;max-width:1440px}
h1,h2,h3{letter-spacing:-.01em;color:var(--ink)}
h1{font-size:24px;font-weight:600;margin:0 0 2px}
h2{font-size:17px;font-weight:600;margin:0 0 10px}
.ap-sub{color:var(--muted);margin:0 0 16px;font-size:13.5px;max-width:80ch}
code,.mono{font-family:var(--mono)!important}

/* verdict strip */
.ap-verdict{display:grid;grid-template-columns:minmax(220px,auto) 1fr;gap:4px 32px;align-items:center;background:var(--panel);border-left:5px solid var(--s);border-radius:6px;padding:16px 20px;margin:2px 0 12px}
.ap-verdict .word{font-size:30px;font-weight:600;line-height:1.05;color:var(--s);letter-spacing:-.01em}
.ap-verdict .file{color:var(--muted);font-size:12.5px;margin-top:6px;font-family:var(--mono)}
.ap-verdict .act{font-size:14.5px;color:var(--ink);line-height:1.5}
.ap-verdict .codes{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}

/* summary cards */
.ap-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 14px}
.ap-card{background:var(--panel);border-radius:6px;padding:14px 16px;border-top:2px solid var(--c,var(--line));min-width:0}
.ap-card .l{font-size:12px;color:var(--muted);margin-bottom:6px}
.ap-card .h{font-size:15px;color:var(--ink);font-weight:500;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ap-card .h .mono{color:var(--muted);font-size:12.5px;margin-left:6px}
.ap-card .d{font-size:12.5px;color:var(--muted);margin-top:4px;line-height:1.45}
.ap-card .n{font-family:var(--mono);color:var(--ink)}
.ap-card .n.s{color:var(--c)}

/* tabs */
.stTabs [data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid var(--line);margin-bottom:12px}
.stTabs [data-baseweb="tab"]{padding:8px 14px;font-size:13.5px;color:var(--muted);background:transparent}
.stTabs [aria-selected="true"]{color:var(--ink)}
.stTabs [data-baseweb="tab-highlight"]{background:var(--accent)}
.stTabs [data-baseweb="tab-border"]{display:none}
.ap-pill{display:inline-block;font-family:var(--mono);font-size:11.5px;padding:2px 8px;border-radius:3px;border:1px solid var(--line);color:var(--muted);background:transparent;white-space:nowrap}
.ap-pill.primary{border-color:var(--s);color:var(--s)}
.ap-pill.s-Approve{border-color:#3DDC97;color:#3DDC97}.ap-pill.s-Hold{border-color:#FFB454;color:#FFB454}.ap-pill.s-Reject{border-color:#FF5C7A;color:#FF5C7A}

/* panels */
.ap-panel{background:var(--panel);border-radius:6px;padding:14px 16px 12px;margin-bottom:12px;border-top:2px solid var(--line);min-width:0;overflow:hidden}
.ap-panel.ok{border-top-color:var(--ok)}.ap-panel.warn{border-top-color:var(--warn)}.ap-panel.bad{border-top-color:var(--bad)}.ap-panel.accent{border-top-color:var(--accent)}
.ap-panel h3{font-size:12.5px;font-weight:600;color:var(--muted);margin:0 0 10px;letter-spacing:0}
.ap-panel h3 .sub{font-weight:400;color:var(--dim)}

/* stage rail */
.ap-step{display:grid;grid-template-columns:12px 1fr auto;gap:10px;align-items:start;padding:8px 0;border-bottom:1px solid var(--line)}
.ap-step:last-child{border-bottom:0}
.ap-step .dot{width:10px;height:10px;border-radius:50%;margin-top:5px;background:var(--c);box-shadow:0 0 0 3px color-mix(in srgb,var(--c) 22%,transparent)}
.ap-step .dot.running{animation:ap-pulse 1s ease-in-out infinite}
@keyframes ap-pulse{50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.ap-step .dot.running{animation:none}}
.ap-step .name{font-size:13.5px;font-weight:500;color:var(--ink)}
.ap-step .sum{font-size:12.5px;color:var(--muted);line-height:1.4}
.ap-step .ms{font-family:var(--mono);font-size:11px;color:var(--dim);padding-top:2px}
.ap-step.pending .name,.ap-step.pending .sum{color:var(--dim)}

/* ledger */
.ap-ledger{width:100%;border-collapse:collapse;table-layout:fixed}
.ap-ledger td{padding:7px 6px;border-bottom:1px solid var(--line);vertical-align:top;font-size:13px;overflow:hidden;text-overflow:ellipsis}
.ap-ledger tr:last-child td{border-bottom:0}
.ap-ledger .k{color:var(--muted);width:19%}
.ap-ledger .v{font-family:var(--mono);color:var(--ink);text-align:right;white-space:nowrap;width:33%;font-size:13.5px}
.ap-ledger .v.miss{color:var(--dim)}
.ap-ledger .src{width:14%;color:var(--muted);font-size:12px;white-space:normal}
.ap-ledger .conf{width:8%;font-family:var(--mono);letter-spacing:1px;font-size:11px;white-space:nowrap}
.ap-ledger .ev{font-family:var(--mono);font-size:11px;color:var(--dim);white-space:nowrap;width:26%}
.ap-ledger .conflict{color:var(--warn);font-size:11.5px}
.ap-ledger tr.sep td{border-bottom:1px solid var(--raised);padding:3px 6px;color:var(--dim);font-size:11.5px}

/* budget bar */
.ap-budget{margin:6px 0 4px}
.ap-budget .track{position:relative;height:16px;background:var(--raised);border-radius:3px;overflow:visible}
.ap-budget .seg{position:absolute;top:0;height:16px}
.ap-budget .before{background:#3A4F73}
.ap-budget .this{background:var(--s)}
.ap-budget .mark{position:absolute;top:-5px;width:2px;height:26px;background:var(--ink)}
.ap-budget .tol{position:absolute;top:-5px;width:0;height:26px;border-left:2px dashed var(--muted)}
.ap-budget .lbl{display:flex;justify-content:space-between;font-size:11.5px;color:var(--muted);margin-top:8px;font-family:var(--mono)}
.ap-kv{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.ap-kv div{background:var(--raised);border-radius:4px;padding:8px 10px;min-width:0}
.ap-kv .l{font-size:11.5px;color:var(--muted)}
.ap-kv .n{font-family:var(--mono);font-size:14px;color:var(--ink);margin-top:2px;overflow-wrap:anywhere}
.ap-kv .n.s{color:var(--s)}

/* checks & lists */
.ap-check{display:grid;grid-template-columns:16px 150px 1fr;gap:8px;padding:5px 0;font-size:12.5px;border-bottom:1px solid var(--line)}
.ap-check:last-child{border-bottom:0}
.ap-check .g{font-family:var(--mono);font-weight:600}
.ap-check .c{color:var(--muted);font-size:12px}
.ap-check .d{color:var(--ink)}
.ap-policy{counter-reset:p;padding:0;margin:0;list-style:none}
.ap-policy li{counter-increment:p;display:grid;grid-template-columns:22px 1fr;gap:6px;padding:5px 0;font-size:12.5px;color:var(--ink);border-bottom:1px solid var(--line)}
.ap-policy li:last-child{border-bottom:0}
.ap-policy li::before{content:counter(p);font-family:var(--mono);color:var(--dim);font-size:11px;padding-top:2px}
.ap-line{color:var(--muted);font-size:12.5px;margin:4px 0}

/* KPI strip */
.ap-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:10px}
.ap-kpi{background:var(--panel);border-radius:6px;padding:12px 14px;border-top:2px solid var(--c,var(--line))}
.ap-kpi .l{font-size:12px;color:var(--muted)}
.ap-kpi .n{font-family:var(--mono);font-size:26px;color:var(--c,var(--ink));line-height:1.1;margin-top:4px}
.ap-kpi .h{font-size:11px;color:var(--dim);margin-top:4px}
.ap-mix{height:8px;border-radius:4px;overflow:hidden;display:flex;margin:4px 0 16px;background:var(--raised)}
.ap-mix span{display:block;height:100%}

/* data table */
.ap-table{width:100%;border-collapse:collapse;font-size:12.5px}
.ap-table th{text-align:left;color:var(--muted);font-weight:500;padding:8px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
.ap-table td{padding:8px 8px;border-bottom:1px solid var(--line);color:var(--ink);vertical-align:top}
.ap-table.fixed{table-layout:fixed}
.ap-table .wrap{font-family:var(--mono);white-space:normal;overflow-wrap:anywhere;font-size:11.5px}
.ap-table tr:hover td{background:var(--raised)}
.ap-table .num{font-family:var(--mono);text-align:right;white-space:nowrap}
.ap-table .m{font-family:var(--mono);white-space:nowrap}
.ap-table .mut{color:var(--muted)}
.ap-wrap{overflow-x:auto}
.ap-empty{background:var(--panel);border-radius:6px;padding:28px 24px;color:var(--muted)}
.ap-empty b{color:var(--ink);font-weight:600;display:block;margin-bottom:6px}
.ap-note{font-size:12.5px;color:var(--muted);margin:6px 0 0}

/* streamlit widget alignment */
[data-testid="stFileUploader"] section{background:var(--panel);border:1px dashed var(--line);border-radius:6px}
div[data-baseweb="select"]>div{background:var(--panel);border-color:var(--line)}
.stButton>button{border-radius:4px;font-weight:500}
[data-testid="stExpander"] details{background:var(--panel);border:1px solid var(--line);border-radius:6px}
</style>
"""


def e(x):
    return html.escape("" if x is None else str(x))


def money(x):
    return f"₹{x:,.2f}" if isinstance(x, (int, float)) else ("—" if x in (None, "") else str(x))


def qty(x):
    if isinstance(x, (int, float)):
        return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"
    return "—" if x in (None, "") else str(x)


def pill(text, cls=""):
    return f'<span class="ap-pill {cls}">{e(text)}</span>'


# ----------------------------------------------------------------- verdict
def verdict(record, filename=None):
    d = record.get("decision") or {}
    status = d.get("status", "Not decided")
    color = STATUS.get(status, STATUS["Not decided"])
    codes = d.get("codes") or []
    primary = d.get("primary_code")
    chips = "".join(pill(c, "primary" if c == primary else "") for c in codes)
    meta = []
    ing = record.get("ingest") or {}
    if ing.get("path") == "ocr":
        meta.append(f"scanned, OCR {ing.get('ocr_confidence')}%")
    elif ing.get("path"):
        meta.append("text layer")
    if record.get("ai_call_count") is not None:
        meta.append(f"{record['ai_call_count']} AI call{'s' if record['ai_call_count'] != 1 else ''}")
    if record.get("elapsed_ms") is not None:
        meta.append(f"{record['elapsed_ms']} ms")
    return (f'<div class="ap-verdict" style="--s:{color}">'
            f'<div><div class="word">{e(status)}</div><div class="file">{e(filename or record.get("filename"))}'
            f'{", " + ", ".join(meta) if meta else ""}</div></div>'
            f'<div><div class="act">{e(d.get("next_action") or "")}</div><div class="codes">{chips}</div></div></div>')


# ----------------------------------------------------------------- summary cards
def summary_cards(record):
    v = record.get("vendor") or {}
    p = record.get("po") or {}
    ex = record.get("extract") or {}
    merged = ex.get("merged") or {}
    d = record.get("decision") or {}
    ing = record.get("ingest") or {}

    # vendor
    vc = "#3DDC97" if v.get("approved") else "#FF5C7A"
    vh = f'{e(v.get("legal_name") or (merged.get("vendor_name") or {}).get("value") or "No vendor matched")}' + (f'<span class="mono">{e(v["vendor_id"])}</span>' if v.get("vendor_id") else "")
    vd = e(v.get("how") or v.get("summary") or "")

    # po
    if p.get("found"):
        over = (p.get("variance_pct") or 0) > float(p.get("tolerance_pct") or 2)
        pc = "#FFB454" if (over or p.get("method") == "inferred" or p.get("vendor_matches") is False or p.get("po_status") != "open") else "#3DDC97"
        ph = f'<span class="mono">{e(p["po_number"])}</span> {e(p.get("description", ""))}'
        pd_ = (f'<span class="n">{money(p.get("cumulative"))}</span> of <span class="n">{money(p.get("po_amount"))}</span> after this invoice'
               + (f' <span class="n s">({p["variance_pct"]:+.2f}%)</span>' if p.get("variance_pct") is not None else ""))
    else:
        pc, ph, pd_ = "#FFB454", "No PO matched", e(p.get("summary") or "")

    # extraction
    found = sum(1 for k in config.FIELDS if k in merged)
    intra, inter = ("cgst" in merged or "sgst" in merged), ("igst" in merged)
    expected = len(config.FIELDS) - (1 if intra and not inter else 2 if inter and not intra else 0)  # only one GST form applies
    low = sum(1 for k in config.FIELDS if merged.get(k, {}).get("confidence") == "low")
    ai_n = record.get("ai_call_count") or 0
    ec = "#FFB454" if low or (ex.get("ai_status") == "unavailable") else "#7AA2FF"
    eh = f'{found} of {expected} fields read'
    path = "scan, OCR " + str(ing.get("ocr_confidence")) + "%" if ing.get("path") == "ocr" else "text layer"
    ed = f'{e(path)}; {ai_n} AI call{"s" if ai_n != 1 else ""}' + (f'; <span style="color:#FFB454">{low} low-confidence</span>' if low else "") + (f'; {record.get("elapsed_ms")} ms' if record.get("elapsed_ms") is not None else "")

    return (f'<div class="ap-cards">'
            f'<div class="ap-card" style="--c:{vc}"><div class="l">Vendor</div><div class="h">{vh}</div><div class="d">{vd}</div></div>'
            f'<div class="ap-card" style="--c:{pc}"><div class="l">Purchase order</div><div class="h">{ph}</div><div class="d">{pd_}</div></div>'
            f'<div class="ap-card" style="--c:{ec}"><div class="l">Extraction</div><div class="h">{eh}</div><div class="d">{ed}</div></div>'
            f'</div>')


# ----------------------------------------------------------------- stage rail
def rail(events, stage_labels, all_stages):
    done = {ev["name"]: ev for ev in events}
    rows = []
    running_set = False
    for name, label in all_stages:
        ev = done.get(name)
        if ev:
            c = STAGE_STATUS.get(ev["status"], "#5B6B85")
            rows.append(f'<div class="ap-step" style="--c:{c}"><div class="dot"></div><div><div class="name">{e(label)}</div>'
                        f'<div class="sum">{e(ev["summary"])}</div></div><div class="ms">{ev.get("ms", "")} ms</div></div>')
        elif not running_set and events is not None and len(events) < len(all_stages):
            running_set = True
            rows.append(f'<div class="ap-step" style="--c:{STAGE_STATUS["running"]}"><div class="dot running"></div><div><div class="name">{e(label)}</div>'
                        f'<div class="sum">running</div></div><div class="ms"></div></div>')
        else:
            rows.append(f'<div class="ap-step pending" style="--c:#2A3B58"><div class="dot"></div><div><div class="name">{e(label)}</div></div><div class="ms"></div></div>')
    return '<div class="ap-panel accent"><h3>Pipeline</h3>' + "".join(rows) + "</div>"


# ----------------------------------------------------------------- field ledger
def ledger(record):
    ex = record.get("extract") or {}
    merged = ex.get("merged") or {}
    groups = [("Identity", config.IDENTITY_FIELDS), ("Amounts", config.MONEY_FIELDS)]
    rows = []
    for title, keys in groups:
        rows.append(f'<tr class="sep"><td colspan="5">{title}</td></tr>')
        for k in keys:
            f = merged.get(k)
            label = k.replace("_", " ")
            if not f:
                if k in ("cgst", "sgst", "igst") and any(x in merged for x in ("cgst", "sgst", "igst")):
                    continue  # the other GST form is present; this one is simply not charged
                rows.append(f'<tr><td class="k">{e(label)}</td><td class="v miss">not found</td><td class="src"></td><td class="conf"></td><td class="ev"></td></tr>')
                continue
            val = money(f["value"]) if k in config.AMOUNT_FIELDS else f["value"]
            ticks = CONF_TICKS.get(f.get("confidence"), 0)
            tick_color = {"high": "var(--ok)", "medium": "var(--accent)", "low": "var(--warn)"}.get(f.get("confidence"), "var(--dim)")
            conf_html = f'<span style="color:{tick_color}">{"▮" * ticks}</span><span style="color:var(--raised)">{"▮" * (3 - ticks)}</span>'
            src = SOURCE_LABEL.get(f.get("source"), f.get("source"))
            extra = ""
            if f.get("conflict"):
                c = f["conflict"]
                extra = f'<div class="conflict">rules read {e(money(c["rules"]) if k in config.AMOUNT_FIELDS else c["rules"])}</div>'
            rows.append(f'<tr><td class="k">{e(label)}</td><td class="v">{e(val)}</td><td class="src">{e(src)}{extra}</td>'
                        f'<td class="conf" title="{e(f.get("confidence"))}">{conf_html}</td><td class="ev" title="{e(f.get("evidence"))}">{e(f.get("evidence"))}</td></tr>')
    items = ex.get("line_items") or []
    items_html = ""
    if items:
        trs = "".join(f'<tr><td>{e(li.get("description"))}</td><td class="m mut">{e(li.get("hsn"))}</td><td class="num">{qty(li.get("quantity"))}</td>'
                      f'<td class="num">{money(li.get("rate"))}</td><td class="num">{money(li.get("amount"))}</td></tr>' for li in items)
        items_html = (f'<h3 style="margin-top:14px">Line items <span style="color:var(--dim);font-weight:400">from the AI read</span></h3>'
                      f'<div class="ap-wrap"><table class="ap-table"><thead><tr><th>Description</th><th>HSN</th><th style="text-align:right">Qty</th>'
                      f'<th style="text-align:right">Rate</th><th style="text-align:right">Amount</th></tr></thead><tbody>{trs}</tbody></table></div>')
    legend = ('<p class="ap-note">Confidence: <span style="color:var(--ok)">▮▮▮</span> rules on a text layer, or rules and AI agree &nbsp; '
              '<span style="color:var(--accent)">▮▮</span> one source &nbsp; <span style="color:var(--warn)">▮</span> sources disagree</p>')
    colgroup = '<colgroup><col style="width:19%"><col style="width:33%"><col style="width:14%"><col style="width:8%"><col style="width:26%"></colgroup>'
    return f'<div class="ap-panel"><h3>Extracted fields</h3><table class="ap-ledger">{colgroup}{"".join(rows)}</table>{items_html}{legend}</div>'


# ----------------------------------------------------------------- matching + budget bar
def matching(record):
    v = record.get("vendor") or {}
    p = record.get("po") or {}
    d = record.get("decision") or {}
    status_color = STATUS.get(d.get("status"), STATUS["Not decided"])
    out = []
    vcls = "ok" if v.get("approved") else "bad"
    out.append(f'<div class="ap-panel {vcls}"><h3>Vendor</h3><div style="font-size:14px;color:var(--ink)">{e(v.get("legal_name") or "No match")}'
               f'{(" <span class=mono style=color:var(--muted)>" + e(v["vendor_id"]) + "</span>") if v.get("vendor_id") else ""}</div>'
               f'<p class="ap-line">{e(v.get("how") or v.get("summary"))}</p></div>')

    if p.get("found"):
        amt, before, this, cum = p["po_amount"], p["invoiced_before"] or 0, (p["cumulative"] or 0) - (p["invoiced_before"] or 0), p["cumulative"] or 0
        tol = float(p.get("tolerance_pct") or 2)
        scale = max(cum, amt * (1 + tol / 100)) * 1.04 or 1
        pct = lambda x: f"{max(0, min(100, x / scale * 100)):.2f}%"
        over = cum > amt
        this_color = status_color if d.get("status") else "var(--accent)"
        bar = (f'<div class="ap-budget" style="--s:{this_color}"><div class="track">'
               f'<div class="seg before" style="left:0;width:{pct(before)}"></div>'
               f'<div class="seg this" style="left:{pct(before)};width:{pct(this)}"></div>'
               f'<div class="mark" style="left:{pct(amt)}" title="PO amount"></div>'
               f'<div class="tol" style="left:{pct(amt * (1 + tol / 100))}" title="tolerance {tol:g}%"></div></div>'
               f'<div class="lbl"><span>0</span><span>PO {money(amt)}</span><span>+{tol:g}% tolerance</span></div></div>')
        variance = p.get("variance_pct")
        kv = (f'<div class="ap-kv" style="--s:{status_color}"><div><div class="l">Already invoiced</div><div class="n">{money(before)}</div></div>'
              f'<div><div class="l">This invoice</div><div class="n s">{money(this)}</div></div>'
              f'<div><div class="l">Cumulative</div><div class="n">{money(cum)}</div></div>'
              f'<div><div class="l">Variance vs PO</div><div class="n {"s" if over else ""}">{f"{variance:+.2f}%" if variance is not None else "—"}</div></div></div>')
        pcls = "ok" if (p.get("method") in ("explicit", "inferred_exact") and p.get("vendor_matches") is not False and p.get("po_status") == "open" and not (variance or 0) > tol) else "warn"
        method_label = {"explicit": "stated on invoice", "inferred_exact": "matched by exact amount, not stated", "inferred": "inferred, not stated"}.get(p.get("method"), p.get("method"))
        head = (f'<div style="font-size:14px;color:var(--ink)"><span class="mono">{e(p["po_number"])}</span> &nbsp;{e(p.get("description", ""))}'
                f' &nbsp;<span style="color:var(--muted);font-size:12px">{e(method_label)}, {e(p.get("po_status"))}</span></div>')
        out.append(f'<div class="ap-panel {pcls}"><h3>Purchase order</h3>{head}{bar}{kv}</div>')
    else:
        out.append(f'<div class="ap-panel warn"><h3>Purchase order</h3><div style="font-size:14px;color:var(--ink)">No PO matched</div><p class="ap-line">{e(p.get("summary"))}</p></div>')

    dup = record.get("duplicate") or {}
    if dup.get("is_duplicate"):
        out.append(f'<div class="ap-panel bad"><h3>Duplicate of an approved invoice</h3><p class="ap-line" style="color:var(--ink)">Matched by {e(dup["by"].replace("_", " "))} to run '
                   f'<span class="mono">{e(dup["run_id"])}</span> ({e(dup.get("filename"))}, {e((dup.get("when") or "")[:10])}), which was approved for payment.</p></div>')
    prior = record.get("prior") or {}
    if prior.get("found"):
        out.append(f'<div class="ap-panel accent"><h3>Resubmission</h3><p class="ap-line" style="color:var(--ink)">Previously <b>{e(prior.get("status"))}</b> in run '
                   f'<span class="mono">{e(prior.get("run_id"))}</span> on {e((prior.get("when") or "")[:10])}. Nothing was paid, so it is evaluated afresh; the earlier run is marked superseded.</p></div>')
    return "".join(out)


# ----------------------------------------------------------------- checks, policy, ai calls
CHECK_LABEL = {"MISSING_FIELD": "Required fields", "LINE_ITEMS_SUM": "Line items add up", "ARITHMETIC_MISMATCH": "Subtotal + GST = total",
               "GST_INCONSISTENT": "GST structure", "GSTIN_INVALID": "GSTIN format", "DATE_IMPLAUSIBLE": "Invoice date"}


def checks(record):
    rows = []
    for c in (record.get("validate") or {}).get("checks") or []:
        if c.get("skipped"):
            g, col = "–", "var(--dim)"
        elif c["ok"]:
            g, col = "✓", "var(--ok)"
        else:
            g, col = "✕", "var(--bad)"
        rows.append(f'<div class="ap-check"><span class="g" style="color:{col}">{g}</span><span class="c" title="{e(c["code"])}">{e(CHECK_LABEL.get(c["code"], c["code"]))}</span><span class="d">{e(c["detail"])}</span></div>')
    return f'<div class="ap-panel"><h3>Checks</h3>{"".join(rows) or "<p class=ap-line>No checks ran</p>"}</div>'


def policy(record):
    items = "".join(f"<li><span>{e(x)}</span></li>" for x in record.get("policy") or [])
    calls = record.get("ai_calls") or []
    call_rows = ""
    if calls:
        trs = "".join(
            f'<tr><td>{e(c.get("purpose"))}<div class="mut" style="font-size:11px">{e(c.get("mode"))} to {e(c.get("provider") or "")}</div></td>'
            f'<td class="wrap mut">{e(", ".join(c.get("requested") or []))}</td>'
            f'<td class="wrap">{e(", ".join(c.get("returned") or []) or "—")}</td>'
            f'<td class="num" style="color:{"var(--ok)" if c.get("status") == "ok" else "var(--bad)"}">{e(c.get("status"))}<div class="mut" style="font-size:11px">{e(c.get("ms"))} ms</div></td></tr>'
            for c in calls)
        call_rows = (f'<h3 style="margin-top:14px">AI calls</h3><table class="ap-table fixed"><colgroup><col style="width:24%"><col style="width:32%"><col style="width:30%"><col style="width:14%"></colgroup>'
                     f'<thead><tr><th>Purpose</th><th>Asked for</th><th>Returned</th><th style="text-align:right">Result</th></tr></thead><tbody>{trs}</tbody></table>')
    return f'<div class="ap-panel accent"><h3>How the extraction was decided</h3><ol class="ap-policy">{items}</ol>{call_rows}</div>'


# ----------------------------------------------------------------- dashboard
def kpis(runs):
    runs = [r for r in runs if not r.get("superseded_by")]
    statuses = [(r.get("decision") or {}).get("status", "Not decided") for r in runs]
    n = len(runs) or 1
    a, h, rj = statuses.count("Approve"), statuses.count("Hold"), statuses.count("Reject")
    ai = sum(r.get("ai_call_count", 0) or 0 for r in runs)
    avg = int(sum(r.get("elapsed_ms", 0) or 0 for r in runs) / n)
    tiles = [("Invoices", len(runs), "current evaluations", None),
             ("Approved", a, f"{a / n:.0%}", STATUS["Approve"]), ("On hold", h, f"{h / n:.0%}", STATUS["Hold"]),
             ("Rejected", rj, f"{rj / n:.0%}", STATUS["Reject"]), ("AI calls", ai, f"{ai / n:.1f} per invoice, {avg} ms avg", "#7AA2FF")]
    tile_html = "".join(f'<div class="ap-kpi" style="--c:{c or "var(--ink)"}"><div class="l">{e(l)}</div><div class="n">{v}</div><div class="h">{e(hh)}</div></div>' for l, v, hh, c in tiles)
    mix = (f'<div class="ap-mix"><span style="width:{a / n * 100}%;background:{STATUS["Approve"]}"></span>'
           f'<span style="width:{h / n * 100}%;background:{STATUS["Hold"]}"></span><span style="width:{rj / n * 100}%;background:{STATUS["Reject"]}"></span></div>')
    return f'<div class="ap-kpis">{tile_html}</div>{mix}'


def runs_table(rows):
    """rows: list of dicts with keys run, when, file, vendor, invoice, total, po, status, primary, codes, ai, read, ms"""
    trs = []
    for r in rows:
        sup = ' <span class="ap-pill" title="replaced by a later evaluation">superseded</span>' if r.get("superseded") else ""
        trs.append(f'<tr style="{"opacity:.55" if r.get("superseded") else ""}"><td class="m mut">{e(r["run"])}{sup}</td><td class="mut">{e(r["when"])}</td>'
                   f'<td>{e(r["file"])}</td><td>{e(r["vendor"])}</td><td class="m">{e(r["invoice"])}</td><td class="num">{e(r["total"])}</td><td class="m">{e(r["po"])}</td>'
                   f'<td>{pill(r["status"], "s-" + r["status"])}</td><td class="m mut">{e(r["primary"])}</td><td class="mut">{e(r["read"])}</td>'
                   f'<td class="num">{e(r["ai"])}</td><td class="num">{e(r["ms"])}</td></tr>')
    head = "".join(f"<th{' style=text-align:right' if h in ('Total', 'AI', 'ms') else ''}>{h}</th>" for h in
                   ["Run", "When", "File", "Vendor", "Invoice", "Total", "PO", "Decision", "Primary reason", "Read via", "AI", "ms"])
    return f'<div class="ap-wrap"><table class="ap-table"><thead><tr>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def data_table(df, numeric=()):
    cols = list(df.columns)
    head = "".join(f"<th{' style=text-align:right' if c in numeric else ''}>{e(c)}</th>" for c in cols)
    trs = []
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            val = row[c]
            if c in numeric and isinstance(val, (int, float)) and val == val:
                tds.append(f'<td class="num">{val:,.0f}</td>' if float(val).is_integer() else f'<td class="num">{val:,.2f}</td>')
            else:
                tds.append(f'<td>{e("" if val != val else val)}</td>')
        trs.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="ap-wrap"><table class="ap-table"><thead><tr>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def empty(title, body):
    return f'<div class="ap-empty"><b>{e(title)}</b>{body}</div>'
