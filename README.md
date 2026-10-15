# Invoice to decision

An accounts-payable process for **Meridian Components Pvt Ltd** (a fictional Pune manufacturer). A vendor invoice PDF goes in; a reasoned decision comes out: **Approve**, **Hold** (with what's needed), or **Reject**. Every stage is visible as it runs, and every past run is on the dashboard.

Built for Zamp's AI Solutions Associate case study, problem statement PS-1.

**Live app:** _your Streamlit URL here_ · **Demo video:** _your Loom link here_

---

## The problem

Hundreds of vendor invoices a month, all PDFs, all different. Someone opens each one, finds the matching purchase order, checks the numbers, decides. It's slow, repetitive, and the kind of work where a tired person on a Friday makes an expensive mistake: pays a duplicate, pays over the PO, pays a vendor who was never approved.

## What this does

```
PDF ─► Read ─► Identify ─► Match vendor ─► Match PO ─► Amounts ─► Check ─► Decide ─► Record
        │         │              │              │           │          │         │
     text or   rules, AI     GSTIN, then    stated or   rules, AI   arithmetic  ordered rules,
     OCR +     for gaps      fuzzy name     inferred;   for gaps    GST, GSTIN  first match wins,
     confidence              + aliases      cumulative  if matched  dates       plain next action
```

| Stage | What happens | Model? |
|---|---|---|
| 1 Read | Text layer via pdfplumber; if none, Tesseract OCR | No |
| 2 Identify | Vendor, GSTIN, invoice number, date, PO reference. Rules first; AI asked only for what the rules missed | Only for gaps |
| 3 Vendor | Exact GSTIN match, else fuzzy legal-name match with aliases, against the approved-vendor register | No |
| 4 PO | Stated PO looked up; if none stated, inferred only when exactly one open PO fits. Cumulative = already invoiced + approved here + this invoice | No |
| 5 Amounts | Subtotal, GST lines, total, line items. Rules first; AI asked for gaps only if vendor or PO matched | Only for gaps, only if worth it |
| 6 Check | Line items sum to subtotal; subtotal + GST = total; CGST/SGST vs IGST consistent with the vendor's state; GSTIN format; date sanity; required fields present | No |
| 7 Decide | Ordered rules (below). First match sets the outcome; all failures are listed; next action in plain words | No |
| 8 Record | Run history with per-stage timings; optionally mirrored to a private Hugging Face Dataset so it survives host restarts | No |

### The AI hierarchy

Rules first, AI only for gaps. In order:

1. **Read.** Text layer, or OCR with a confidence score.
2. **Identify** (vendor name, GSTIN, invoice number, date, PO reference). Rules first. If vendor name, PO reference, invoice number or date is missing, one AI call asks for exactly those fields. A missing GSTIN alone does not trigger a call.
3. **Match vendor and PO** against the reference data, before any money is read.
4. **Amounts** (subtotal, GST lines, total, line items). Rules first. If a gap remains **and** at least one of vendor or PO matched, one AI call asks for the amounts. If neither matched, no AI is spent: the rules' amounts are shown and the decision will be Reject or Hold on identity grounds anyway.
5. **Poor scan** (OCR confidence below 90%): the OCR text itself is suspect, so the AI reads the whole document once at the identify stage. With a Gemini key the page image goes to Gemini Flash vision; otherwise, or if that call fails, the OCR text goes to the text model. Rules from the OCR text cross-check the result: disagreements keep the AI value, drop confidence to low, and a low-confidence required field becomes a Hold.
6. **AI unavailable** at any point: the stage continues on rules alone and says so. Gaps become Holds with a specific next action.

Most clean invoices make zero AI calls; the worst case is two. Every call is listed on the run with what it asked for and what came back.

### Why the model never decides

Vendors format invoices however they like. Pattern rules work on layouts you've seen and break on the next one; a language model reads a new layout fine. But a model can also misread, so its output is treated as a *candidate*: cross-checked against the rules, checked by arithmetic, and never allowed to make the payment decision. A decision about money has to come out the same way every time and be readable by the person who owns it. If the model is unavailable (quota, outage, no key), the pipeline continues on rules alone and says so; anything the rules can't read becomes a Hold with a specific next action, never a crash and never a silent approval.

### Decision rules, in order

| # | Condition | Outcome | Code |
|---|---|---|---|
| 1 | Same vendor + invoice number (or same file) was already **approved** | Reject | `DUPLICATE_INVOICE` |
| 2 | Vendor not in the approved register (or inactive) | Reject | `VENDOR_NOT_APPROVED` |
| 3 | A required field is missing (vendor, invoice number, date, total) | Hold | `MISSING_FIELD` |
| 4 | Arithmetic, GST structure or date check failed | Hold | `ARITHMETIC_MISMATCH` / `GST_INCONSISTENT` / `DATE_IMPLAUSIBLE` |
| 5 | GSTIN malformed | Hold | `GSTIN_INVALID` |
| 6 | No PO stated and none inferable | Hold | `PO_NOT_FOUND` |
| 7 | Stated PO belongs to another vendor | Hold | `PO_VENDOR_MISMATCH` |
| 8 | Stated PO is closed | Hold | `PO_CLOSED` |
| 9 | PO not stated and inferred only approximately (an exact single match approves, annotated `PO_MATCHED_BY_AMOUNT`) | Hold | `PO_INFERRED` |
| 10 | Cumulative invoicing exceeds PO beyond tolerance, earlier invoices exist | Hold | `CUMULATIVE_EXCEEDS_PO` |
| 11 | First invoice on the PO exceeds it beyond tolerance | Hold | `OUTSIDE_TOLERANCE` |
| 12 | Extractors disagreed on a required field | Hold | `LOW_CONFIDENCE` |
| — | Otherwise | Approve | `EXACT_MATCH` / `WITHIN_TOLERANCE` / `PARTIAL_DELIVERY` (+ `SPLIT_FINAL`, `PO_MATCHED_BY_AMOUNT`, `RESUBMISSION` annotations) |

Tolerance is a per-vendor attribute in `vendors.csv` (default 2%).

## The test set

Fourteen generated invoices in four different layouts; one is an image-only scan.

| Invoice | Scenario | Expected |
|---|---|---|
| inv01 | Clean, explicit PO, exact amount | Approve · `EXACT_MATCH` |
| inv02 | 1.5% over PO, tolerance 2% | Approve · `WITHIN_TOLERANCE` |
| inv03 | 3% over PO, tolerance 2% | Hold · `OUTSIDE_TOLERANCE` |
| inv04 | **Scanned**, invoice number missing; OCR also mangles the GSTIN | Hold · `MISSING_FIELD`, `GSTIN_INVALID` |
| inv05 | First of two against a PO already 60% consumed | Approve · `PARTIAL_DELIVERY` |
| inv06 | Second against the same PO; cumulative exceeds it | Hold · `CUMULATIVE_EXCEEDS_PO` |
| inv07 | inv01 reissued under a new filename | Reject · `DUPLICATE_INVOICE` |
| inv08 | **Unseen layout**: labels no rule covers, bundled line item, lakh digit grouping | Approve; rules find 3 fields, AI fills the rest (2 calls) |
| inv09, inv10 | One PO billed in two invoices | `PARTIAL_DELIVERY`, then `EXACT_MATCH` + `SPLIT_FINAL` |
| inv11–13 | One PO billed in three invoices | partial, partial, `SPLIT_FINAL` |
| inv14 | No PO number; exactly one open PO equals the amount | Approve · `PO_MATCHED_BY_AMOUNT` |

Run inv08 with the AI toggle off to see the fallback: Hold · `MISSING_FIELD`, "AI unavailable" in the log. Across the fourteen, the pipeline makes three AI calls in total: two for the unseen layout, one for the poor scan, none for the other twelve.

**Resubmissions.** Only an *approved* invoice counts as a duplicate. A held or rejected invoice uploaded again is re-evaluated (so "raise the PO, resubmit, approve" works) and the earlier run is marked superseded on the dashboard. A rejected vendor-not-approved invoice resubmitted unchanged is rejected again for the same reason, tagged `RESUBMISSION`.

Reference data can be extended from the app: upload a CSV in the bundled format (templates downloadable in the UI, validated column by column) or add a single vendor or PO by hand. Changes apply to the current session.

## Run it

```
# system tools: tesseract-ocr, poppler-utils (brew / apt / Windows installers)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add GROQ_API_KEY; GROQ_MODEL=openai/gpt-oss-120b
streamlit run app.py
```

Regenerate the sample invoices with `python tools/make_invoices.py`.

Deployed on Streamlit Community Cloud (`packages.txt` installs Tesseract and Poppler; keys live in the app's Secrets).

## Layout

```
app.py                   Streamlit UI: Process, Dashboard, Reference data
ui.py                    design tokens, CSS and HTML renderers for the console
.streamlit/config.toml   theme
pipeline/
  ingest.py              text layer or OCR (with confidence and page image)
  extract_rules.py       regex extraction
  extract_ai.py          targeted LLM extraction (Groq text; Gemini text or vision), graceful "unavailable"
  merge.py               fill gaps from AI, or reconcile a full AI read of a poor scan
  reference.py           vendor/PO registers: templates, upload validation, append/replace, add-row
  validate.py            arithmetic, GST, GSTIN, dates, required fields
  match.py               vendor and PO matching
  decide.py              ordered rules, codes, next action
  store.py               run history, PO ledger, duplicate index, HF mirror, seed runs
  config.py              buyer identity, field list, thresholds
data/
  vendors.csv            approved vendors, aliases, GSTIN, tolerance
  purchase_orders.csv    PO register with invoiced-to-date
  samples/               the fourteen test PDFs
docs/
  Invoice-to-Decision_Coverage.xlsx
tools/
  make_invoices.py       generates the fourteen PDFs
  make_docs_xlsx.py      generates the coverage workbook
```

## Assumptions

One invoice per PDF. PO amounts are GST-inclusive, so invoice totals compare directly. Tolerance is set by procurement per vendor. A duplicate is a previously approved invoice with the same vendor and invoice number, or the same file. Holds and rejects do not consume PO budget; approvals do. A PO is approved without being stated only on an exact single-amount match.

## Documentation

`docs/Invoice-to-Decision_Coverage.xlsx`: pipeline stages, decision rules, the 20 test scenarios, 78 edge cases from the customer's point of view with coverage status and next steps, AI policy, reference schema, assumptions, code glossary.

## What I'd build next

1. **Email ingestion.** Poll a mailbox, pull PDF attachments, run them, reply to the vendor automatically on Hold with the next-action text.
2. **Multi-page and multi-invoice PDFs.** Split by invoice-number boundaries before extraction.
3. **Vendor-level format memory.** When a human corrects a field, store the correction keyed by vendor; the rules extractor learns that vendor's labels and the model is needed less over time.
4. **Human actions in the app.** Approve-anyway and reject-anyway buttons with a reason, feeding an audit trail; today the app recommends and a person acts outside it.
5. **Line-level PO matching.** Match line items to PO lines for quantity and rate, not just invoice total to PO total.
6. **A real database** instead of a JSONL file, and a proper queue for volume.
