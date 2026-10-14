"""
Stages 4 and 5 - Match vendor, match purchase order.

Deterministic lookups against data/vendors.csv and data/purchase_orders.csv.
The PO ledger also counts invoices this system has already APPROVED (from run
history), so a split PO works across runs: approve part 1, and part 2 sees the
cumulative amount.

Design choices worth saying out loud:
- GSTIN match beats name match: it is a legal identifier, names are fuzzy.
- Inactive vendors are treated as not approved.
- A PO is inferred only when exactly one open PO for that vendor fits the
  amount within tolerance and the date window. Inferred POs always go to a human.
- Holds and rejects do not consume PO budget; approvals do.
"""
import difflib
import re
from datetime import date, datetime

import pandas as pd

from . import config

SUFFIXES = {"pvt", "private", "ltd", "limited", "llp", "co", "company", "inc", "corp", "corporation", "the"}


def _norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return " ".join(t for t in s.split() if t not in SUFFIXES)


def load_vendors() -> pd.DataFrame:
    df = pd.read_csv(config.DATA_DIR / "vendors.csv", dtype=str).fillna("")
    df["tolerance_pct"] = pd.to_numeric(df["tolerance_pct"], errors="coerce").fillna(config.DEFAULT_TOLERANCE_PCT)
    return df


def load_pos() -> pd.DataFrame:
    df = pd.read_csv(config.DATA_DIR / "purchase_orders.csv", dtype=str).fillna("")
    for c in ("po_amount", "invoiced_to_date"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _val(fields, key):
    f = fields.get(key)
    return None if f is None else f.get("value")


# ----------------------------------------------------------------- vendor
def match_vendor(fields: dict) -> dict:
    vendors = load_vendors()
    gstin = _val(fields, "vendor_gstin")
    name = _val(fields, "vendor_name")
    result = {"vendor_id": None, "legal_name": None, "tolerance_pct": config.DEFAULT_TOLERANCE_PCT, "status": None,
              "method": None, "score": None, "approved": False, "summary": ""}

    row = None
    if gstin:
        hit = vendors[vendors["gstin"].str.upper() == str(gstin).upper()]
        if not hit.empty:
            row, result["method"], result["score"] = hit.iloc[0], "gstin", 1.0

    if row is None and name:
        target = _norm_name(name)
        best, best_score = None, 0.0
        for _, v in vendors.iterrows():
            names = [v["legal_name"]] + [a for a in v["aliases"].split("|") if a]
            for cand in names:
                score = difflib.SequenceMatcher(None, target, _norm_name(cand)).ratio()
                if score > best_score:
                    best, best_score = v, score
        if best is not None and best_score >= config.VENDOR_MATCH_THRESHOLD:
            row, result["method"], result["score"] = best, "name", round(best_score, 2)
        else:
            result["score"] = round(best_score, 2)
            result["summary"] = (f"No approved vendor matches '{name}' (best similarity {best_score:.2f}, need {config.VENDOR_MATCH_THRESHOLD:.2f})")

    if row is not None:
        result.update(vendor_id=row["vendor_id"], legal_name=row["legal_name"], tolerance_pct=float(row["tolerance_pct"]),
                      status=row["status"], approved=(row["status"] == "approved"))
        how = "GSTIN" if result["method"] == "gstin" else f"name similarity {result['score']:.2f}"
        if result["approved"]:
            result["summary"] = f"{row['legal_name']} ({row['vendor_id']}) matched by {how}; tolerance {result['tolerance_pct']:g}%"
        else:
            result["summary"] = f"{row['legal_name']} ({row['vendor_id']}) matched by {how} but status is '{row['status']}'"
    elif not name and not gstin:
        result["summary"] = "No vendor name or GSTIN extracted, so nothing to match"
    return result


# ----------------------------------------------------------------- purchase order
def match_po(fields: dict, vendor: dict, ledger_extra: dict, today: date = None) -> dict:
    """ledger_extra: {po_number: amount already approved by this system}, from store.po_ledger()."""
    today = today or date.today()
    pos = load_pos()
    total = _val(fields, "total")
    ref = _val(fields, "po_reference")
    inv_date = _val(fields, "invoice_date")
    tol = float(vendor.get("tolerance_pct") or config.DEFAULT_TOLERANCE_PCT)

    result = {"po_number": None, "found": False, "method": None, "po_vendor_id": None, "po_amount": None,
              "invoiced_before": None, "remaining": None, "cumulative": None, "variance_abs": None, "variance_pct": None,
              "po_status": None, "vendor_matches": None, "tolerance_pct": tol, "candidates": [], "summary": ""}

    def fill(row, method):
        before = float(row["invoiced_to_date"]) + float(ledger_extra.get(row["po_number"], 0.0))
        amt = float(row["po_amount"])
        cum = before + (float(total) if total is not None else 0.0)
        result.update(po_number=row["po_number"], found=True, method=method, po_vendor_id=row["vendor_id"], po_amount=amt,
                      invoiced_before=round(before, 2), remaining=round(amt - before, 2), cumulative=round(cum, 2),
                      variance_abs=round(cum - amt, 2), variance_pct=round((cum - amt) / amt * 100, 2) if amt else None,
                      po_status=row["status"], vendor_matches=(vendor.get("vendor_id") == row["vendor_id"]) if vendor.get("vendor_id") else None,
                      description=row["description"])

    if ref:
        hit = pos[pos["po_number"].str.upper() == str(ref).upper()]
        if hit.empty:
            result["summary"] = f"Invoice cites {ref}, which is not in the PO register"
            return result
        fill(hit.iloc[0], "explicit")
    else:
        # infer: open POs for this vendor, within date window, whose remaining amount fits the invoice within tolerance
        if not vendor.get("vendor_id") or total is None:
            result["summary"] = "No PO reference on the invoice, and not enough information to infer one"
            return result
        cands = pos[(pos["vendor_id"] == vendor["vendor_id"]) & (pos["status"] == "open")]
        fits = []
        for _, row in cands.iterrows():
            try:
                po_date = datetime.strptime(row["po_date"], "%Y-%m-%d").date()
                ref_date = datetime.strptime(inv_date, "%Y-%m-%d").date() if inv_date else today
                if (ref_date - po_date).days > config.PO_INFER_WINDOW_DAYS or po_date > ref_date:
                    continue
            except ValueError:
                pass
            before = float(row["invoiced_to_date"]) + float(ledger_extra.get(row["po_number"], 0.0))
            remaining = float(row["po_amount"]) - before
            if remaining <= 0:
                continue
            if abs(float(total) - remaining) <= remaining * tol / 100 or float(total) <= remaining:
                fits.append(row)
        result["candidates"] = [r["po_number"] for r in fits]
        if len(fits) == 1:
            fill(fits[0], "inferred")
        else:
            result["summary"] = ("No PO reference on the invoice; "
                                 + ("no open PO for this vendor fits the amount" if not fits else f"{len(fits)} open POs could fit ({', '.join(result['candidates'])}), so none chosen"))
            return result

    r = result
    how = "stated on the invoice" if r["method"] == "explicit" else "inferred (not stated on the invoice)"
    v = f"{r['variance_pct']:+.2f}%" if r["variance_pct"] is not None else "n/a"
    r["summary"] = (f"{r['po_number']} {how}: PO {r['po_amount']:,.2f}, already invoiced {r['invoiced_before']:,.2f}, "
                    f"this invoice {float(total):,.2f} → cumulative {r['cumulative']:,.2f} ({v} vs PO)") if total is not None else f"{r['po_number']} {how}; invoice total unknown"
    return r
