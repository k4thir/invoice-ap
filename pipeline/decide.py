"""
Stage 6 - Decide.

An ordered list of rules. Every rule is evaluated so the human sees everything
that is wrong, but the FIRST rule that fires sets the decision. No model is
involved: a payment decision must come out the same way every time and be
readable by the person who owns it.

Outcomes:  Reject  - do not pay, do not ask the vendor to fix it
           Hold    - a human must act; the next_action says what
           Approve - matches an open PO within tolerance, numbers check out

Rule order (first match wins):
   1 DUPLICATE_INVOICE        Reject
   2 VENDOR_NOT_APPROVED      Reject
   3 MISSING_FIELD            Hold
   4 ARITHMETIC / GST / DATE  Hold
   5 GSTIN_INVALID            Hold
   6 PO_NOT_FOUND             Hold
   7 PO_VENDOR_MISMATCH       Hold
   8 PO_CLOSED                Hold
   9 PO_INFERRED              Hold
  10 CUMULATIVE_EXCEEDS_PO    Hold   (over tolerance, and earlier invoices exist on the PO)
  11 OUTSIDE_TOLERANCE        Hold   (over tolerance, first invoice on the PO)
  12 LOW_CONFIDENCE           Hold   (a required field came from conflicting extractors)
     otherwise                Approve, annotated EXACT_MATCH / WITHIN_TOLERANCE / PARTIAL_DELIVERY
"""
from . import config

REJECT = "Reject"
HOLD = "Hold"
APPROVE = "Approve"

NEXT_ACTION = {
    "DUPLICATE_INVOICE": "Do not pay. {invoice_number} was already approved for payment on {dup_when} (run {dup_run}); reply to the vendor that it is a duplicate.",
    "VENDOR_NOT_APPROVED": "Route to procurement: '{vendor_name}' is not an approved vendor. Onboard the vendor first or confirm the correct legal entity.",
    "MISSING_FIELD": "Ask the vendor to reissue the invoice with: {missing}. Nothing can be matched without it.",
    "ARITHMETIC_MISMATCH": "Ask the vendor to confirm the figures: the stated total does not equal subtotal plus GST.",
    "LINE_ITEMS_SUM": "Ask the vendor to confirm the line items: they do not add up to the subtotal.",
    "GST_INCONSISTENT": "Check the tax treatment with finance before paying: the GST lines are inconsistent for this vendor's state.",
    "DATE_IMPLAUSIBLE": "Confirm the invoice date with the vendor before processing.",
    "GSTIN_INVALID": "Verify the vendor's GSTIN on the GST portal; the printed value is not a valid format (possibly an OCR misread).",
    "PO_NOT_FOUND": "Ask the requester which PO this belongs to, or ask the vendor to quote the PO number.",
    "PO_VENDOR_MISMATCH": "The cited PO was raised for a different vendor. Confirm with procurement before paying.",
    "PO_CLOSED": "The cited PO is closed. Confirm with procurement whether it should be reopened or a new PO raised.",
    "PO_INFERRED": "Confirm with the requester that {po_number} is the right PO; the invoice did not state one.",
    "CUMULATIVE_EXCEEDS_PO": "Confirm with procurement whether {po_number} should be increased: cumulative invoicing is {cumulative} against a PO of {po_amount} ({variance_pct} over).",
    "OUTSIDE_TOLERANCE": "Confirm the price with the requester: invoice is {variance_pct} over {po_number}, tolerance is {tolerance_pct}%.",
    "LOW_CONFIDENCE": "Check the highlighted fields against the PDF: the two extractors disagreed on {low_fields}.",
}


def _fmt(code, ctx):
    try:
        return NEXT_ACTION[code].format(**ctx)
    except (KeyError, IndexError):
        return NEXT_ACTION.get(code, "Review manually.")


def run(merged: dict, validation: dict, vendor: dict, po: dict, duplicate: dict, prior: dict = None) -> dict:
    """
    merged:     merged fields {key: {value, source, confidence, ...}}
    validation: output of validate.run
    vendor:     output of match.match_vendor
    po:         output of match.match_po
    duplicate:  {"is_duplicate": True, ...} only when an earlier run APPROVED this invoice
    prior:      an earlier non-approved run for the same invoice, now superseded (informational)
    """
    prior = prior or {}
    def v(k):
        f = merged.get(k)
        return None if f is None else f.get("value")

    failed = set(validation.get("failed_codes", []))
    missing = next((c.get("missing", []) for c in validation.get("checks", []) if c["code"] == "MISSING_FIELD"), [])
    low_fields = [k for k in config.REQUIRED_FIELDS if merged.get(k, {}).get("confidence") == "low"]
    tol = float(po.get("tolerance_pct") or vendor.get("tolerance_pct") or config.DEFAULT_TOLERANCE_PCT)

    ctx = {
        "invoice_number": v("invoice_number") or "this invoice",
        "vendor_name": v("vendor_name") or "the vendor",
        "missing": ", ".join(m.replace("_", " ") for m in missing) or "the missing fields",
        "po_number": po.get("po_number") or "the PO",
        "po_amount": f"{po['po_amount']:,.2f}" if po.get("po_amount") is not None else "?",
        "cumulative": f"{po['cumulative']:,.2f}" if po.get("cumulative") is not None else "?",
        "variance_pct": f"{po['variance_pct']:+.2f}%" if po.get("variance_pct") is not None else "?",
        "tolerance_pct": f"{tol:g}",
        "low_fields": ", ".join(k.replace("_", " ") for k in low_fields) or "some fields",
        "dup_when": (duplicate.get("when") or "")[:10],
        "dup_run": duplicate.get("run_id") or "?",
    }

    # Evaluate every rule; collect (code, outcome) in order.
    fired = []
    if duplicate.get("is_duplicate"):
        fired.append(("DUPLICATE_INVOICE", REJECT))
    if (v("vendor_name") or v("vendor_gstin")) and not vendor.get("approved"):
        fired.append(("VENDOR_NOT_APPROVED", REJECT))
    if "MISSING_FIELD" in failed:
        fired.append(("MISSING_FIELD", HOLD))
    for code in ("ARITHMETIC_MISMATCH", "LINE_ITEMS_SUM", "GST_INCONSISTENT", "DATE_IMPLAUSIBLE"):
        if code in failed:
            fired.append((code, HOLD))
    if "GSTIN_INVALID" in failed:
        fired.append(("GSTIN_INVALID", HOLD))

    over_tolerance = False
    if v("total") is not None and not missing:
        if not po.get("found"):
            fired.append(("PO_NOT_FOUND", HOLD))
        else:
            if po.get("vendor_matches") is False:
                fired.append(("PO_VENDOR_MISMATCH", HOLD))
            if po.get("po_status") and po["po_status"] != "open":
                fired.append(("PO_CLOSED", HOLD))
            if po.get("method") == "inferred":
                fired.append(("PO_INFERRED", HOLD))
            if po.get("variance_pct") is not None and po["variance_pct"] > tol:
                over_tolerance = True
                if (po.get("invoiced_before") or 0) > 0:
                    fired.append(("CUMULATIVE_EXCEEDS_PO", HOLD))
                else:
                    fired.append(("OUTSIDE_TOLERANCE", HOLD))
    if low_fields:
        fired.append(("LOW_CONFIDENCE", HOLD))

    explanation = []
    if fired:
        primary_code, status = fired[0]
        codes = [c for c, _ in fired]
        next_action = _fmt(primary_code, ctx)
        for code, outcome in fired:
            explanation.append(f"{outcome}: {code.replace('_', ' ').lower()}")
    else:
        status, codes = APPROVE, []
        vp = po.get("variance_pct")
        if vp is None or abs(vp) < 0.005:
            codes.append("EXACT_MATCH")
        elif vp < 0:
            codes.append("PARTIAL_DELIVERY")
        else:
            codes.append("WITHIN_TOLERANCE")
        primary_code = codes[0]
        next_action = {
            "EXACT_MATCH": f"Post for payment against {po.get('po_number')}. Invoice closes the PO exactly.",
            "PARTIAL_DELIVERY": f"Post for payment against {po.get('po_number')}. Cumulative {ctx['cumulative']} of {ctx['po_amount']} now invoiced; balance remains open.",
            "WITHIN_TOLERANCE": f"Post for payment against {po.get('po_number')}. Invoice is {ctx['variance_pct']} over PO, inside the {ctx['tolerance_pct']}% tolerance.",
        }[primary_code]
        if po.get("method") == "inferred_exact":
            codes.append("PO_MATCHED_BY_AMOUNT")
            next_action += f" The invoice did not state a PO; {po.get('po_number')} was the only open PO whose remaining balance equals it."
        if (po.get("invoiced_before") or 0) > 0 and primary_code == "EXACT_MATCH":
            codes.append("SPLIT_FINAL")
        if prior.get("found"):
            codes.append("RESUBMISSION")

    if prior.get("found") and not duplicate.get("is_duplicate"):
        if "RESUBMISSION" not in codes:
            codes.append("RESUBMISSION")
        explanation.append(f"Resubmission: previously {str(prior.get('status')).lower()} in run {prior.get('run_id')} on {(prior.get('when') or '')[:10]}; that run is now superseded by this evaluation.")

    # a short, human explanation of what the system looked at
    explanation.insert(0, vendor.get("summary") or "Vendor: nothing to match")
    if po.get("summary"):
        explanation.insert(1, po["summary"])
    explanation.append(validation.get("summary", ""))

    return {
        "status": status,
        "primary_code": primary_code,
        "codes": codes,
        "next_action": next_action,
        "explanation": explanation,
        "tolerance_pct": tol,
        "over_tolerance": over_tolerance,
        "consumes_po": status == APPROVE and bool(po.get("po_number")),
    }
