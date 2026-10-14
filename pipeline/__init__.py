"""
The pipeline. One invoice in, one run record out.

run() is a generator so the UI can show each stage as it finishes:
    for event in pipeline.run(pdf_bytes, filename):
        if event["type"] == "stage": ... update the stage log ...
        elif event["type"] == "done": record = event["record"]

Stages:
  1 ingest        text layer, or OCR when there is none
  2 extract       rules + AI in parallel, then merge            <- the only stage that uses a model
  3 validate      arithmetic, GST structure, GSTIN format, dates, required fields
  4 match_vendor  approved-vendor register (GSTIN, then fuzzy name + aliases)
  5 match_po      PO register + what this system already approved
  6 decide        ordered rules -> Approve / Hold / Reject + next action
  7 record        append to history (and mirror it, if configured)
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import config, ingest, extract_rules, extract_ai, merge, validate, match, decide, store

STAGES = [
    ("ingest", "Read the PDF"),
    ("extract", "Extract fields"),
    ("validate", "Check the numbers"),
    ("match_vendor", "Match vendor"),
    ("match_po", "Match purchase order"),
    ("decide", "Decide"),
    ("record", "Record the run"),
]


def run(data: bytes, filename: str, use_ai: bool = True):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    started = time.time()
    record = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filename": filename,
        "stages": [],
        "decision": None,
    }

    def emit(name, status, summary, t0, detail=None):
        ev = {"type": "stage", "name": name, "status": status, "summary": summary,
              "ms": int((time.time() - t0) * 1000), "detail": detail or {}}
        record["stages"].append({k: ev[k] for k in ("name", "status", "summary", "ms")})
        return ev

    # ---- 1 ingest
    t0 = time.time()
    try:
        ing = ingest.run(data, filename)
    except Exception as e:  # noqa: BLE001 - unreadable or non-PDF upload
        yield emit("ingest", "failed", f"Could not read the file: {type(e).__name__}: {e}", t0)
        record["decision"] = {"status": "Hold", "primary_code": "UNREADABLE_FILE", "codes": ["UNREADABLE_FILE"],
                              "next_action": "Open the file manually; it may be corrupt, password-protected or not a PDF.", "explanation": []}
        record["elapsed_ms"] = int((time.time() - started) * 1000)
        store.save(record)
        yield {"type": "done", "record": record}
        return
    record["ingest"] = {k: ing[k] for k in ("file_hash", "size_bytes", "path", "pages", "ocr_confidence")}
    record["text"] = ing["text"]
    yield emit("ingest", "ok" if ing["path"] == "text_layer" else "warn", ing["summary"], t0,
               {"path": ing["path"], "pages": ing["pages"]})

    # ---- 2 extract: rules and AI run side by side, then merge
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_rules = pool.submit(extract_rules.run, ing["text"])
        f_ai = pool.submit(extract_ai.run, ing["text"]) if use_ai else None
        rules = f_rules.result()
        ai = f_ai.result() if f_ai else {"status": "unavailable", "error": "AI disabled for this run", "fields": {}, "line_items": [], "provider": None, "model": None, "ms": 0, "attempts": []}
    merged = merge.run(rules["fields"], ai)
    record["extract"] = {
        "rules": rules["fields"],
        "ai": ai["fields"],
        "ai_status": ai["status"],
        "ai_provider": ai.get("provider"),
        "ai_model": ai.get("model"),
        "ai_ms": ai.get("ms"),
        "ai_error": ai.get("error"),
        "ai_attempts": ai.get("attempts", []),
        "merged": merged["fields"],
        "line_items": merged["line_items"],
        "conflicts": merged["conflicts"],
    }
    if ai["status"] == "ok":
        status = "ok" if not merged["missing"] and not merged["conflicts"] else "warn"
        summary = merged["summary"] + f" · {ai.get('provider')} / {ai.get('model')} in {ai.get('ms')} ms"
    else:
        status = "warn"
        summary = merged["summary"] + f" · AI_UNAVAILABLE ({ai.get('error')})"
    yield emit("extract", status, summary, t0, {"found": merged["found"], "missing": merged["missing"]})

    # ---- 3 validate
    t0 = time.time()
    val = validate.run(merged["fields"], line_items=merged["line_items"])
    record["validate"] = val
    yield emit("validate", "ok" if not val["failed_codes"] else "warn", val["summary"], t0, {"failed": val["failed_codes"]})

    # ---- 4 vendor
    t0 = time.time()
    vendor = match.match_vendor(merged["fields"])
    record["vendor"] = vendor
    yield emit("match_vendor", "ok" if vendor["approved"] else "warn", vendor["summary"], t0)

    # ---- 5 purchase order
    t0 = time.time()
    po = match.match_po(merged["fields"], vendor, store.po_ledger())
    record["po"] = po
    po_ok = po["found"] and po.get("method") == "explicit" and po.get("vendor_matches") is not False and po.get("po_status") == "open"
    yield emit("match_po", "ok" if po_ok else "warn", po["summary"], t0)

    # ---- 6 decide
    t0 = time.time()
    dup = store.find_duplicate(vendor.get("vendor_id"),
                               (merged["fields"].get("vendor_name") or {}).get("value"),
                               (merged["fields"].get("invoice_number") or {}).get("value"),
                               ing["file_hash"])
    record["duplicate"] = dup
    decision = decide.run(merged["fields"], val, vendor, po, dup)
    record["decision"] = decision
    icon = {"Approve": "ok", "Hold": "warn", "Reject": "failed"}[decision["status"]]
    yield emit("decide", icon, f"{decision['status']} · {decision['primary_code']}", t0)

    # ---- 7 record
    t0 = time.time()
    record["elapsed_ms"] = int((time.time() - started) * 1000)
    store.save(record)
    sync = store.sync_status()
    where = "history + mirrored" if sync["configured"] and not sync.get("error") else "local history"
    yield emit("record", "ok", f"Run {run_id} saved to {where} ({record['elapsed_ms']} ms total)", t0)
    yield {"type": "done", "record": record}
