"""
Invoice to decision - AP automation for Meridian Components Pvt Ltd.

Run locally:            streamlit run app.py
Streamlit Community Cloud: main file app.py; put keys in the app's Secrets.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # local .env; harmless on the cloud

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

# Streamlit secrets -> environment, so the pipeline reads one place.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)) and _k not in os.environ:
            os.environ[_k] = str(_v)
except Exception:  # noqa: BLE001 - no secrets file locally
    pass

import pipeline  # noqa: E402
from pipeline import config, store, extract_ai  # noqa: E402

st.set_page_config(page_title="Invoice to decision", page_icon="📄", layout="wide")

if "pulled" not in st.session_state:
    store.pull_from_hf()
    st.session_state["pulled"] = True

STAGE_LABELS = dict(pipeline.STAGES)
STATUS_ICON = {"ok": "✅", "warn": "⚠️", "failed": "❌", "skipped": "⏭️"}
DECISION_COLOR = {"Approve": "green", "Hold": "orange", "Reject": "red", "Not decided": "gray"}
SOURCE_LABEL = {"both": "rules + AI agree", "rules": "rules", "ai": "AI", "not found": "not found"}


def money(x):
    if isinstance(x, (int, float)):
        return f"₹{x:,.2f}"
    return "—" if x in (None, "") else str(x)


# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("Invoice to decision")
    st.caption(f"Buyer: {config.BUYER_NAME}")
    page = st.radio("Go to", ["Process an invoice", "Dashboard", "Reference data", "How it works"], label_visibility="collapsed")
    st.divider()
    providers = extract_ai.providers_in_order()
    if providers:
        model = os.environ.get(f"{providers[0].upper()}_MODEL") or ("openai/gpt-oss-120b" if providers[0] == "groq" else "gemini-2.5-flash")
        st.caption(f"AI extractor: **{providers[0]}** · {model}" + (f" · fallback {providers[1]}" if len(providers) > 1 else ""))
    else:
        st.caption("AI extractor: **off** (no key configured). Extraction runs on rules only.")
    use_ai = st.toggle("Use AI extractor", value=bool(providers), disabled=not providers,
                       help="Turn off to demonstrate the rules-only fallback.")
    sync = store.sync_status()
    if sync["configured"]:
        st.caption(("History mirrored to HF dataset " + sync["repo"]) if not sync.get("error") else f"History mirror error: {sync['error']}")
    else:
        st.caption("History: local file only (set HF_TOKEN and HF_DATASET_REPO to mirror it)")


# ----------------------------------------------------------------- render helpers
def render_stage_log(container, events):
    lines = []
    for ev in events:
        icon = STATUS_ICON.get(ev["status"], "•")
        lines.append(f"{icon} **{STAGE_LABELS.get(ev['name'], ev['name'])}** · {ev['summary']} "
                     f"<span style='color:#888'>{ev.get('ms', '')} ms</span>")
    container.markdown("<br>".join(lines) if lines else "_Waiting to start_", unsafe_allow_html=True)


def render_decision(record):
    d = record.get("decision") or {}
    status = d.get("status", "Not decided")
    color = DECISION_COLOR.get(status, "gray")
    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown(f"## :{color}[{status}]")
        if d.get("codes"):
            st.markdown(" ".join(f"`{c}`" for c in d["codes"]))
    with c2:
        if d.get("next_action"):
            {"Approve": st.success, "Hold": st.warning, "Reject": st.error}.get(status, st.info)(d["next_action"])
        for line in (d.get("explanation") or [])[:2]:
            st.caption(line)


def render_fields(record):
    ex = record.get("extract") or {}
    merged = ex.get("merged") or {}
    rows = []
    for key in config.FIELDS:
        f = merged.get(key)
        if f and f.get("conflict"):
            src = f"conflict, kept {f['source']} (rules {f['conflict']['rules']} vs AI {f['conflict']['ai']})"
        else:
            src = SOURCE_LABEL.get(f["source"], f["source"]) if f else "not found"
        rows.append({
            "Field": key.replace("_", " "),
            "Value": money(f["value"]) if (f and key in config.AMOUNT_FIELDS) else (f["value"] if f else "—"),
            "Source": src,
            "Confidence": f["confidence"] if f else "",
            "Read from": (f.get("evidence") or "")[:70] if f else "",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    ai_status = ex.get("ai_status")
    if ai_status == "ok":
        st.caption(f"AI extractor: {ex.get('ai_provider')} · {ex.get('ai_model')} · {ex.get('ai_ms')} ms")
    elif ai_status:
        st.caption(f"AI extractor unavailable: {ex.get('ai_error')}. Rules carried the extraction.")
    if ex.get("line_items"):
        with st.expander(f"Line items ({len(ex['line_items'])}, from the AI extractor)"):
            st.dataframe(pd.DataFrame(ex["line_items"]), hide_index=True, use_container_width=True)


def render_checks(record):
    for c in (record.get("validate") or {}).get("checks") or []:
        icon = "➖" if c.get("skipped") else ("✅" if c["ok"] else "❌")
        st.markdown(f"{icon} `{c['code']}` {c['detail']}")


def render_matching(record):
    v = record.get("vendor") or {}
    p = record.get("po") or {}
    st.markdown(("✅" if v.get("approved") else "⚠️") + " **Vendor** · " + (v.get("summary") or "—"))
    if p.get("found"):
        ok = p.get("method") == "explicit" and p.get("vendor_matches") is not False and p.get("po_status") == "open"
        st.markdown(("✅" if ok else "⚠️") + f" **PO {p['po_number']}** · {p.get('description', '')} · {p.get('method')} · status {p.get('po_status')}")
        a, b, c, d = st.columns(4)
        a.metric("PO amount", money(p["po_amount"]))
        b.metric("Already invoiced", money(p["invoiced_before"]))
        c.metric("Cumulative after this", money(p["cumulative"]))
        d.metric("Variance vs PO", f"{p['variance_pct']:+.2f}%" if p.get("variance_pct") is not None else "—",
                 help=f"Tolerance for this vendor: {p.get('tolerance_pct', 2):g}%")
    else:
        st.markdown("⚠️ **PO** · " + (p.get("summary") or "—"))
    dup = record.get("duplicate") or {}
    if dup.get("is_duplicate"):
        st.markdown(f"❌ **Duplicate** · matched by {dup['by']} to run {dup['run_id']} ({dup.get('filename')})")


def render_run_detail(record):
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Extracted fields")
        render_fields(record)
    with right:
        st.subheader("Matching")
        render_matching(record)
        st.subheader("Checks")
        render_checks(record)
    ing = record.get("ingest") or {}
    st.caption(f"Read via {ing.get('path', '?')} · {ing.get('pages', '?')} page(s) · file hash {ing.get('file_hash', '?')}"
               + (f" · OCR confidence {ing['ocr_confidence']}%" if ing.get("ocr_confidence") is not None else "")
               + f" · {record.get('elapsed_ms', '?')} ms end to end")
    with st.expander("Raw text the pipeline worked from"):
        st.text(record.get("text") or "")
    with st.expander("Stage timings"):
        st.dataframe(pd.DataFrame(record.get("stages", [])), hide_index=True, use_container_width=True)


# ----------------------------------------------------------------- page: process
if page == "Process an invoice":
    st.header("Process an invoice")
    st.caption("Upload a vendor invoice PDF, or pick a bundled sample. Each stage reports as it finishes; the decision and its evidence follow.")

    samples = sorted(p.name for p in config.SAMPLES_DIR.glob("*.pdf")) if config.SAMPLES_DIR.exists() else []
    c1, c2 = st.columns(2)
    with c1:
        uploaded = st.file_uploader("Upload a PDF", type=["pdf"])
    with c2:
        sample = st.selectbox("…or pick a sample", ["(none)"] + samples)

    if st.button("Run", type="primary", disabled=not (uploaded or sample != "(none)")):
        data, name = (uploaded.getvalue(), uploaded.name) if uploaded else ((config.SAMPLES_DIR / sample).read_bytes(), sample)
        st.subheader(f"Run log · {name}")
        log_box = st.empty()
        events, record = [], None
        with st.spinner("Running…"):
            for ev in pipeline.run(data, name, use_ai=use_ai):
                if ev["type"] == "stage":
                    events.append(ev)
                    render_stage_log(log_box, events)
                else:
                    record = ev["record"]
        if record:
            st.session_state["last_record"] = record
            st.divider()
            render_decision(record)
            render_run_detail(record)
    elif "last_record" in st.session_state:
        rec = st.session_state["last_record"]
        st.caption(f"Showing the last run · {rec['filename']}")
        render_decision(rec)
        render_run_detail(rec)


# ----------------------------------------------------------------- page: dashboard
elif page == "Dashboard":
    st.header("Dashboard")
    runs = store.load_all()
    if not runs:
        st.info("No runs yet. Process an invoice and it will appear here.")
    else:
        live = [r for r in runs if not r.get("seed")]
        statuses = [(r.get("decision") or {}).get("status", "Not decided") for r in runs]
        cols = st.columns(5)
        cols[0].metric("Runs", len(runs), help=f"{len(live)} live, {len(runs) - len(live)} seeded demo runs")
        for i, s in enumerate(["Approve", "Hold", "Reject"], start=1):
            cols[i].metric(s, statuses.count(s))
        cols[4].metric("Avg time", f"{int(sum(r.get('elapsed_ms', 0) for r in runs) / len(runs))} ms")

        rows = []
        for r in reversed(runs):
            m = (r.get("extract") or {}).get("merged") or {}
            d = r.get("decision") or {}
            rows.append({
                "Run": r["run_id"] + (" (seed)" if r.get("seed") else ""),
                "When": r.get("started_at", "")[:16].replace("T", " "),
                "File": r.get("filename"),
                "Vendor": (r.get("vendor") or {}).get("legal_name") or (m.get("vendor_name") or {}).get("value", "—"),
                "Invoice #": (m.get("invoice_number") or {}).get("value", "—"),
                "Total": money((m.get("total") or {}).get("value")),
                "PO": (r.get("po") or {}).get("po_number") or "—",
                "Decision": d.get("status", "Not decided"),
                "Primary reason": d.get("primary_code", ""),
                "All codes": ", ".join(d.get("codes") or []),
                "AI": (r.get("extract") or {}).get("ai_status", ""),
                "Read via": (r.get("ingest") or {}).get("path", ""),
                "ms": r.get("elapsed_ms"),
            })
        df = pd.DataFrame(rows)
        f1, f2 = st.columns([1, 2])
        with f1:
            pick = st.multiselect("Decision", sorted(df["Decision"].unique()), default=sorted(df["Decision"].unique()))
        with f2:
            reason = st.multiselect("Primary reason", sorted(x for x in df["Primary reason"].unique() if x))
        view = df[df["Decision"].isin(pick)]
        if reason:
            view = view[view["Primary reason"].isin(reason)]
        st.dataframe(view, hide_index=True, use_container_width=True)

        st.subheader("Open a run")
        ids = [r["run_id"] for r in reversed(runs)]
        chosen = st.selectbox("Run id", ids)
        rec = next(r for r in runs if r["run_id"] == chosen)
        if rec.get("seed"):
            st.caption("Seeded demo run: shown for history, excluded from duplicate checks and the PO ledger.")
        render_decision(rec)
        render_run_detail(rec)

        with st.expander("Reset"):
            st.caption("Clears live runs (and the mirror, if configured). Seeded demo runs stay. Use this before a demo to start from a clean PO ledger.")
            if st.button("Clear live history"):
                store.clear_live()
                st.session_state.pop("last_record", None)
                st.rerun()


# ----------------------------------------------------------------- page: reference
elif page == "Reference data":
    st.header("Reference data")
    st.caption("What the matching stage checks invoices against. Edit the CSVs in data/ to change the world.")
    st.subheader("Approved vendors")
    st.dataframe(pd.read_csv(config.DATA_DIR / "vendors.csv"), hide_index=True, use_container_width=True)
    st.subheader("Purchase orders")
    po = pd.read_csv(config.DATA_DIR / "purchase_orders.csv")
    ledger = store.po_ledger()
    po["approved_here"] = po["po_number"].map(lambda p: ledger.get(p, 0.0))
    po["remaining"] = po["po_amount"] - po["invoiced_to_date"] - po["approved_here"]
    st.dataframe(po, hide_index=True, use_container_width=True)
    st.caption("PO amounts are GST-inclusive, so invoice totals compare directly. 'approved_here' is what this system has approved in live runs.")


# ----------------------------------------------------------------- page: how it works
else:
    st.header("How it works")
    st.markdown("""
**One invoice in, one decision out, every step visible.**

| Stage | What happens | Uses a model? |
|---|---|---|
| 1 Read | Text layer if the PDF has one; otherwise Tesseract OCR | No |
| 2 Extract | Regex rules and the AI extractor read the text side by side, then merge: agree → high confidence, one source → medium, disagree → low and flagged | **Yes, here only** |
| 3 Check | Line items sum to subtotal; subtotal + GST = total; CGST/SGST vs IGST consistent with the vendor's state; GSTIN format; date sanity; required fields | No |
| 4 Vendor | GSTIN exact match, else fuzzy name with aliases, against the approved list | No |
| 5 PO | Stated PO looked up; if none stated, inferred only when exactly one open PO fits. Cumulative = already invoiced + approved here + this invoice | No |
| 6 Decide | Ordered rules; first match sets the outcome, all failures listed, next action in plain words | No |
| 7 Record | History with timings; mirrored to a private dataset so it survives restarts | No |

**Why the model is only in stage 2.** Vendors format invoices however they like, so pattern rules break on a layout they haven't seen; a language model reads a new layout fine. But a model can also misread, so its output is treated as a candidate: checked against the rules, checked against arithmetic, and never allowed to make the payment decision. Decisions about money must come out the same way every time and be readable by the person who owns them.

**Decision order.** Duplicate → Reject. Unapproved vendor → Reject. Missing required field, arithmetic or GST inconsistency, bad GSTIN → Hold. No PO, PO for another vendor, closed PO, inferred PO → Hold. Over tolerance (cumulative vs PO) → Hold. Extractors disagree on a required field → Hold. Otherwise Approve, annotated exact / within tolerance / partial delivery.

**If the AI is unavailable** (quota, outage, no key) the pipeline continues on rules alone and says so. Anything the rules can't read becomes a Hold with a specific next action, never a crash and never a silent approval.

**Assumptions.** One invoice per PDF. PO amounts are GST-inclusive. Tolerance is a vendor attribute set by procurement. A duplicate is the same vendor and invoice number regardless of amount, or the same file. Holds and rejects don't consume PO budget; approvals do.
""")
