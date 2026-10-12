"""
Invoice to decision - AP automation for Meridian Components Pvt Ltd.

Run locally:   streamlit run app.py
On HF Spaces:  this file is the entry point (SDK: streamlit).
"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

import pipeline
from pipeline import config, store

st.set_page_config(page_title="Invoice to decision", page_icon="📄", layout="wide")

STAGE_LABELS = dict(pipeline.STAGES)
STATUS_ICON = {"ok": "✅", "warn": "⚠️", "failed": "❌", "skipped": "⏭️", "running": "⏳"}
DECISION_COLOR = {"Approve": "green", "Hold": "orange", "Reject": "red", "Not decided": "gray"}


def money(x):
    if isinstance(x, (int, float)):
        return f"₹{x:,.2f}"
    return "—" if x in (None, "") else str(x)


# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("Invoice to decision")
    st.caption(f"Buyer: {config.BUYER_NAME}")
    page = st.radio("Go to", ["Process an invoice", "Dashboard", "Reference data"], label_visibility="collapsed")
    st.divider()
    st.caption("Pipeline: read → extract → check → match vendor → match PO → decide → record. "
               "AI is used in one stage only (extraction); every decision is a rule you can read.")
    ai_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY")
    st.caption(("AI extractor key detected" if ai_key else "No AI key set; extraction runs on rules only") + " · model wiring lands on day 2")


# ----------------------------------------------------------------- helpers
def render_stage_log(container, events):
    """events: list of stage dicts, in order. Rerenders the full list."""
    lines = []
    for ev in events:
        icon = STATUS_ICON.get(ev["status"], "•")
        ms = f"{ev['ms']} ms" if ev.get("ms") is not None else ""
        lines.append(f"{icon} **{STAGE_LABELS.get(ev['name'], ev['name'])}** · {ev['summary']}  <span style='color:#888'>{ms}</span>")
    container.markdown("<br>".join(lines) if lines else "_Waiting to start_", unsafe_allow_html=True)


def render_decision(record):
    d = record.get("decision") or {}
    status = d.get("status", "Not decided")
    color = DECISION_COLOR.get(status, "gray")
    st.markdown(f"### :{color}[{status}]")
    if d.get("codes"):
        st.markdown(" ".join(f"`{c}`" for c in d["codes"]))
    if d.get("next_action"):
        st.info(d["next_action"])


def render_fields(record):
    merged = (record.get("extract") or {}).get("merged") or {}
    rows = []
    for key in config.FIELDS:
        f = merged.get(key)
        rows.append({
            "Field": key.replace("_", " "),
            "Value": money(f["value"]) if (f and key in config.AMOUNT_FIELDS) else (f["value"] if f else "—"),
            "Source": f["source"] if f else "not found",
            "Confidence": f["confidence"] if f else "",
            "Evidence": (f.get("evidence") or "")[:80] if f else "",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_checks(record):
    checks = (record.get("validate") or {}).get("checks") or []
    for c in checks:
        icon = "✅" if c["ok"] else "❌"
        if c.get("skipped"):
            icon = "➖"
        st.markdown(f"{icon} `{c['code']}` {c['detail']}")


def render_run_detail(record):
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Extracted fields")
        render_fields(record)
    with right:
        st.subheader("Checks")
        render_checks(record)
        ing = record.get("ingest") or {}
        st.caption(f"Read via {ing.get('path', '?')} · {ing.get('pages', '?')} page(s) · file hash {ing.get('file_hash', '?')}"
                   + (f" · OCR confidence {ing['ocr_confidence']}%" if ing.get("ocr_confidence") is not None else ""))
    with st.expander("Raw text the pipeline worked from"):
        st.text(record.get("text") or "")
    with st.expander("Stage timings"):
        st.dataframe(pd.DataFrame(record.get("stages", [])), hide_index=True, use_container_width=True)


# ----------------------------------------------------------------- page: process
if page == "Process an invoice":
    st.header("Process an invoice")
    st.caption("Upload a vendor invoice PDF, or pick one of the bundled samples. Each stage reports as it finishes.")

    samples = sorted(p.name for p in config.SAMPLES_DIR.glob("*.pdf")) if config.SAMPLES_DIR.exists() else []
    c1, c2 = st.columns([1, 1])
    with c1:
        uploaded = st.file_uploader("Upload a PDF", type=["pdf"])
    with c2:
        sample = st.selectbox("…or pick a sample", ["(none)"] + samples)

    go = st.button("Run", type="primary", disabled=not (uploaded or sample != "(none)"))

    if go:
        if uploaded:
            data, name = uploaded.getvalue(), uploaded.name
        else:
            data, name = (config.SAMPLES_DIR / sample).read_bytes(), sample

        st.subheader(f"Run log · {name}")
        log_box = st.empty()
        events, record = [], None
        with st.spinner("Running…"):
            for ev in pipeline.run(data, name):
                if ev["type"] == "stage":
                    events.append(ev)
                    render_stage_log(log_box, events)
                elif ev["type"] == "done":
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
        statuses = [(r.get("decision") or {}).get("status", "Not decided") for r in runs]
        cols = st.columns(5)
        cols[0].metric("Runs", len(runs))
        for i, s in enumerate(["Approve", "Hold", "Reject", "Not decided"], start=1):
            cols[i].metric(s, statuses.count(s))

        rows = []
        for r in reversed(runs):
            m = (r.get("extract") or {}).get("merged") or {}
            d = r.get("decision") or {}
            rows.append({
                "Run": r["run_id"],
                "When": r.get("started_at", "")[:19].replace("T", " "),
                "File": r.get("filename"),
                "Vendor": (m.get("vendor_name") or {}).get("value", "—"),
                "Invoice #": (m.get("invoice_number") or {}).get("value", "—"),
                "Total": money((m.get("total") or {}).get("value")),
                "PO": (m.get("po_reference") or {}).get("value", "—"),
                "Decision": d.get("status", "Not decided"),
                "Codes": ", ".join(d.get("codes") or []),
                "Read via": (r.get("ingest") or {}).get("path", ""),
                "ms": r.get("elapsed_ms"),
            })
        df = pd.DataFrame(rows)
        f1, f2 = st.columns([1, 3])
        with f1:
            pick = st.multiselect("Decision", sorted(df["Decision"].unique()), default=list(sorted(df["Decision"].unique())))
        df = df[df["Decision"].isin(pick)]
        st.dataframe(df, hide_index=True, use_container_width=True)

        st.subheader("Open a run")
        chosen = st.selectbox("Run id", [r["run_id"] for r in reversed(runs)])
        rec = next(r for r in runs if r["run_id"] == chosen)
        render_decision(rec)
        render_run_detail(rec)

        with st.expander("Danger zone"):
            if st.button("Clear local history"):
                store.clear()
                st.rerun()


# ----------------------------------------------------------------- page: reference
else:
    st.header("Reference data")
    st.caption("What the matching stage checks invoices against. Edit the CSVs in data/ to change the world.")
    st.subheader("Approved vendors")
    st.dataframe(pd.read_csv(config.DATA_DIR / "vendors.csv"), hide_index=True, use_container_width=True)
    st.subheader("Purchase orders")
    po = pd.read_csv(config.DATA_DIR / "purchase_orders.csv")
    po["remaining"] = po["po_amount"] - po["invoiced_to_date"]
    st.dataframe(po, hide_index=True, use_container_width=True)
    st.caption("Assumption: PO amounts are GST-inclusive, so invoice totals compare directly.")
