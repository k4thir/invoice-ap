"""
Merging rule and AI extractions under the fallback-first policy.

Two situations:

fill_gaps(merged, ai_fields)
    Text PDFs and good scans. Rules already populated what they could; the AI
    was asked only for the gaps. AI values are added as source "ai", confidence
    medium. Nothing the rules found is overwritten.

reconcile(rules_fields, ai_fields)
    Poor scans (OCR confidence below the threshold). The AI read the whole
    document because the OCR text itself is unreliable. Per field:
        both agree       -> high,   source "both"
        only AI          -> medium, source "ai"
        only rules       -> medium, source "rules"   (unverified, but a label was there)
        disagree         -> low,    keep the AI value, record the conflict
    On a poor scan the rules are the weaker witness, so conflicts go to the AI;
    validation (arithmetic) still has the final say.

base_confidence(path)
    What a rules-found field is worth on its own: high on a text layer,
    medium on OCR text.
"""
import difflib
import re

from . import config


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _agree(key, a, b):
    if key in config.AMOUNT_FIELDS:
        try:
            return abs(float(a) - float(b)) <= config.ROUNDING_TOLERANCE
        except (TypeError, ValueError):
            return False
    if key == "vendor_name":
        return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio() >= 0.85
    return _norm(a) == _norm(b)


def base_confidence(read_path: str) -> str:
    return "high" if read_path == "text_layer" else "medium"


def from_rules(rules_fields: dict, read_path: str, keys) -> dict:
    conf = base_confidence(read_path)
    return {k: {"value": rules_fields[k]["value"], "source": "rules", "confidence": conf, "evidence": rules_fields[k].get("evidence")}
            for k in keys if k in rules_fields}


def fill_gaps(merged: dict, ai_fields: dict, keys) -> list:
    """Add AI values for keys not already present. Returns the list of keys filled."""
    filled = []
    for k in keys:
        if k not in merged and k in ai_fields:
            merged[k] = {"value": ai_fields[k]["value"], "source": "ai", "confidence": "medium", "evidence": ai_fields[k].get("evidence")}
            filled.append(k)
    return filled


def reconcile(rules_fields: dict, ai_fields: dict, keys) -> tuple:
    """Full-read merge for poor scans. Returns (merged_subset, conflicts)."""
    merged, conflicts = {}, []
    for k in keys:
        r, a = rules_fields.get(k), ai_fields.get(k)
        if r and a:
            if _agree(k, r["value"], a["value"]):
                value = a["value"] if k == "vendor_name" else r["value"]
                merged[k] = {"value": value, "source": "both", "confidence": "high", "evidence": r.get("evidence") or a.get("evidence")}
            else:
                merged[k] = {"value": a["value"], "source": "ai", "confidence": "low", "evidence": a.get("evidence"),
                             "conflict": {"rules": r["value"], "ai": a["value"]}}
                conflicts.append({"field": k, "rules": r["value"], "ai": a["value"], "kept": "ai"})
        elif a:
            merged[k] = {"value": a["value"], "source": "ai", "confidence": "medium", "evidence": a.get("evidence")}
        elif r:
            merged[k] = {"value": r["value"], "source": "rules", "confidence": "medium", "evidence": r.get("evidence")}
    return merged, conflicts


def missing_of(merged: dict, keys) -> list:
    """Keys absent from merged, treating the three GST lines as one optional group."""
    missing = [k for k in keys if k not in merged and k not in ("cgst", "sgst", "igst")]
    if any(k in keys for k in ("cgst", "sgst", "igst")) and not any(k in merged for k in ("cgst", "sgst", "igst")):
        missing.append("gst lines")
    return missing
