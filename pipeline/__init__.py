"""
The pipeline. One invoice in, one run record out.

run() is a generator so the UI can show each stage as it finishes:
    for event in pipeline.run(pdf_bytes, filename, reference=...):
        if event["type"] == "stage": ... update the stage rail ...
        elif event["type"] == "done": record = event["record"]

Extraction policy (rules first, AI only for gaps):

  1 read       text layer, or OCR. OCR confidence decides the path below.
  2 identify   vendor name / GSTIN, invoice number, date, PO reference.
               Rules first. AI call only for the identity fields the rules missed.
               POOR SCAN (OCR confidence < 90%): the OCR text itself is suspect,
               so the AI reads the whole document once, now. With a Gemini key
               the page IMAGE goes to the vision model; otherwise (or if that
               fails) the OCR text goes to the text model. Rules cross-check.
  3 vendor     match against the vendor register (GSTIN, then fuzzy name + aliases)
  4 po         match against the PO register (stated, else inferred)
  5 amounts    subtotal, GST lines, total (and line items).
               Rules first. AI call only if rules left a gap AND at least one of
               vendor / PO matched the reference data. If neither matched, the
               rules' amounts are shown but no AI is spent: the invoice is
               heading for Reject/Hold on identity grounds regardless.
  6 check      arithmetic, GST structure, GSTIN format, dates, required fields
  7 decide     ordered rules -> Approve / Hold / Reject + next action
  8 record     history (+ mirror, if configured)

Maximum AI calls per invoice: 2 (identity gaps, amount gaps), or 1 (poor scan full read).
A clean text PDF the rules fully understand makes 0 calls.
"""
import time
import uuid
from datetime import datetime, timezone

from . import config, ingest, extract_rules, extract_ai, merge, validate, match, decide, store

STAGES = [
    ("read", "Read"),
    ("identify", "Identify"),
    ("vendor", "Match vendor"),
    ("po", "Match PO"),
    ("amounts", "Amounts"),
    ("check", "Check"),
    ("decide", "Decide"),
    ("record", "Record"),
]


def _ai_summary(res, filled):
    if res["status"] == "ok":
        got = ", ".join(filled) if filled else "nothing new"
        return f"AI ({res['provider']}, {res['ms']} ms) filled {got}"
    return f"AI unavailable ({res.get('error')})"


def run(data: bytes, filename: str, use_ai: bool = True, reference: dict = None):
    reference = reference or {}
    vendors_df, pos_df = reference.get("vendors"), reference.get("pos")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    started = time.time()
    record = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "filename": filename, "stages": [], "ai_calls": [], "policy": [], "decision": None}
    merged, conflicts, line_items = {}, [], []

    def emit(name, status, summary, t0, detail=None):
        ev = {"type": "stage", "name": name, "status": status, "summary": summary, "ms": int((time.time() - t0) * 1000), "detail": detail or {}}
        record["stages"].append({k: ev[k] for k in ("name", "status", "summary", "ms")})
        return ev

    def note(msg):
        record["policy"].append(msg)

    def ai(fields, want_items, purpose, image=None):
        res = extract_ai.run(ing["text"], fields=fields, want_line_items=want_items, image_png=image, purpose=purpose)
        if res.get("attempts"):  # only count calls that actually went to a provider
            record["ai_calls"].append({k: res[k] for k in ("purpose", "mode", "status", "provider", "model", "ms", "requested", "error")} | {"returned": sorted(res["fields"].keys())})
        return res

    # ---- 1 read
    t0 = time.time()
    try:
        ing = ingest.run(data, filename)
    except Exception as e:  # noqa: BLE001
        yield emit("read", "failed", f"Could not read the file: {type(e).__name__}: {e}", t0)
        record["decision"] = {"status": "Hold", "primary_code": "UNREADABLE_FILE", "codes": ["UNREADABLE_FILE"],
                              "next_action": "Open the file manually; it may be corrupt, password-protected or not a PDF.", "explanation": []}
        record["elapsed_ms"] = int((time.time() - started) * 1000)
        store.save(record)
        yield {"type": "done", "record": record}
        return
    record["ingest"] = {k: ing[k] for k in ("file_hash", "size_bytes", "path", "pages", "ocr_confidence")}
    record["text"] = ing["text"]
    conf = ing["ocr_confidence"]
    poor_scan = ing["path"] == "ocr" and conf is not None and conf < config.OCR_AI_THRESHOLD
    if ing["path"] == "text_layer":
        note("Text layer present: rules read it first; AI only for gaps.")
    elif poor_scan:
        note(f"Scan at {conf}% OCR confidence, below {config.OCR_AI_THRESHOLD:g}%: AI reads the whole document; rules cross-check.")
    else:
        note(f"Scan at {conf}% OCR confidence, at or above {config.OCR_AI_THRESHOLD:g}%: OCR text treated like a text layer; AI only for gaps.")
    yield emit("read", "ok" if ing["path"] == "text_layer" else "warn", ing["summary"], t0, {"path": ing["path"], "pages": ing["pages"]})

    rules = extract_rules.run(ing["text"])["fields"]
    record["extract"] = {"rules": rules, "ai": {}}

    # ---- 2 identify
    t0 = time.time()
    if poor_scan and use_ai:
        res = None
        if extract_ai.vision_available() and ing.get("page_image_png"):
            res = ai(config.FIELDS, True, "full read of a poor scan", ing["page_image_png"])
            if res["status"] != "ok":
                note(f"Vision read failed ({res.get('error')}); falling back to the OCR text.")
                res = None
        else:
            note("No Gemini key, so the page image cannot be sent to a vision model; the OCR text goes to the text model instead.")
        if res is None:
            res = ai(config.FIELDS, True, "full read of a poor scan (OCR text)")
        image_used = res.get("mode") == "image" and res["status"] == "ok"
        if res["status"] == "ok":
            record["extract"]["ai"].update(res["fields"])
            m, c = merge.reconcile(rules, res["fields"], config.FIELDS)
            merged.update(m)
            conflicts.extend(c)
            line_items = res["line_items"]
            agree = sum(1 for v in m.values() if v["source"] == "both")
            summary = (f"AI read the page image ({res['provider']}, {res['ms']} ms)" if image_used else f"AI read the OCR text ({res['provider']}, {res['ms']} ms)") \
                      + f"; rules agree on {agree}" + (f", {len(c)} conflict(s)" if c else "")
            note(("Vision model read the page image; " if image_used else "Text model read the OCR text; ") + f"rules from the OCR text cross-checked it: {agree} agree" + (f", {len(c)} differ (AI value kept, confidence low)." if c else "."))
        else:
            merged.update(merge.from_rules(rules, ing["path"], config.FIELDS))
            summary = f"Rules only: {_ai_summary(res, [])}"
            note("AI unavailable for the full read; rules stand alone and every gap becomes a Hold.")
    else:
        merged.update(merge.from_rules(rules, ing["path"], config.IDENTITY_FIELDS))
        gaps = [k for k in config.IDENTITY_FIELDS if k not in merged]
        # a missing GSTIN alone is not worth a call; a missing vendor, PO, invoice number or date is
        need_ai = any(k in gaps for k in ("vendor_name", "po_reference", "invoice_number", "invoice_date"))
        if gaps and need_ai and use_ai:
            res = ai(gaps, False, "identity gaps")
            record["extract"]["ai"].update(res["fields"])
            filled = merge.fill_gaps(merged, res["fields"], gaps)
            note(f"Rules missed {', '.join(gaps)} → AI asked for exactly those; " + (f"it returned {', '.join(filled) or 'none'}." if res['status'] == 'ok' else "AI unavailable, so they stay missing."))
            summary = f"Rules found {len(config.IDENTITY_FIELDS) - len(gaps)} of {len(config.IDENTITY_FIELDS)}; {_ai_summary(res, filled)}"
        elif gaps and not use_ai:
            note(f"Rules missed {', '.join(gaps)}; AI is off, so they stay missing.")
            summary = f"Rules found {len(config.IDENTITY_FIELDS) - len(gaps)} of {len(config.IDENTITY_FIELDS)}; AI off"
        else:
            note("Rules found every identity field → no AI call.")
            summary = f"Rules found all {len(config.IDENTITY_FIELDS)} identity fields; no AI needed"
    still = [k for k in ("vendor_name", "invoice_number", "invoice_date", "po_reference") if k not in merged]
    yield emit("identify", "ok" if not still else "warn", summary + (f"; still missing {', '.join(still)}" if still else ""), t0)

    # ---- 3 vendor
    t0 = time.time()
    vendor = match.match_vendor(merged, vendors_df)
    record["vendor"] = vendor
    yield emit("vendor", "ok" if vendor["approved"] else "warn", vendor["summary"], t0)

    # ---- 4 po (needs the total for cumulative maths; use the rules' total if we have it, refine after amounts)
    t0 = time.time()
    if not poor_scan:
        merged.update(merge.from_rules(rules, ing["path"], config.MONEY_FIELDS))
    po = match.match_po(merged, vendor, store.po_ledger(), pos_df)
    po_identified = po["found"] and po.get("method") in ("explicit", "inferred_exact")
    yield emit("po", "ok" if po_identified and po.get("vendor_matches") is not False and po.get("po_status") == "open" else "warn", po["summary"], t0)

    # ---- 5 amounts
    t0 = time.time()
    money_gaps = merge.missing_of(merged, config.MONEY_FIELDS)
    eligible = vendor["approved"] or po["found"]
    if poor_scan:
        summary = "Amounts came from the full read above" + (f"; still missing {', '.join(money_gaps)}" if money_gaps else "")
    elif money_gaps and eligible and use_ai:
        res = ai(config.MONEY_FIELDS, True, "amount gaps")
        record["extract"]["ai"].update(res["fields"])
        filled = merge.fill_gaps(merged, res["fields"], config.MONEY_FIELDS)
        line_items = res["line_items"]
        why = f"vendor matched ({vendor['vendor_id']})" if vendor["approved"] else f"PO matched ({po['po_number']})"
        note(f"Rules missed {', '.join(money_gaps)}; {why}, so the amounts are worth an AI call → " + (f"it returned {', '.join(filled) or 'none'} plus {len(line_items)} line item(s)." if res['status'] == 'ok' else "AI unavailable, so they stay missing."))
        summary = f"Rules found {sum(1 for k in config.MONEY_FIELDS if k in merged and merged[k]['source'] == 'rules')} of {len(config.MONEY_FIELDS)}; {_ai_summary(res, filled)}"
    elif money_gaps and not eligible:
        note(f"Rules missed {', '.join(money_gaps)}, but neither vendor nor PO matched the reference data → no AI spent on amounts; decision will rest on identity.")
        summary = f"Rules missed {', '.join(money_gaps)}; AI skipped because nothing matched the reference data"
    elif money_gaps:
        note(f"Rules missed {', '.join(money_gaps)}; AI is off.")
        summary = f"Rules missed {', '.join(money_gaps)}; AI off"
    else:
        note("Rules found every amount → no AI call.")
        summary = "Rules found all amounts; no AI needed"
    # the PO was identified before the amounts tier; recompute its arithmetic now that the total is known
    if merged.get("total"):
        po = match.match_po(merged, vendor, store.po_ledger(), pos_df)
    record["po"] = po
    record["extract"].update({"merged": merged, "line_items": line_items, "conflicts": conflicts,
                              "ai_status": "ok" if any(c["status"] == "ok" for c in record["ai_calls"]) else ("none" if not record["ai_calls"] else "unavailable")})
    yield emit("amounts", "ok" if not merge.missing_of(merged, config.MONEY_FIELDS) else "warn", summary, t0)

    # ---- 6 check
    t0 = time.time()
    val = validate.run(merged, line_items=line_items)
    record["validate"] = val
    yield emit("check", "ok" if not val["failed_codes"] else "warn", val["summary"], t0)

    # ---- 7 decide
    t0 = time.time()
    prior = store.find_prior(vendor.get("vendor_id"), (merged.get("vendor_name") or {}).get("value"),
                             (merged.get("invoice_number") or {}).get("value"), ing["file_hash"])
    dup = {"is_duplicate": True, **prior} if prior.get("found") and prior.get("status") == "Approve" else {"is_duplicate": False}
    record["duplicate"] = dup
    record["prior"] = prior if (prior.get("found") and not dup["is_duplicate"]) else {"found": False}
    if record["prior"]["found"]:
        note(f"Seen before: run {prior['run_id']} ended as {prior['status']}. Not a duplicate (nothing was paid), so it is re-evaluated and the earlier run is superseded.")
    decision = decide.run(merged, val, vendor, po, dup, record["prior"])
    record["decision"] = decision
    yield emit("decide", {"Approve": "ok", "Hold": "warn", "Reject": "failed"}[decision["status"]], f"{decision['status']}: {decision['primary_code']}", t0)

    # ---- 8 record
    t0 = time.time()
    record["elapsed_ms"] = int((time.time() - started) * 1000)
    record["ai_call_count"] = len(record["ai_calls"])
    store.save(record)
    if record["prior"]["found"]:
        store.mark_superseded(record["prior"]["run_id"], run_id)
    sync = store.sync_status()
    where = "history and mirror" if sync["configured"] and not sync.get("error") else "history"
    yield emit("record", "ok", f"Saved to {where}; {record['ai_call_count']} AI call(s); {record['elapsed_ms']} ms end to end", t0)
    yield {"type": "done", "record": record}
