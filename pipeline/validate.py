"""
Stage 3 - Validate.

Pure checks on the merged fields. No lookups, no AI. Every failure becomes a
reason code; nothing stops the pipeline. The decision stage decides what the
reason codes mean.

Each check returns {"code": ..., "ok": bool, "detail": "human sentence"}.
"""
import re
from datetime import date, datetime

from . import config

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _val(fields, key):
    f = fields.get(key)
    return None if f is None else f.get("value")


def _money(x):
    return f"{x:,.2f}" if isinstance(x, (int, float)) else str(x)


def run(fields: dict, line_items=None, today: date = None) -> dict:
    today = today or date.today()
    checks = []

    # 1. required fields
    missing = [k for k in config.REQUIRED_FIELDS if _val(fields, k) in (None, "")]
    checks.append({
        "code": "MISSING_FIELD",
        "ok": not missing,
        "detail": "All required fields present" if not missing else "Missing: " + ", ".join(missing),
        "missing": missing,
    })

    sub, cgst, sgst, igst, total = (_val(fields, k) for k in ("subtotal", "cgst", "sgst", "igst", "total"))
    cgst, sgst, igst = (x or 0.0 for x in (cgst, sgst, igst))

    # 2. line items sum to subtotal (only if we have line items, which come from the AI extractor)
    if line_items and sub is not None:
        s = sum((li.get("amount") or 0) for li in line_items)
        ok = abs(s - sub) <= config.ROUNDING_TOLERANCE
        checks.append({"code": "LINE_ITEMS_SUM", "ok": ok,
                       "detail": f"Line items sum {_money(s)} vs subtotal {_money(sub)}" + ("" if ok else f" (off by {_money(abs(s - sub))})")})

    # 3. subtotal + taxes = total
    if sub is not None and total is not None:
        expected = sub + cgst + sgst + igst
        ok = abs(expected - total) <= config.ROUNDING_TOLERANCE
        checks.append({"code": "ARITHMETIC_MISMATCH", "ok": ok,
                       "detail": f"{_money(sub)} + GST {_money(cgst + sgst + igst)} = {_money(expected)} vs stated total {_money(total)}" + ("" if ok else f" (off by {_money(abs(expected - total))})")})
    elif total is not None:
        checks.append({"code": "ARITHMETIC_MISMATCH", "ok": True, "detail": "Subtotal not available; arithmetic not checked", "skipped": True})

    # 4. GST structure: either CGST+SGST (equal) or IGST, never both
    has_intra = cgst > 0 or sgst > 0
    has_inter = igst > 0
    if has_intra and has_inter:
        checks.append({"code": "GST_INCONSISTENT", "ok": False, "detail": "Both CGST/SGST and IGST charged on one invoice"})
    elif has_intra and abs(cgst - sgst) > config.ROUNDING_TOLERANCE:
        checks.append({"code": "GST_INCONSISTENT", "ok": False, "detail": f"CGST {_money(cgst)} and SGST {_money(sgst)} should be equal"})
    elif has_intra or has_inter:
        kind = "intra-state (CGST + SGST)" if has_intra else "inter-state (IGST)"
        checks.append({"code": "GST_INCONSISTENT", "ok": True, "detail": f"GST structure consistent: {kind}"})
        # cross-check against the vendor's state code if we have a GSTIN
        g = _val(fields, "vendor_gstin")
        if g and GSTIN_RE.match(g):
            vendor_state = g[:2]
            expect_intra = vendor_state == config.BUYER_STATE_CODE
            if expect_intra != has_intra:
                checks.append({"code": "GST_INCONSISTENT", "ok": False,
                               "detail": f"Vendor GSTIN state {vendor_state} vs buyer {config.BUYER_STATE_CODE} implies {'intra' if expect_intra else 'inter'}-state, but invoice charges {'CGST/SGST' if has_intra else 'IGST'}"})
    else:
        checks.append({"code": "GST_INCONSISTENT", "ok": True, "detail": "No GST lines found; structure not checked", "skipped": True})

    # 5. GSTIN format
    g = _val(fields, "vendor_gstin")
    if g:
        ok = bool(GSTIN_RE.match(g))
        checks.append({"code": "GSTIN_INVALID", "ok": ok, "detail": f"Vendor GSTIN {g} " + ("is well-formed" if ok else "does not match the 15-character GSTIN format")})
    else:
        checks.append({"code": "GSTIN_INVALID", "ok": True, "detail": "No vendor GSTIN found; format not checked", "skipped": True})

    # 6. date sanity
    d = _val(fields, "invoice_date")
    if d:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            age = (today - dt).days
            if age < 0:
                checks.append({"code": "DATE_IMPLAUSIBLE", "ok": False, "detail": f"Invoice date {d} is in the future"})
            elif age > config.DATE_MAX_AGE_DAYS:
                checks.append({"code": "DATE_IMPLAUSIBLE", "ok": False, "detail": f"Invoice date {d} is {age} days old"})
            else:
                checks.append({"code": "DATE_IMPLAUSIBLE", "ok": True, "detail": f"Invoice date {d} is {age} days old"})
        except ValueError:
            checks.append({"code": "DATE_IMPLAUSIBLE", "ok": False, "detail": f"Invoice date '{d}' could not be parsed"})

    failed = [c for c in checks if not c["ok"]]
    return {
        "checks": checks,
        "failed_codes": sorted({c["code"] for c in failed}),
        "summary": "All checks passed" if not failed else f"{len(failed)} check(s) failed: " + ", ".join(sorted({c['code'] for c in failed})),
    }
