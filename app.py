"""
Invoice to decision - AP automation console for Meridian Components Pvt Ltd.

Run locally:               streamlit run app.py
Streamlit Community Cloud: main file app.py; keys in the app's Secrets.
"""
import io
import os
import zipfile

from dotenv import load_dotenv

load_dotenv()

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)) and _k not in os.environ:
            os.environ[_k] = str(_v)
except Exception:  # noqa: BLE001
    pass

import pipeline  # noqa: E402
import ui  # noqa: E402
from pipeline import config, store, extract_ai, reference  # noqa: E402

st.set_page_config(page_title="Invoice to decision", page_icon="📄", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)

# ----------------------------------------------------------------- session state
if "pulled" not in st.session_state:
    store.pull_from_hf()
    st.session_state["pulled"] = True
if "ref_vendors" not in st.session_state:
    st.session_state["ref_vendors"] = reference.load_default_vendors()
    st.session_state["ref_pos"] = reference.load_default_pos()
    st.session_state["ref_changes"] = []
st.session_state.setdefault("results", [])  # records from this session's runs, newest first


def reference_bundle():
    return {"vendors": st.session_state["ref_vendors"], "pos": st.session_state["ref_pos"]}


def samples_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(config.SAMPLES_DIR.glob("*.pdf")):
            z.write(p, arcname=p.name)
    return buf.getvalue()


# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## Invoice to decision")
    st.caption(f"Accounts payable for {config.BUYER_NAME}")
    page = st.radio("Go to", ["Process invoices", "Dashboard", "Reference data", "How it works"], label_visibility="collapsed")
    st.divider()
    providers = extract_ai.providers_in_order()
    if providers:
        model = os.environ.get(f"{providers[0].upper()}_MODEL") or ("openai/gpt-oss-120b" if providers[0] == "groq" else "gemini-2.5-flash")
        st.caption(f"AI extractor: {providers[0]} / {model}" + (f"; fallback {providers[1]}" if len(providers) > 1 else ""))
        st.caption("Vision for very poor scans: " + ("on (Gemini)" if extract_ai.vision_available() else "off, no Gemini key"))
    else:
        st.caption("AI extractor: off (no key configured)")
    use_ai = st.toggle("Use AI for gaps", value=bool(providers), disabled=not providers,
                       help="Off: rules only. Anything the rules can't read becomes a Hold.")
    sync = store.sync_status()
    st.caption(("History mirrored to " + sync["repo"]) if sync["configured"] and not sync.get("error")
               else ("Mirror error: " + sync["error"]) if sync.get("error") else "History: local file only")
    if st.session_state["ref_changes"]:
        st.caption(f"Reference data: {len(st.session_state['ref_changes'])} change(s) this session")
    st.divider()
    if config.SAMPLES_DIR.exists():
        st.download_button("Download the 8 sample invoices", samples_zip(), "sample-invoices.zip", "application/zip", use_container_width=True)
        st.caption("Upload them on the Process page to see every path: clean, scanned, split PO, duplicate, unseen layout.")


# ----------------------------------------------------------------- shared console renderer
def render_console(record, rail_html=None):
    st.markdown(ui.verdict(record), unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.75, 1.45], gap="medium")
    with c1:
        st.markdown(rail_html or ui.rail([{"name": s["name"], "status": s["status"], "summary": s["summary"], "ms": s["ms"]} for s in record.get("stages", [])],
                                        dict(pipeline.STAGES), pipeline.STAGES), unsafe_allow_html=True)
    with c2:
        st.markdown(ui.ledger(record), unsafe_allow_html=True)
    with c3:
        st.markdown(ui.matching(record), unsafe_allow_html=True)
    c4, c5 = st.columns([1.1, 1], gap="medium")
    with c4:
        st.markdown(ui.policy(record), unsafe_allow_html=True)
    with c5:
        st.markdown(ui.checks(record), unsafe_allow_html=True)
    with st.expander("Raw text the pipeline worked from"):
        st.code(record.get("text") or "", language=None)


# ================================================================= page: process
if page == "Process invoices":
    st.markdown("# Process invoices")
    st.markdown('<p class="ap-sub">Drop one or more vendor invoice PDFs. Each one runs through the eight stages; the decision, the evidence and every AI call are shown.</p>', unsafe_allow_html=True)

    files = st.file_uploader("Invoice PDFs", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
    run_clicked = st.button("Run", type="primary", disabled=not files)

    if run_clicked and files:
        for f in files:
            data, name = f.getvalue(), f.name
            st.markdown(f"### {name}")
            verdict_slot = st.empty()
            c1, c2, c3 = st.columns([1, 1.75, 1.45], gap="medium")
            rail_slot = c1.empty()
            events, record = [], None
            rail_slot.markdown(ui.rail(events, dict(pipeline.STAGES), pipeline.STAGES), unsafe_allow_html=True)
            for ev in pipeline.run(data, name, use_ai=use_ai, reference=reference_bundle()):
                if ev["type"] == "stage":
                    events.append(ev)
                    rail_slot.markdown(ui.rail(events, dict(pipeline.STAGES), pipeline.STAGES), unsafe_allow_html=True)
                else:
                    record = ev["record"]
            if record:
                st.session_state["results"].insert(0, record)
                verdict_slot.markdown(ui.verdict(record), unsafe_allow_html=True)
                with c2:
                    st.markdown(ui.ledger(record), unsafe_allow_html=True)
                with c3:
                    st.markdown(ui.matching(record), unsafe_allow_html=True)
                c4, c5 = st.columns([1.1, 1], gap="medium")
                with c4:
                    st.markdown(ui.policy(record), unsafe_allow_html=True)
                with c5:
                    st.markdown(ui.checks(record), unsafe_allow_html=True)
                with st.expander("Raw text the pipeline worked from"):
                    st.code(record.get("text") or "", language=None)
            st.markdown("")
    elif st.session_state["results"]:
        rec = st.session_state["results"][0]
        st.caption(f"Last run this session: {rec['filename']}")
        render_console(rec)
    else:
        st.markdown(ui.empty("No invoice yet", "Upload a PDF and press Run. Need test files? Download the sample set from the sidebar."), unsafe_allow_html=True)


# ================================================================= page: dashboard
elif page == "Dashboard":
    st.markdown("# Dashboard")
    runs = store.load_all()
    if not runs:
        st.markdown(ui.empty("No runs recorded yet", "Process an invoice and it appears here with its decision, timings and AI calls. "
                             "The sample set in the sidebar covers every path in about two minutes."), unsafe_allow_html=True)
    else:
        st.markdown(ui.kpis(runs), unsafe_allow_html=True)
        rows = []
        for r in reversed(runs):
            m = (r.get("extract") or {}).get("merged") or {}
            d = r.get("decision") or {}
            rows.append({"run": r["run_id"], "when": r.get("started_at", "")[:16].replace("T", " "), "file": r.get("filename"),
                         "vendor": (r.get("vendor") or {}).get("legal_name") or (m.get("vendor_name") or {}).get("value", "—"),
                         "invoice": (m.get("invoice_number") or {}).get("value", "—"), "total": ui.money((m.get("total") or {}).get("value")),
                         "po": (r.get("po") or {}).get("po_number") or "—", "status": d.get("status", "Not decided"), "primary": d.get("primary_code", ""),
                         "codes": ", ".join(d.get("codes") or []), "ai": r.get("ai_call_count", ""), "read": (r.get("ingest") or {}).get("path", ""),
                         "ms": r.get("elapsed_ms", "")})
        df = pd.DataFrame(rows)
        f1, f2 = st.columns([1, 1.6])
        with f1:
            pick = st.multiselect("Decision", sorted(df["status"].unique()), default=sorted(df["status"].unique()))
        with f2:
            reasons = st.multiselect("Primary reason", sorted(x for x in df["primary"].unique() if x))
        view = df[df["status"].isin(pick)]
        if reasons:
            view = view[view["primary"].isin(reasons)]
        st.markdown(ui.runs_table(view.to_dict("records")), unsafe_allow_html=True)

        st.markdown("## Open a run")
        ids = list(view["run"])
        if ids:
            chosen = st.selectbox("Run", ids, label_visibility="collapsed")
            rec = next(r for r in runs if r["run_id"] == chosen)
            render_console(rec)

        with st.expander("Reset"):
            st.caption("Clears all recorded runs (and the mirror, if configured). Do this before a demo to start from a clean PO ledger.")
            if st.button("Clear history"):
                store.clear_live()
                st.session_state["results"] = []
                st.rerun()


# ================================================================= page: reference data
elif page == "Reference data":
    st.markdown("# Reference data")
    st.markdown('<p class="ap-sub">The registers that invoices are matched against. Changes here apply to this session; reload to return to the bundled data.</p>', unsafe_allow_html=True)
    tab_v, tab_p = st.tabs(["Vendors", "Purchase orders"])

    def upload_block(kind, label, key_col):
        st.markdown(f"## Add {label}")
        a, b = st.columns([1, 1], gap="large")
        with a:
            st.download_button(f"Download the {label} template (CSV)", reference.template_csv(kind), f"{kind}_template.csv", "text/csv")
            up = st.file_uploader(f"Upload a {label} CSV with the same columns", type=["csv"], key=f"up_{kind}")
            mode = st.radio("When a row has the same " + key_col + " as an existing one", ["Append (uploaded rows replace matching ids)", "Replace the whole register"],
                            key=f"mode_{kind}", label_visibility="visible")
            if up is not None:
                clean, errors, warnings, preview = reference.validate_upload(kind, up.getvalue(), st.session_state["ref_vendors"] if kind == "pos" else None)
                for w in warnings:
                    st.warning(w)
                for er in errors:
                    st.error(er)
                if preview is not None:
                    st.caption("Preview (first rows)")
                    st.markdown(ui.data_table(preview, numeric=("tolerance_pct", "po_amount", "invoiced_to_date")), unsafe_allow_html=True)
                if clean is not None and st.button(f"Add {len(clean)} row(s)", type="primary", key=f"apply_{kind}"):
                    m = "replace" if mode.startswith("Replace") else "append"
                    st.session_state[f"ref_{kind}"] = reference.merge_into(kind, st.session_state[f"ref_{kind}"], clean, m)
                    st.session_state["ref_changes"].append(f"{kind}: {m} {len(clean)} rows from {up.name}")
                    st.success(f"Added {len(clean)} row(s). The matching stage uses them from the next run.")
                    st.rerun()
        with b:
            with st.form(f"add_{kind}", clear_on_submit=True):
                st.markdown(f"**Add one {label[:-1] if label.endswith('s') else label} by hand**")
                row = {}
                if kind == "vendors":
                    row["vendor_id"] = st.text_input("vendor_id", placeholder="V101")
                    row["legal_name"] = st.text_input("legal_name", placeholder="Example Industries Pvt Ltd")
                    row["aliases"] = st.text_input("aliases (separate with |)", placeholder="Example Ind|EIPL")
                    row["gstin"] = st.text_input("gstin", placeholder="27AAACE1234F1Z5")
                    c1, c2 = st.columns(2)
                    row["state_code"] = c1.text_input("state_code", placeholder="27")
                    row["state"] = c2.text_input("state", placeholder="Maharashtra")
                    row["tolerance_pct"] = c1.text_input("tolerance_pct", value="2")
                    row["status"] = c2.selectbox("status", ["approved", "inactive", "blocked"])
                else:
                    row["po_number"] = st.text_input("po_number", placeholder="PO-2001")
                    row["vendor_id"] = st.selectbox("vendor_id", list(st.session_state["ref_vendors"]["vendor_id"]))
                    c1, c2 = st.columns(2)
                    row["po_date"] = c1.text_input("po_date (YYYY-MM-DD)", placeholder="2026-10-01")
                    row["currency"] = c2.text_input("currency", value="INR")
                    row["po_amount"] = c1.text_input("po_amount (GST-inclusive)", placeholder="118000")
                    row["invoiced_to_date"] = c2.text_input("invoiced_to_date", value="0")
                    row["status"] = c1.selectbox("status", ["open", "closed", "cancelled"])
                    row["description"] = st.text_input("description", placeholder="What the PO is for")
                if st.form_submit_button("Add row", type="primary"):
                    new_df, errors = reference.add_row(kind, st.session_state[f"ref_{kind}"], row)
                    if errors:
                        for er in errors:
                            st.error(er)
                    else:
                        st.session_state[f"ref_{kind}"] = new_df
                        st.session_state["ref_changes"].append(f"{kind}: added {row.get(key_col)}")
                        st.success(f"Added {row.get(key_col)}.")
                        st.rerun()

    with tab_v:
        v = st.session_state["ref_vendors"]
        st.markdown(f"## Approved vendors <span style='color:var(--muted);font-weight:400;font-size:14px'>{len(v)} rows</span>", unsafe_allow_html=True)
        st.markdown(ui.data_table(v, numeric=("tolerance_pct",)), unsafe_allow_html=True)
        st.markdown("")
        upload_block("vendors", "vendors", "vendor_id")

    with tab_p:
        p = st.session_state["ref_pos"].copy()
        ledger = store.po_ledger()
        p["approved_here"] = p["po_number"].map(lambda x: ledger.get(x, 0.0))
        p["remaining"] = p["po_amount"] - p["invoiced_to_date"] - p["approved_here"]
        st.markdown(f"## Purchase orders <span style='color:var(--muted);font-weight:400;font-size:14px'>{len(p)} rows</span>", unsafe_allow_html=True)
        st.markdown(ui.data_table(p, numeric=("po_amount", "invoiced_to_date", "approved_here", "remaining")), unsafe_allow_html=True)
        st.caption("PO amounts are GST-inclusive. approved_here is what this system approved in live runs; remaining is what the next invoice can draw on.")
        st.markdown("")
        upload_block("pos", "purchase orders", "po_number")

    st.divider()
    if st.button("Reset to the bundled registers"):
        st.session_state["ref_vendors"] = reference.load_default_vendors()
        st.session_state["ref_pos"] = reference.load_default_pos()
        st.session_state["ref_changes"] = []
        st.rerun()


# ================================================================= page: how it works
else:
    st.markdown("# How it works")
    st.markdown(f"""
One invoice in, one decision out, every step visible. Rules do the work wherever they can; a language model is called only to fill a gap the rules left, and never to make the decision.

| Stage | What happens | Model? |
|---|---|---|
| 1 Read | Text layer if the PDF has one; otherwise Tesseract OCR, which also reports a confidence score | No |
| 2 Identify | Vendor name, GSTIN, invoice number, date, PO reference. Rules first; AI asked only for what the rules missed | Only for gaps |
| 3 Match vendor | GSTIN exact match, then fuzzy legal name with aliases, against the vendor register | No |
| 4 Match PO | Stated PO looked up; if none stated, inferred only when exactly one open PO fits | No |
| 5 Amounts | Subtotal, GST lines, total. Rules first; AI asked for gaps only if the vendor or the PO matched the reference data | Only for gaps, only if worth it |
| 6 Check | Line items sum to subtotal; subtotal + GST = total; CGST/SGST vs IGST consistent with the vendor's state; GSTIN format; date sanity; required fields | No |
| 7 Decide | Ordered rules; first match sets the outcome; every failure listed; next action in plain words | No |
| 8 Record | History with timings; mirrored to a private dataset so it survives host restarts | No |

**The AI hierarchy, exactly as the pipeline applies it**

1. Text PDF, or a scan with OCR confidence at or above {config.OCR_AI_THRESHOLD:g}%: the text is trusted. Rules run first on identity fields. If vendor name, PO reference, invoice number or date is missing, one AI call asks for exactly those. A missing GSTIN alone does not trigger a call.
2. Vendor and PO are matched against the reference data before any money is read.
3. Amounts: rules first. If a gap remains and at least one of vendor or PO matched, one AI call asks for the amounts and line items. If neither matched, no AI is spent: the rules' amounts are shown, and the decision will be Reject or Hold on identity grounds anyway.
4. Scan with OCR confidence below {config.OCR_AI_THRESHOLD:g}%: the OCR text itself is suspect, so the AI reads the whole document once, at the identify stage, and the rules cross-check it. Where they disagree the AI value is kept, confidence is marked low, and the decision rules turn a low-confidence required field into a Hold.
5. Scan below {config.OCR_VISION_THRESHOLD:g}% with a Gemini key configured: the page image goes to a vision model instead of the OCR text.
6. AI unavailable at any point (quota, outage, no key): the stage continues on rules alone and says so. Gaps become Holds with a specific next action; nothing crashes and nothing is silently approved.

Most clean invoices make zero AI calls. The worst case is two.

**Decision order.** Duplicate → Reject. Unapproved vendor → Reject. Missing required field, arithmetic or GST inconsistency, bad GSTIN → Hold. No PO, PO for another vendor, closed PO, inferred PO → Hold. Over tolerance (cumulative vs PO) → Hold. Extractors disagree on a required field → Hold. Otherwise Approve, annotated exact / within tolerance / partial delivery.

**Assumptions.** One invoice per PDF. PO amounts are GST-inclusive. Tolerance is a per-vendor attribute. A duplicate is the same vendor and invoice number regardless of amount, or the same file. Holds and rejects don't consume PO budget; approvals do. Reference data uploaded in the app applies to the current session.
""")
