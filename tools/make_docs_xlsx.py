"""
Build docs/Invoice-to-Decision_Coverage.xlsx: what the system covers, how each case is
handled, where it would fail and what the next step would be.

    python tools/make_docs_xlsx.py
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

OUT = Path(__file__).resolve().parent.parent / "docs" / "Invoice-to-Decision_Coverage.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)

FONT = "Arial"
NAVY = "1B2A41"
BAND = "F3F5F8"
C = {"Covered": "DDF3E4", "Partial": "FFF0D6", "Not covered": "FFE1E4", "Approve": "DDF3E4", "Hold": "FFF0D6", "Reject": "FFE1E4"}

wb = Workbook()
thin = Side(style="thin", color="D5DBE1")
border = Border(left=thin, right=thin, top=thin, bottom=thin)


def sheet(title, headers, rows, widths, status_col=None, note=None):
    ws = wb.create_sheet(title)
    r0 = 1
    if note:
        ws.cell(row=1, column=1, value=note).font = Font(name=FONT, size=10, italic=True, color="5C6672")
        ws.cell(row=1, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        ws.row_dimensions[1].height = 34
        r0 = 3
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=r0, column=j, value=h)
        c.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = border
    for i, row in enumerate(rows, 1):
        for j, val in enumerate(row, 1):
            c = ws.cell(row=r0 + i, column=j, value=val)
            c.font = Font(name=FONT, size=10)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = border
            if i % 2 == 0:
                c.fill = PatternFill("solid", fgColor=BAND)
        if status_col is not None:
            v = row[status_col - 1]
            if v in C:
                ws.cell(row=r0 + i, column=status_col).fill = PatternFill("solid", fgColor=C[v])
                ws.cell(row=r0 + i, column=status_col).font = Font(name=FONT, size=10, bold=True)
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=r0 + 1, column=1)
    ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(headers))}{r0 + len(rows)}"
    return ws, r0


# ===================================================================== Pipeline
pipeline_rows = [
    ("1", "Read", "Pull text from the PDF. If there is no usable text layer, render the page and OCR it with Tesseract, recording a mean word confidence.",
     "PDF bytes", "Text, read path (text_layer / ocr), OCR confidence, page image, file hash", "No",
     "Corrupt, password-protected or non-PDF file -> Hold UNREADABLE_FILE. Never crashes."),
    ("2", "Identify", "Vendor name, GSTIN, invoice number, invoice date, PO reference. Rules (regex on known labels) run first. If vendor, PO, number or date is missing, ONE AI call asks for exactly those fields. Poor scan (OCR < 90%): AI reads the whole page once (image via Gemini, else OCR text via Groq) and rules cross-check.",
     "Text (+ page image)", "Identity fields with source (rules / ai / both) and confidence (high / medium / low)", "Only for gaps, or poor scans",
     "AI unavailable -> rules stand alone, gaps become Holds, log says AI_UNAVAILABLE."),
    ("3", "Match vendor", "Exact GSTIN match first (legal identifier beats names). Else fuzzy legal-name match with aliases, threshold 0.80. Inactive / blocked vendors count as not approved.",
     "Identity fields, vendor register", "vendor_id, legal name, tolerance %, approved flag, how it matched", "No",
     "No match -> decision Reject VENDOR_NOT_APPROVED (after money is still shown)."),
    ("4", "Match PO", "Stated PO looked up and checked for vendor and status. No PO stated: open POs for the vendor within 90 days whose remaining balance fits; exactly one EQUAL match -> usable, one approximate -> PO_INFERRED, else none. Cumulative = register invoiced_to_date + approvals made here + this invoice.",
     "Identity fields, vendor, PO register, approval ledger", "PO, method (explicit / inferred_exact / inferred), amounts, variance %, candidates", "No",
     "Not found -> Hold PO_NOT_FOUND. Vendor mismatch, closed PO, inferred PO -> Hold."),
    ("5", "Amounts", "Subtotal, CGST, SGST, IGST, total, line items. Rules first. If a gap remains AND vendor or PO matched, ONE AI call asks for the amounts and line items. If neither matched, no AI is spent: the decision will rest on identity. Poor scans already have amounts from the full read.",
     "Text, matching results", "Amount fields with source and confidence, line items", "Only for gaps, only if worth it",
     "Total missing -> Hold MISSING_FIELD. AI unavailable -> rules only."),
    ("6", "Check", "Required fields present; line items sum to subtotal; subtotal + GST = total (rounding tolerance INR 1); GST form (CGST+SGST vs IGST) consistent with vendor state code; GSTIN 15-character format; date not in future and < 365 days old.",
     "Merged fields", "List of checks with pass / fail / skipped and a sentence each", "No",
     "Any failure becomes a reason code; nothing stops."),
    ("7", "Decide", "Ordered rules (see Decision rules sheet). Every rule is evaluated so all problems are listed; the FIRST that fires sets the outcome. Plain-language next action is generated for the primary reason.",
     "Everything above, duplicate / prior lookup", "Approve / Hold / Reject, primary code, all codes, next action, explanation", "No",
     "Deterministic: the same invoice always gets the same decision."),
    ("8", "Record", "Append the full run (fields, evidence, checks, matching, decision, AI calls, policy notes, timings) to history. Mirror to a private Hugging Face dataset if configured. Mark a superseded earlier run when this is a resubmission.",
     "Run record", "History entry, dashboard row", "No",
     "Mirror failure is reported in the sidebar; local history still works."),
]

# ===================================================================== Decision rules
rules_rows = [
    (1, "An earlier run APPROVED the same invoice (same file, or same vendor + invoice number)", "Reject", "DUPLICATE_INVOICE", "Do not pay; reply to the vendor that it was already approved on <date>.", "inv07 after inv01"),
    (2, "Vendor not in the register, or status inactive / blocked", "Reject", "VENDOR_NOT_APPROVED", "Route to procurement; onboard the vendor or confirm the legal entity.", "Any invoice from a vendor not in Reference data"),
    (3, "A required field is missing (vendor, invoice number, date, total)", "Hold", "MISSING_FIELD", "Ask the vendor to reissue with the missing field named.", "inv04"),
    (4, "Subtotal + GST does not equal total; or line items do not sum to subtotal; or GST form inconsistent; or date implausible", "Hold", "ARITHMETIC_MISMATCH / LINE_ITEMS_SUM / GST_INCONSISTENT / DATE_IMPLAUSIBLE", "Confirm figures or tax treatment with the vendor / finance.", "Edit a sample total"),
    (5, "Vendor GSTIN malformed", "Hold", "GSTIN_INVALID", "Verify on the GST portal; may be an OCR misread.", "inv04 (secondary code)"),
    (6, "No PO stated and none inferable, or stated PO not in register", "Hold", "PO_NOT_FOUND", "Ask the requester which PO, or the vendor to quote it.", "Remove the PO line from a sample"),
    (7, "Stated PO belongs to a different vendor", "Hold", "PO_VENDOR_MISMATCH", "Confirm with procurement.", "Swap a PO number between vendors"),
    (8, "Stated PO is closed or cancelled", "Hold", "PO_CLOSED", "Confirm whether to reopen or raise a new PO.", "Reference PO-1033"),
    (9, "PO inferred (not stated) and fits only approximately", "Hold", "PO_INFERRED", "Confirm with the requester that this is the right PO.", "No-PO invoice within tolerance of a PO"),
    (10, "Cumulative invoicing exceeds PO beyond tolerance, earlier invoices exist", "Hold", "CUMULATIVE_EXCEEDS_PO", "Confirm with procurement whether the PO should be increased.", "inv05 then inv06"),
    (11, "First invoice on the PO exceeds it beyond tolerance", "Hold", "OUTSIDE_TOLERANCE", "Confirm the price with the requester.", "inv03"),
    (12, "Two extractors disagreed on a required field", "Hold", "LOW_CONFIDENCE", "Check the highlighted fields against the PDF.", "Poor scan with OCR / vision disagreement"),
    ("—", "None of the above", "Approve", "EXACT_MATCH / WITHIN_TOLERANCE / PARTIAL_DELIVERY", "Post for payment against the PO.", "inv01 / inv02 / inv09"),
    ("ann.", "Annotations added to an approval", "Approve", "PO_MATCHED_BY_AMOUNT (no PO stated; the only open PO that equals the amount) · SPLIT_FINAL (this invoice closes a PO that had earlier invoices) · RESUBMISSION (an earlier held / rejected run was superseded)", "—", "inv14 · inv10, inv13 · resubmit inv03 after raising PO-1041"),
    ("sys.", "File could not be read at all", "Hold", "UNREADABLE_FILE", "Open manually; may be corrupt or password-protected.", "Upload a non-PDF renamed .pdf"),
]

# ===================================================================== Test scenarios
tests_rows = [
    ("S01", "inv01_sk_fasteners_SKF-26-27-0912.pdf", "Happy path: clean text PDF, PO stated, exact amount, intra-state GST", "V001, PO-1037", "Approve", "EXACT_MATCH", 0, "text layer"),
    ("S02", "inv02_deccan_DP-2609-114.pdf", "1.5% over PO with 2% tolerance", "V002, PO-1040", "Approve", "WITHIN_TOLERANCE", 0, "text layer"),
    ("S03", "inv03_deccan_DP-2609-121.pdf", "3% over PO with 2% tolerance", "V002, PO-1041", "Hold", "OUTSIDE_TOLERANCE", 0, "text layer"),
    ("S04", "inv04_pune_packaging_scanned.pdf", "Photocopy-grade scan (OCR ~84%), invoice number blank on the paper; Gemini reads the image, rules cross-check", "V004, PO-1045", "Hold", "MISSING_FIELD (+ GSTIN_INVALID if OCR text is used)", 1, "ocr -> vision"),
    ("S05", "inv05_bharat_steel_BST-0882.pdf", "First invoice on a PO already 60% consumed; inter-state IGST", "V003, PO-1042 (300,000 already invoiced)", "Approve", "PARTIAL_DELIVERY", 0, "text layer"),
    ("S06", "inv06_bharat_steel_BST-0907.pdf", "Second invoice pushes cumulative to 570,220 vs PO 500,000", "V003, PO-1042", "Hold", "CUMULATIVE_EXCEEDS_PO", 0, "text layer"),
    ("S07", "inv07_sk_fasteners_resent.pdf", "inv01 reissued under a new filename after inv01 was approved", "V001, PO-1037", "Reject", "DUPLICATE_INVOICE", 0, "text layer"),
    ("S08", "inv08_nexora_NXR-TI-4471.pdf", "Unseen layout: 'Document No.', 'Dated', 'Ref PO', 'Amount Payable', bundled line, lakh grouping. Rules find 3 fields, AI fills the rest", "V005, PO-1048", "Approve", "EXACT_MATCH", 2, "text layer"),
    ("S09", "inv09_sahyadri_SE-1101_split1of2.pdf", "Split 1 of 2: 59,000 against a 118,000 PO", "V006, PO-1055", "Approve", "PARTIAL_DELIVERY", 0, "text layer"),
    ("S10", "inv10_sahyadri_SE-1108_split2of2.pdf", "Split 2 of 2: two items, 59,000; cumulative closes the PO exactly", "V006, PO-1055", "Approve", "EXACT_MATCH, SPLIT_FINAL", 0, "text layer"),
    ("S11", "inv11_deccan_DP-2610-131_split1of3.pdf", "Split 1 of 3: 59,000 of 118,000", "V002, PO-1057", "Approve", "PARTIAL_DELIVERY", 0, "text layer"),
    ("S12", "inv12_deccan_DP-2610-137_split2of3.pdf", "Split 2 of 3: 23,600; cumulative 82,600", "V002, PO-1057", "Approve", "PARTIAL_DELIVERY", 0, "text layer"),
    ("S13", "inv13_deccan_DP-2610-142_split3of3.pdf", "Split 3 of 3: 35,400; cumulative 118,000 closes the PO", "V002, PO-1057", "Approve", "EXACT_MATCH, SPLIT_FINAL", 0, "text layer"),
    ("S14", "inv14_pune_packaging_no_po.pdf", "No PO number on the invoice; exactly one open PO for the vendor equals the amount", "V004, PO-1053", "Approve", "EXACT_MATCH, PO_MATCHED_BY_AMOUNT", 0, "text layer"),
    ("S15", "inv08 with sidebar 'Use AI for gaps' OFF", "Fallback path: rules cannot read the layout, AI is not consulted", "V005, PO-1048", "Hold", "MISSING_FIELD (log shows AI off)", 0, "text layer"),
    ("S16", "inv03 again, after raising PO-1041 to 243,080 on the Reference data page", "Fix the data, resubmit: the earlier Hold is superseded", "V002, PO-1041", "Approve", "EXACT_MATCH, RESUBMISSION", 0, "text layer"),
    ("S17", "Any invoice from a vendor removed from the register, uploaded twice", "A rejection is not a duplicate: second run says VENDOR_NOT_APPROVED again, tagged RESUBMISSION", "Vendor absent", "Reject", "VENDOR_NOT_APPROVED, RESUBMISSION", 0, "text layer"),
    ("S18", "Same PDF uploaded twice after it was approved", "Duplicate by file hash", "Any approved sample", "Reject", "DUPLICATE_INVOICE", 0, "text layer"),
    ("S19", "Upload a vendors CSV missing a column, then a correct one", "Reference-data validation: row-level errors, nothing applied until clean", "—", "—", "UI error messages, then rows added", 0, "—"),
    ("S20", "Any upload with no Groq / Gemini key set", "AI unavailable: rules carry the run; gaps become Holds", "—", "Approve or Hold", "AI_UNAVAILABLE in the log", 0, "—"),
]

# ===================================================================== Edge cases
E = [
    # Input & file
    ("Input & file", "A normal digital invoice PDF arrives", "Text layer read in milliseconds; rules usually find everything; zero AI calls.", "Covered", "Approve / per rules", "inv01", ""),
    ("Input & file", "Vendor sends a scanned copy of good quality (OCR confidence >= 90%)", "OCR text is trusted like a text layer; rules first, AI only for gaps.", "Covered", "Per rules", "Regenerate inv04 with lighter noise to see this path", ""),
    ("Input & file", "Vendor sends a poor photocopy (OCR confidence < 90%)", "The page image is sent to Gemini vision; rules from the OCR text cross-check; disagreements keep the vision value with low confidence.", "Covered", "Per rules, often Hold", "inv04", ""),
    ("Input & file", "Scan is almost unreadable", "Vision returns null for fields it cannot see; the run holds with the exact missing fields named.", "Covered", "Hold MISSING_FIELD", "Upload a heavily blurred scan", "Next: ask the vendor for a digital copy automatically (email ingestion)."),
    ("Input & file", "Invoice photographed with a phone (skew, shadow, perspective)", "Treated as a scan. Vision handles moderate distortion; Tesseract's confidence will be low so the vision path is taken.", "Partial", "Per rules", "Photograph a printed sample", "Next: deskew / perspective correction before OCR."),
    ("Input & file", "Page is rotated 90 degrees or landscape", "Tesseract does not auto-rotate; OCR text is poor, confidence low, vision reads it anyway.", "Partial", "Per rules", "Rotate a sample in Preview", "Next: Tesseract orientation detection (OSD) before OCR."),
    ("Input & file", "Multi-page invoice (items on page 1, totals on page 2)", "All pages' text is concatenated, so rules and the text model see everything. Only the first page image goes to vision.", "Partial", "Per rules", "Merge two sample pages", "Next: send all page images, or the page containing the totals."),
    ("Input & file", "Several invoices in one PDF", "Treated as one document; the first invoice's fields dominate; arithmetic usually fails so it holds rather than paying a wrong amount.", "Partial", "Hold ARITHMETIC_MISMATCH", "Concatenate inv01 and inv02", "Next: split on invoice-number boundaries and run each."),
    ("Input & file", "File is corrupt, password-protected, or not actually a PDF", "Read stage fails gracefully.", "Covered", "Hold UNREADABLE_FILE", "Rename a .txt to .pdf and upload", ""),
    ("Input & file", "Vendor emails a JPG or PNG instead of a PDF", "The uploader accepts PDF only.", "Not covered", "—", "—", "Next: accept images and wrap them as single-page PDFs."),
    ("Input & file", "Someone uploads a purchase order copy, delivery challan or quotation by mistake", "No document-type check. Fields may be partly extracted; most such documents hold on missing total or PO.", "Partial", "Hold MISSING_FIELD / PO_NOT_FOUND", "Upload a non-invoice PDF", "Next: a document-type classification step before Identify."),
    ("Input & file", "Handwritten invoice", "OCR is nearly useless; vision reads what it can; unclear fields come back null or low confidence.", "Partial", "Hold or Reject", "Your handwritten test file", "Expected behaviour: never guesses; asks the vendor."),
    ("Input & file", "Invoice in Hindi / Marathi or mixed script", "Tesseract runs English only; vision reads other scripts; rules know English labels only.", "Partial", "Per rules", "—", "Next: Tesseract language packs; label lists per language."),
    ("Input & file", "Very large PDF", "Upload capped at 25 MB (config).", "Covered", "Upload refused by the UI", "—", ""),
    # Extraction
    ("Extraction", "Vendor uses unusual labels ('Document No.', 'Dated', 'Ref PO', 'Amount Payable')", "Rules miss them; the AI is asked for exactly the missing fields and returns them with the text snippet each came from.", "Covered", "Approve", "inv08", ""),
    ("Extraction", "Amounts printed in Indian grouping (1,77,000.00) or with 'INR' / 'Rs.' prefixes", "Parsed by both rules and AI normalisation.", "Covered", "—", "inv08", ""),
    ("Extraction", "Total printed only in words, or no total at all", "Nothing invents a number.", "Covered", "Hold MISSING_FIELD: total", "Edit a sample", ""),
    ("Extraction", "Invoice number blank", "Required field missing; next action names it.", "Covered", "Hold MISSING_FIELD: invoice number", "inv04", ""),
    ("Extraction", "OCR confuses characters in the GSTIN (1/l, 0/O, 5/S)", "Format check fails on the OCR value; on poor scans the vision read usually corrects it and the conflict is shown.", "Covered", "Hold GSTIN_INVALID (or corrected)", "inv04 with AI off", ""),
    ("Extraction", "OCR misreads a digit inside an amount", "Subtotal + GST = total no longer holds, so it is caught.", "Covered", "Hold ARITHMETIC_MISMATCH", "—", "A misread that keeps the arithmetic consistent is not detectable from the document alone; the PO match is the second net."),
    ("Extraction", "Rules and AI disagree on a required field", "Value kept according to the merge policy, confidence set to low, conflict shown in the ledger.", "Covered", "Hold LOW_CONFIDENCE", "Poor scan", ""),
    ("Extraction", "The AI invents a value that is not printed (hallucination)", "Arithmetic and GSTIN checks catch inconsistent inventions; the evidence snippet is shown for a human to verify; on text PDFs amounts are anchored to printed labels by the rules.", "Partial", "Often Hold", "—", "Next: require the evidence snippet to appear in the source text before accepting an AI value."),
    ("Extraction", "AI provider is down, out of quota, or no key is configured", "The stage continues on rules; every gap becomes a Hold with a next action; the log says AI_UNAVAILABLE.", "Covered", "Approve or Hold", "Sidebar toggle off, run inv08", ""),
    ("Extraction", "AI rate-limits in the middle of a batch", "Two retries with backoff, then the other provider if a key exists.", "Covered", "—", "—", ""),
    ("Extraction", "Configured Gemini model name has been retired (HTTP 404)", "The app lists the models the key can use, picks the newest plain Flash, retries once, and shows the model in use.", "Covered", "—", "Set GEMINI_MODEL to a wrong name", ""),
    ("Extraction", "Both buyer and vendor names and GSTINs are on the page", "Buyer name and GSTIN are excluded explicitly in rules and in the AI instruction.", "Covered", "—", "Every sample", ""),
    ("Extraction", "Line items bundled into a single line", "Accepted; the line-sum check still runs.", "Covered", "—", "inv08", ""),
    ("Extraction", "Line items do not add up to the subtotal", "Flagged by the line-sum check.", "Covered", "Hold LINE_ITEMS_SUM", "Edit a sample line", ""),
    # Vendor
    ("Vendor", "Vendor prints a short name or abbreviation ('SK Fasteners')", "Alias list plus fuzzy match at 0.80 on normalised names (legal suffixes removed).", "Covered", "—", "Change a sample vendor header", ""),
    ("Vendor", "Printed GSTIN belongs to a different registered vendor than the printed name", "GSTIN wins silently.", "Partial", "Approve (possibly wrong entity)", "—", "Next: flag when GSTIN and name resolve to different vendors."),
    ("Vendor", "Vendor is not in the approved register", "Money fields are still extracted and shown, but no AI is spent on them; decision is Reject with a procurement next action.", "Covered", "Reject VENDOR_NOT_APPROVED", "Delete a vendor on Reference data, run its invoice", ""),
    ("Vendor", "Vendor exists but is inactive or blocked", "Treated as not approved.", "Covered", "Reject VENDOR_NOT_APPROVED", "V007 Konark", ""),
    ("Vendor", "New vendor onboarded today", "Upload a CSV or add one row on Reference data; the next run matches it.", "Covered (session)", "Approve", "Add vendor, re-run", "Next: persist reference data beyond the session."),
    ("Vendor", "Two different legal entities with near-identical names", "Fuzzy match may pick the wrong one when no GSTIN is printed.", "Partial", "Approve (risk)", "—", "Next: require a GSTIN match when more than one name clears the threshold."),
    # Purchase order
    ("Purchase order", "PO stated on the invoice and found", "Looked up directly; vendor and status checked.", "Covered", "Per rules", "inv01", ""),
    ("Purchase order", "PO stated but not in the register (typo or unknown)", "Nothing is inferred when a PO is stated.", "Covered", "Hold PO_NOT_FOUND", "Edit a sample PO number", ""),
    ("Purchase order", "PO belongs to another vendor", "Detected after vendor match.", "Covered", "Hold PO_VENDOR_MISMATCH", "Swap PO numbers", ""),
    ("Purchase order", "PO is closed or cancelled", "Status checked.", "Covered", "Hold PO_CLOSED", "PO-1033", ""),
    ("Purchase order", "No PO number, exactly one open PO for the vendor equals the amount", "Approved, annotated so the reviewer knows it was matched by amount.", "Covered", "Approve PO_MATCHED_BY_AMOUNT", "inv14", ""),
    ("Purchase order", "No PO number, one PO fits only within tolerance or as a partial", "A human confirms.", "Covered", "Hold PO_INFERRED", "Change inv14's amount slightly", ""),
    ("Purchase order", "No PO number, several POs could fit", "Candidates are listed; nothing is chosen.", "Covered", "Hold PO_NOT_FOUND", "Add a second matching PO", ""),
    ("Purchase order", "Register holds PO amounts excluding GST (data entry error)", "Every invoice on that PO looks ~18% over and holds. The GST-inclusive assumption is documented on the Reference page.", "Partial", "Hold OUTSIDE_TOLERANCE", "—", "Next: an incl/excl flag per PO."),
    ("Purchase order", "Invoice dated before the PO date", "Not checked for stated POs (inference window excludes it).", "Partial", "Approve", "—", "Next: date-order check."),
    ("Purchase order", "Right amount, wrong goods (items do not match the PO)", "Matching is at the amount level; line items are read but not compared to PO lines.", "Not covered", "Approve (risk)", "—", "Next: PO line items in the register and line-level matching."),
    ("Purchase order", "Invoice currency differs from the PO (USD vs INR)", "Not checked.", "Not covered", "Per amounts", "—", "Next: currency extraction and a mismatch rule."),
    # Amounts & tax
    ("Amounts & tax", "Invoice a little over the PO (price rounding, freight)", "Within the vendor's tolerance it approves, annotated.", "Covered", "Approve WITHIN_TOLERANCE", "inv02", ""),
    ("Amounts & tax", "Invoice materially over the PO", "Holds with the variance shown.", "Covered", "Hold OUTSIDE_TOLERANCE", "inv03", ""),
    ("Amounts & tax", "Different vendors negotiate different tolerances", "Tolerance is a column in the vendor register (V005 has 5%).", "Covered", "—", "inv08 at 177,000 vs a 172,000 PO", ""),
    ("Amounts & tax", "GST rate other than 18%", "Structure (which taxes appear) is checked and arithmetic must balance; the rate itself is not validated.", "Covered by design", "—", "—", "Next: HSN-based rate table if required."),
    ("Amounts & tax", "Intra-state vendor charges IGST, or inter-state charges CGST/SGST", "Vendor state code from the GSTIN is compared with the GST form on the invoice.", "Covered", "Hold GST_INCONSISTENT", "Edit a sample's tax lines", ""),
    ("Amounts & tax", "Round-off line (+/- 0.50)", "Rounding tolerance of INR 1 in every arithmetic check.", "Covered", "—", "—", ""),
    ("Amounts & tax", "Freight, packing or other charges added after the subtotal", "Arithmetic no longer balances, so it holds rather than paying unverified charges.", "Partial", "Hold ARITHMETIC_MISMATCH", "—", "Next: an 'other charges' field in the schema and the checks."),
    ("Amounts & tax", "Discount, TDS deduction or advance adjusted on the invoice", "Same as above: holds for a human.", "Partial", "Hold ARITHMETIC_MISMATCH", "—", "Next: deduction fields."),
    ("Amounts & tax", "Credit note or negative amount", "Treated as an invoice; negative values fail checks.", "Not covered", "Hold", "—", "Next: document type 'credit note' with reversal logic against the ledger."),
    ("Amounts & tax", "Invoice dated in the future or more than a year old", "Date sanity check.", "Covered", "Hold DATE_IMPLAUSIBLE", "Edit a sample date", ""),
    # Duplicates & resubmission
    ("Duplicates", "Vendor resends an invoice that was already approved (new filename, same number)", "Same vendor + invoice number as an approved run.", "Covered", "Reject DUPLICATE_INVOICE", "inv07 after inv01", ""),
    ("Duplicates", "The same file is uploaded twice after approval", "File hash match.", "Covered", "Reject DUPLICATE_INVOICE", "Upload inv01 twice", ""),
    ("Duplicates", "A HELD invoice is uploaded again after the PO was increased", "Not a duplicate (nothing was paid): re-evaluated; the earlier run is marked superseded on the dashboard.", "Covered", "Approve RESUBMISSION", "Raise PO-1041, re-run inv03", ""),
    ("Duplicates", "A REJECTED invoice is uploaded again unchanged", "Re-evaluated; same rejection, tagged as a resubmission; primary reason stays the real one (e.g. vendor not approved).", "Covered", "Reject <same code>, RESUBMISSION", "Run an unapproved-vendor invoice twice", ""),
    ("Duplicates", "Same invoice number resubmitted with a different amount (altered after approval)", "Rejected as a duplicate by number; the amount difference is not highlighted.", "Partial", "Reject DUPLICATE_INVOICE", "Edit inv07's total", "Next: show the delta and flag as possible tampering."),
    ("Duplicates", "Vendor bills the same goods twice under a new invoice number", "Indistinguishable from a legitimate second delivery at the document level; the PO ledger limits the damage (cumulative exceeds PO).", "Partial", "Approve until the PO is exhausted", "—", "Next: fuzzy duplicate on vendor + amount + date window, flagged for review."),
    # Split & partial
    ("Split & partial", "One PO billed in two invoices", "Ledger-based cumulative: first approves as partial, second closes the PO.", "Covered", "PARTIAL_DELIVERY then EXACT_MATCH + SPLIT_FINAL", "inv09, inv10", ""),
    ("Split & partial", "One PO billed in three invoices", "Same mechanism, any number of parts.", "Covered", "PARTIAL, PARTIAL, SPLIT_FINAL", "inv11, inv12, inv13", ""),
    ("Split & partial", "Split invoices add up to more than the PO", "Cumulative compared with PO plus tolerance.", "Covered", "Hold CUMULATIVE_EXCEEDS_PO", "inv05, inv06", ""),
    ("Split & partial", "Split invoices arrive out of order", "Amount-level logic is order-independent.", "Covered", "—", "Run inv13 before inv11", ""),
    ("Split & partial", "Invoices already recorded in the ERP before this system started", "invoiced_to_date column in the PO register is added to approvals made here.", "Covered", "—", "PO-1042", ""),
    ("Split & partial", "Under-delivery: the PO never gets closed", "Nothing flags a PO that stays partly open.", "Partial", "—", "—", "Next: PO ageing view on the dashboard."),
    ("Split & partial", "Holds and rejects must not consume PO budget", "Only approvals are added to the ledger; superseded runs are excluded.", "Covered", "—", "Reference data page, 'approved_here' column", ""),
    # Operations & governance
    ("Operations", "The hosting platform restarts and wipes the disk", "History is mirrored to a private Hugging Face dataset when HF_TOKEN / HF_DATASET_REPO are set and restored on start.", "Covered (needs setup)", "—", "Set the two secrets", "Without the secrets, history is lost on restart."),
    ("Operations", "Reference data uploaded in the app is lost on restart", "Session-only by design for the demo.", "Partial", "—", "—", "Next: persist uploads to the same mirror."),
    ("Operations", "Someone uploads a reference CSV with wrong columns or bad values", "Row-level validation with exact messages; nothing is applied until the file is clean; templates downloadable.", "Covered", "—", "Upload a broken CSV", ""),
    ("Operations", "Two reviewers use the app at the same time", "Separate sessions (own reference data, own last-run view); shared history file, last write wins.", "Partial", "—", "—", "Next: a real database with row locking."),
    ("Operations", "Reviewer wants to approve anyway / reject anyway inside the app", "Decisions are recommendations; the action happens in the ERP. No override button.", "Not covered", "—", "—", "Next: override with mandatory reason, written to the audit trail."),
    ("Operations", "Auditor asks why an invoice was paid", "Every run stores the raw text, each field with its source and evidence snippet, every check, the matching arithmetic, every AI call and the policy notes, with timings.", "Covered", "—", "Dashboard -> open any run", ""),
    ("Operations", "API keys and secrets", "Environment / Streamlit secrets only; .env is git-ignored; never printed.", "Covered", "—", "—", ""),
    ("Operations", "Invoice data is sent to a third-party AI", "Groq / Gemini free tiers may use prompts to improve models. Acceptable for fictional data; not for client PII.", "Partial (documented limitation)", "—", "—", "Next: paid tier or a private deployment; the architecture does not change."),
    ("Operations", "Invoices arrive by email, not by upload", "Not built.", "Not covered", "—", "—", "Next step 1: poll a mailbox, run attachments, reply to the vendor on Hold with the next-action text."),
    ("Operations", "Hundreds of invoices a month", "Sequential processing, typically 1 to 5 seconds each; no queue or retry workers.", "Partial", "—", "Upload several files at once", "Next: background queue and a proper database."),
]

# ===================================================================== AI policy
ai_rows = [
    ("1", "Text PDF, or scan with OCR confidence >= 90%", "Identity gaps: vendor name, PO reference, invoice number or date missing after rules", "Groq, text", "Only the missing identity fields", "Rules' values are never overwritten; AI fills gaps at medium confidence", "Call skipped; gaps become Holds"),
    ("2", "Same", "Amount gaps after rules AND (vendor matched OR PO matched)", "Groq, text", "subtotal, cgst, sgst, igst, total + line items", "Same", "Call skipped; total missing -> Hold"),
    ("3", "Same", "Amount gaps but NEITHER vendor nor PO matched", "No call", "—", "Rules' amounts shown; decision rests on identity (Reject / Hold)", "—"),
    ("4", "Scan with OCR confidence < 90%", "Always, once, at Identify", "Gemini vision, page image (if GEMINI_API_KEY) else Groq, OCR text", "All fields + line items", "Rules cross-check: agree -> high; AI only -> medium; disagree -> AI kept, low", "Vision failure falls back to text; text failure -> rules only"),
    ("5", "Any provider error", "429 / 5xx / timeout", "Retry twice with backoff, then the other provider", "—", "—", "Status 'unavailable' recorded; pipeline continues"),
    ("6", "Gemini model name retired (404)", "First Gemini call", "List models, pick newest plain Flash, retry once", "—", "Model in use shown in the sidebar", "—"),
    ("—", "Totals", "Clean invoice: 0 calls. Unseen layout: 2. Poor scan: 1. Over the 14 samples: 3 calls.", "", "", "Every call is listed per run: purpose, input type, fields asked, fields returned, model, time, result", ""),
]

# ===================================================================== Reference schema
schema_rows = [
    ("vendors.csv", "vendor_id", "Text, unique", "Key used by purchase_orders.vendor_id", "V001"),
    ("vendors.csv", "legal_name", "Text", "Primary name for fuzzy matching", "Shree Krishna Fasteners Pvt Ltd"),
    ("vendors.csv", "aliases", "Text, | separated", "Alternative names the vendor prints", "SK Fasteners|SKF Pune"),
    ("vendors.csv", "gstin", "15 chars, validated format", "Exact match beats name match; first two digits are the state code used by the GST structure check", "27AABCS1234F1Z5"),
    ("vendors.csv", "state_code / state", "Text", "Informational", "27 / Maharashtra"),
    ("vendors.csv", "tolerance_pct", "Number", "Allowed overrun of cumulative vs PO, percent", "2"),
    ("vendors.csv", "status", "approved | inactive | blocked", "Only approved can be paid", "approved"),
    ("purchase_orders.csv", "po_number", "PO-#### , unique", "Matched against the invoice's PO reference", "PO-1037"),
    ("purchase_orders.csv", "vendor_id", "Must exist in vendors", "PO_VENDOR_MISMATCH if the invoice's vendor differs", "V001"),
    ("purchase_orders.csv", "po_date", "YYYY-MM-DD", "Used by the 90-day inference window", "2026-09-02"),
    ("purchase_orders.csv", "currency", "Text", "Informational today (see edge cases)", "INR"),
    ("purchase_orders.csv", "po_amount", "Number, GST-inclusive", "Compared with cumulative invoiced", "118000"),
    ("purchase_orders.csv", "invoiced_to_date", "Number", "Amount already invoiced before this system; approvals made here are added", "0"),
    ("purchase_orders.csv", "status", "open | closed | cancelled", "Only open POs accept invoices", "open"),
    ("purchase_orders.csv", "description", "Text", "Shown on the run", "M8 hex bolts and nuts"),
]

# ===================================================================== Assumptions
assumptions_rows = [
    ("One invoice per PDF", "Multi-invoice PDFs are treated as one document and usually hold on arithmetic.", "Split on invoice-number boundaries."),
    ("PO amounts are GST-inclusive", "Invoice totals compare directly with PO amounts.", "Add an incl/excl flag if the register mixes both."),
    ("Tolerance is set per vendor by procurement", "Stored in vendors.csv; default 2%.", "—"),
    ("A duplicate is an invoice that was already APPROVED", "Same vendor + invoice number, or the same file. Held and rejected invoices are re-evaluated and the earlier run is superseded.", "—"),
    ("Approvals consume PO budget; holds and rejects do not", "The ledger adds only approved totals; superseded runs are excluded.", "—"),
    ("A PO is approved without being stated only on an exact amount match", "Approximate or multiple fits go to a human.", "—"),
    ("GST rate is not validated, GST structure is", "CGST+SGST vs IGST must match the vendor's state; arithmetic must balance.", "HSN rate table if needed."),
    ("Rounding tolerance INR 1", "Applies to every arithmetic check.", "—"),
    ("Reference data uploaded in the app lasts for the session", "Bundled CSVs are the baseline on every start.", "Persist to the history mirror."),
    ("AI never decides", "A model is used only to read fields the rules missed or to read poor scans; its output is a candidate checked by arithmetic, format and reference data.", "—"),
    ("Free-tier AI providers", "Prompts may be used by the provider to improve models; fine for fictional data, not for client PII.", "Paid tier / private deployment."),
    ("History on a free host needs the mirror", "Disk resets on restart; HF_TOKEN + HF_DATASET_REPO keep history.", "Real database."),
]

# ===================================================================== Codes
codes_rows = [
    ("DUPLICATE_INVOICE", "Reject", "Same vendor + invoice number (or same file) was already approved."),
    ("VENDOR_NOT_APPROVED", "Reject", "Vendor not in the register or not approved."),
    ("MISSING_FIELD", "Hold", "A required field (vendor, invoice number, date, total) could not be read."),
    ("ARITHMETIC_MISMATCH", "Hold", "Subtotal + GST does not equal the stated total."),
    ("LINE_ITEMS_SUM", "Hold", "Line items do not add up to the subtotal."),
    ("GST_INCONSISTENT", "Hold", "GST form does not match the vendor's state, or CGST and SGST differ, or both forms appear."),
    ("DATE_IMPLAUSIBLE", "Hold", "Invoice date in the future, unparseable, or older than a year."),
    ("GSTIN_INVALID", "Hold", "Vendor GSTIN is not a valid 15-character format."),
    ("PO_NOT_FOUND", "Hold", "No PO stated and none inferable, or stated PO unknown."),
    ("PO_VENDOR_MISMATCH", "Hold", "The PO was raised for a different vendor."),
    ("PO_CLOSED", "Hold", "The PO is closed or cancelled."),
    ("PO_INFERRED", "Hold", "PO not stated; one open PO fits approximately."),
    ("CUMULATIVE_EXCEEDS_PO", "Hold", "Earlier invoices plus this one exceed the PO beyond tolerance."),
    ("OUTSIDE_TOLERANCE", "Hold", "First invoice on the PO exceeds it beyond tolerance."),
    ("LOW_CONFIDENCE", "Hold", "Rules and AI disagreed on a required field."),
    ("UNREADABLE_FILE", "Hold", "The file could not be read."),
    ("EXACT_MATCH", "Approve", "Invoice closes the PO exactly."),
    ("WITHIN_TOLERANCE", "Approve", "Over the PO but within the vendor's tolerance."),
    ("PARTIAL_DELIVERY", "Approve", "Cumulative below the PO; balance remains open."),
    ("PO_MATCHED_BY_AMOUNT", "Approve (annotation)", "PO not stated; the only open PO whose remaining balance equals the invoice."),
    ("SPLIT_FINAL", "Approve (annotation)", "This invoice closes a PO that had earlier invoices."),
    ("RESUBMISSION", "Any (annotation)", "An earlier held / rejected run for the same invoice was superseded by this one."),
    ("AI_UNAVAILABLE", "Log note", "No AI provider responded; rules carried the extraction."),
]

# ===================================================================== build
ws0 = wb.active
ws0.title = "Overview"
sheet("Pipeline", ["#", "Stage", "What it does", "Input", "Output", "Uses a model?", "Failure handling"], pipeline_rows, [4, 14, 70, 22, 40, 16, 44])
sheet("Decision rules", ["Order", "Condition", "Outcome", "Code(s)", "Next action shown to the reviewer", "How to demo"], rules_rows, [7, 56, 10, 40, 48, 30], status_col=3,
      note="Rules are evaluated top to bottom; every rule that fires is listed on the run, the first one sets the decision. Annotations are added to approvals for context; they never change the outcome.")
sheet("Test scenarios", ["ID", "File or action", "What it proves", "Reference data involved", "Expected decision", "Expected codes", "AI calls", "Read path"], tests_rows, [6, 42, 60, 30, 14, 36, 9, 14], status_col=5,
      note="S01-S14 are the bundled sample PDFs (download from the app sidebar). Suggested live order: S01, S08, S04, S05, S06, S07, S14, S09, S10, S03, S16, S15. Clear history first (Dashboard -> Reset).")
sheet("Edge cases", ["Category", "Scenario (as the customer would describe it)", "What the system does today", "Coverage", "Decision / code", "How to demo", "Gap and recommended next step"], E, [16, 48, 62, 16, 30, 32, 52], status_col=4,
      note="Coverage: Covered = handled and demonstrable; Partial = handled safely but not fully (usually fails to Hold rather than paying wrongly); Not covered = no handling today. Read 'Gap' for the planned next step.")
sheet("AI policy", ["Tier", "Document condition", "Trigger", "Provider and input", "Fields requested", "How the result is merged", "If the call fails"], ai_rows, [6, 30, 44, 34, 34, 50, 36])
sheet("Reference schema", ["File", "Column", "Type / allowed values", "How it is used", "Example"], schema_rows, [20, 20, 28, 60, 30])
sheet("Assumptions", ["Assumption", "Consequence", "Change needed if the assumption is wrong"], assumptions_rows, [44, 70, 40])
sheet("Codes", ["Code", "Outcome", "Meaning"], codes_rows, [26, 20, 80])

# ---- Overview sheet (summary with live COUNTIF formulas against the Edge cases sheet)
ws = ws0
ws["A1"] = "Invoice to decision: coverage and failure-mode documentation"
ws["A1"].font = Font(name=FONT, size=14, bold=True, color=NAVY)
ws["A2"] = "Accounts-payable automation for Meridian Components Pvt Ltd (fictional). Built for Zamp's AI Solutions Associate case study, PS-1."
ws["A2"].font = Font(name=FONT, size=10, color="5C6672")
lines = [
    ("What it does", "A vendor invoice PDF goes in; a reasoned decision comes out: Approve, Hold (with the next action) or Reject. Every stage, field, check and AI call is visible on the run and kept in history."),
    ("Where AI is used", "Only to read fields the rules missed, or to read a poor scan. It never matches, never checks and never decides. Most clean invoices make zero AI calls."),
    ("How to read this workbook", "Pipeline: the eight stages. Decision rules: the ordered rules and codes. Test scenarios: the 14 sample PDFs and 6 operational scenarios with expected results. Edge cases: 78 situations from the customer's point of view, what happens today, coverage and the next step. AI policy, Reference schema, Assumptions and Codes are reference."),
]
r = 4
for k, v in lines:
    ws.cell(row=r, column=1, value=k).font = Font(name=FONT, size=10, bold=True)
    c = ws.cell(row=r, column=2, value=v)
    c.font = Font(name=FONT, size=10)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[r].height = 48
    r += 1
r += 1
ws.cell(row=r, column=1, value="Coverage summary (live counts from the Edge cases sheet)").font = Font(name=FONT, size=11, bold=True, color=NAVY)
r += 1
hdr = ["Coverage", "Count", "Share"]
for j, h in enumerate(hdr, 1):
    c = ws.cell(row=r, column=j, value=h)
    c.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=NAVY)
    c.border = border
first = r + 1
n_edge = len(E)
rng = f"'Edge cases'!$D$4:$D${3 + n_edge}"
for i, label in enumerate(["Covered", "Partial", "Not covered"]):
    rr = first + i
    ws.cell(row=rr, column=1, value=label).fill = PatternFill("solid", fgColor=C[label])
    ws.cell(row=rr, column=2, value=f'=COUNTIF({rng},"{label}*")')
    ws.cell(row=rr, column=3, value=f"=IFERROR(B{rr}/B{first + 3},0)")
    ws.cell(row=rr, column=3).number_format = "0%"
    for j in (1, 2, 3):
        ws.cell(row=rr, column=j).font = Font(name=FONT, size=10)
        ws.cell(row=rr, column=j).border = border
tot = first + 3
ws.cell(row=tot, column=1, value="Total scenarios").font = Font(name=FONT, size=10, bold=True)
ws.cell(row=tot, column=2, value=f"=COUNTA({rng})").font = Font(name=FONT, size=10, bold=True)
ws.cell(row=tot, column=3, value=f"=IFERROR(B{tot}/B{tot},0)").number_format = "0%"
for j in (1, 2, 3):
    ws.cell(row=tot, column=j).border = border
r = tot + 2
ws.cell(row=r, column=1, value="Note").font = Font(name=FONT, size=10, bold=True)
ws.cell(row=r, column=2, value="'Covered (session)', 'Covered (needs setup)', 'Covered by design' and 'Partial (documented limitation)' are counted by their prefix. Counts update automatically if rows are added to the Edge cases sheet with the same labels.").font = Font(name=FONT, size=10, color="5C6672")
ws.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
ws.row_dimensions[r].height = 40
ws.column_dimensions["A"].width = 26
ws.column_dimensions["B"].width = 110
ws.column_dimensions["C"].width = 12

wb.save(OUT)
print("wrote", OUT, "| edge cases:", n_edge)
