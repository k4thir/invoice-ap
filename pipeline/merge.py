"""
Stage 2c - Merge.

Two extractors looked at the same text. For each field:
  both found it and agree      -> confidence high,   source "both"
  only one found it            -> confidence medium, source "rules" or "ai"
  both found it and disagree   -> confidence low,    we pick one and record the conflict:
        text fields (names, numbers-as-identifiers, dates): take the AI value, it reads layout better
        amounts: take the rules value, it is anchored to a printed label; validation will arbitrate
The merged record is what every later stage reads. Nothing is dropped: the
original candidates stay in the run record for the human to see.
"""
import difflib
import re

from . import config

TEXT_FIELDS = {"vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "po_reference"}


def _norm_text(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _agree(key, a, b):
    if key in config.AMOUNT_FIELDS:
        try:
            return abs(float(a) - float(b)) <= config.ROUNDING_TOLERANCE
        except (TypeError, ValueError):
            return False
    if key == "vendor_name":
        return difflib.SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio() >= 0.85
    return _norm_text(a) == _norm_text(b)


def run(rules_fields: dict, ai_result: dict) -> dict:
    ai_ok = ai_result.get("status") == "ok"
    ai_fields = ai_result.get("fields", {}) if ai_ok else {}
    merged, conflicts = {}, []
    counts = {"both": 0, "rules": 0, "ai": 0, "conflict": 0}

    for key in config.FIELDS:
        r, a = rules_fields.get(key), ai_fields.get(key)
        if r and a:
            if _agree(key, r["value"], a["value"]):
                value = a["value"] if key == "vendor_name" else r["value"]  # AI casing for names, rules otherwise (identical anyway)
                merged[key] = {"value": value, "source": "both", "confidence": "high", "evidence": r.get("evidence") or a.get("evidence")}
                counts["both"] += 1
            else:
                prefer_ai = key in TEXT_FIELDS
                chosen, other = (a, r) if prefer_ai else (r, a)
                merged[key] = {"value": chosen["value"], "source": "ai" if prefer_ai else "rules", "confidence": "low",
                               "evidence": chosen.get("evidence"), "conflict": {"rules": r["value"], "ai": a["value"]}}
                conflicts.append({"field": key, "rules": r["value"], "ai": a["value"], "kept": "ai" if prefer_ai else "rules"})
                counts["conflict"] += 1
        elif r:
            merged[key] = {"value": r["value"], "source": "rules", "confidence": "medium", "evidence": r.get("evidence")}
            counts["rules"] += 1
        elif a:
            merged[key] = {"value": a["value"], "source": "ai", "confidence": "medium", "evidence": a.get("evidence")}
            counts["ai"] += 1

    found = [k for k in config.FIELDS if k in merged]
    missing = [k for k in config.FIELDS if k not in merged and k not in ('cgst', 'sgst', 'igst')]
    if not any(k in merged for k in ('cgst', 'sgst', 'igst')):
        missing.append('gst lines')
    ai_only = [k for k, v in merged.items() if v["source"] == "ai" and v["confidence"] == "medium"]

    if ai_ok:
        summary = (f"Rules found {len(rules_fields)}, AI found {len(ai_fields)}; {counts['both']} agree"
                   + (f", {counts['conflict']} conflict" if counts["conflict"] else "")
                   + (f"; filled by AI alone: {', '.join(ai_only)}" if ai_only else ""))
    else:
        summary = f"Rules found {len(rules_fields)} of {len(config.FIELDS)}; AI unavailable, so rules stand alone"
    if missing:
        summary += f"; still missing {', '.join(missing)}"

    return {
        "fields": merged,
        "line_items": ai_result.get("line_items", []) if ai_ok else [],
        "conflicts": conflicts,
        "counts": counts,
        "found": found,
        "missing": missing,
        "ai_status": ai_result.get("status"),
        "summary": summary,
    }
