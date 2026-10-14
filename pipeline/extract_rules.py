"""
Stage 2a - Rule-based extraction.

Plain pattern matching for the fields we care about. This is deliberately
written for the labels we have seen (Invoice No, Inv #, Invoice Number,
Grand Total, Total Amount, Total Payable, Sub Total, Taxable Value ...).
A vendor who uses different words will produce gaps here. That is expected:
the AI extractor (stage 2b) exists to fill exactly those gaps, and the
validation stage checks whichever source we end up trusting.

Every value we find is returned as {"value": ..., "evidence": "<the text it came from>"}.
"""
import re
from datetime import datetime

from . import config

GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
PO_RE = re.compile(r"\b(PO-\d{3,6})\b", re.I)
AMOUNT = r"((?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?)"

INVOICE_NO_PATTERNS = [
    r"Invoice\s*(?:No|Number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{2,})",
    r"Inv\.?\s*(?:No|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{2,})",
    r"Bill\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{2,})",
]
DATE_LABELS = [r"Invoice\s*Date", r"Bill\s*Date", r"\bDate\b"]
DATE_VALUE = r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|\d{1,2}-[A-Za-z]{3}-\d{4})"
DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y"]

TOTAL_LABELS = [r"Grand\s*Total", r"Total\s*Amount(?:\s*\(INR\))?", r"Total\s*Payable", r"Invoice\s*Total", r"Net\s*Payable", r"\bTotal\b"]
SUBTOTAL_LABELS = [r"Sub\s*Total", r"Subtotal", r"Taxable\s*Value", r"Taxable\s*Amount"]
TAX_LABELS = {
    "cgst": [r"CGST"],
    "sgst": [r"SGST"],
    "igst": [r"IGST"],
}


def to_amount(s: str):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def parse_date(s: str):
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _first(patterns, text, flags=re.I, require_digit=False):
    for p in patterns:
        for m in re.finditer(p, text, flags):
            val = m.group(1).strip()
            if require_digit and not re.search(r"\d", val):
                continue
            return {"value": val, "evidence": m.group(0).strip()}
    return None


CURRENCY_AMOUNT = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{2})(?!\s*%)(?![\d,])")


def _labelled_amount(labels, text, exclude_labels=None):
    """
    Find the line that carries LABEL and return the last currency-formatted
    amount on it (e.g. 'CGST @ 9% 9,000.00' -> 9000.0). Bare integers and
    percentages are never accepted, so 'Section 31 of the CGST Act, 2017'
    yields nothing. Labels are tried in priority order.
    """
    lines = text.splitlines()
    for label in labels:
        lab = re.compile(label, re.I)
        for line in lines:
            if not lab.search(line):
                continue
            if exclude_labels and any(re.search(x, line, re.I) for x in exclude_labels):
                continue
            amounts = [m for m in CURRENCY_AMOUNT.finditer(line)]
            if not amounts:
                continue
            amt = to_amount(amounts[-1].group(1))
            if amt is not None:
                return {"value": amt, "evidence": line.strip()}
    return None


CUT_AT = re.compile(r"\s+(TAX\s+INVOICE|INVOICE\s*(?:NO|NUMBER|DATE|#)?\b|GSTIN|DATE\b|CONSIGNEE|BILL\s+TO|INV\s*#)", re.I)
SKIP_LINE = re.compile(r"^(\(|tax\s+invoice\b|invoice\b|bill\s+to\b|bill\s+from\b|original\b|duplicate\b)", re.I)


def vendor_name_guess(text: str):
    """The vendor is almost always the first substantial line that is not a heading.
    pdfplumber can merge a right-hand column onto the same line, so cut at the first label."""
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 4 or SKIP_LINE.match(line):
            continue
        line = CUT_AT.split(line, maxsplit=1)[0].strip()
        if len(line) < 4 or config.BUYER_NAME.lower() in line.lower():
            continue
        return {"value": line, "evidence": line}
    return None


def run(text: str) -> dict:
    fields = {}

    inv = _first(INVOICE_NO_PATTERNS, text, require_digit=True)
    if inv:
        fields["invoice_number"] = inv

    for label in DATE_LABELS:
        m = re.search(label + r"\s*[:\-]?\s*" + DATE_VALUE, text, re.I)
        if m:
            iso = parse_date(m.group(1))
            if iso:
                fields["invoice_date"] = {"value": iso, "evidence": m.group(0).strip()}
                break

    po = PO_RE.search(text)
    if po:
        fields["po_reference"] = {"value": po.group(1).upper(), "evidence": po.group(0)}

    gstins = [g for g in GSTIN_RE.findall(text) if g != config.BUYER_GSTIN]
    if gstins:
        fields["vendor_gstin"] = {"value": gstins[0], "evidence": gstins[0]}

    vn = vendor_name_guess(text)
    if vn:
        fields["vendor_name"] = vn

    sub = _labelled_amount(SUBTOTAL_LABELS, text)
    if sub:
        fields["subtotal"] = sub
    for key, labels in TAX_LABELS.items():
        hit = _labelled_amount(labels, text)
        if hit:
            fields[key] = hit
    tot = _labelled_amount(TOTAL_LABELS, text, exclude_labels=SUBTOTAL_LABELS)
    if tot:
        fields["total"] = tot

    found = [k for k in config.FIELDS if k in fields]
    missing = [k for k in config.FIELDS if k not in fields and k not in ('cgst', 'sgst', 'igst')]
    if not any(k in fields for k in ('cgst', 'sgst', 'igst')):
        missing.append('gst lines')
    return {
        "fields": fields,
        "found": found,
        "missing": missing,
        "summary": f"Rules found {len(found)} of {len(config.FIELDS)} fields" + (f"; missing {', '.join(missing)}" if missing else ""),
    }
