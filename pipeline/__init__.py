"""
The pipeline. One invoice in, one run record out.

run() is a generator so the UI can show each stage as it finishes:
    for event in pipeline.run(pdf_bytes, filename):
        if event["type"] == "stage": ... update the stage log ...
        elif event["type"] == "done": record = event["record"]

Stages (day 1 status in brackets):
  1 ingest        [real]   text layer or OCR
  2 extract       [rules real, AI stub -> day 2]
  3 validate      [real]
  4 match_vendor  [stub -> day 2]
  5 match_po      [stub -> day 2]
  6 decide        [stub -> day 2]
  7 record        [real, local file only; HF Dataset sync -> day 2]
"""
import time
import uuid
from datetime import datetime, timezone

from . import config, ingest, extract_rules, validate, store

STAGES = [
    ("ingest", "Read the PDF"),
    ("extract", "Extract fields"),
    ("validate", "Check the numbers"),
    ("match_vendor", "Match vendor"),
    ("match_po", "Match purchase order"),
    ("decide", "Decide"),
    ("record", "Record the run"),
]


def _stage(name, status, summary, ms, detail=None):
    return {"type": "stage", "name": name, "status": status, "summary": summary, "ms": ms, "detail": detail or {}}


def _merge_rules_only(rules_fields):
    """Day 1 merge: rules are the only source. Day 2 replaces this with merge.py."""
    merged = {}
    for key in config.FIELDS:
        f = rules_fields.get(key)
        if f:
            merged[key] = {"value": f["value"], "source": "rules", "confidence": "medium", "evidence": f["evidence"]}
    return merged


def run(data: bytes, filename: str):
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
        ev = _stage(name, status, summary, int((time.time() - t0) * 1000), detail)
        record["stages"].append({k: ev[k] for k in ("name", "status", "summary", "ms")})
        return ev

    # 1 ingest
    t0 = time.time()
    try:
        ing = ingest.run(data, filename)
    except Exception as e:  # unreadable file
        yield emit("ingest", "failed", f"Could not read the file: {e}", t0)
        record["decision"] = {"status": "Hold", "codes": ["UNREADABLE_FILE"], "next_action": "Open the file manually; it may be corrupt or not a PDF."}
        record["elapsed_ms"] = int((time.time() - started) * 1000)
        yield {"type": "done", "record": record}
        return
    record["ingest"] = {k: ing[k] for k in ("file_hash", "size_bytes", "path", "pages", "ocr_confidence")}
    record["text"] = ing["text"]
    yield emit("ingest", "ok" if ing["path"] == "text_layer" else "warn", ing["summary"], t0,
               {"path": ing["path"], "pages": ing["pages"]})

    # 2 extract (rules now, AI on day 2)
    t0 = time.time()
    rules = extract_rules.run(ing["text"])
    record["extract"] = {
        "rules": rules["fields"],
        "ai": None,
        "ai_status": "not_wired_day_2",
        "merged": _merge_rules_only(rules["fields"]),
        "line_items": [],
    }
    status = "ok" if not rules["missing"] else "warn"
    yield emit("extract", status, rules["summary"] + ". AI extractor arrives on day 2.", t0,
               {"found": rules["found"], "missing": rules["missing"]})

    # 3 validate
    t0 = time.time()
    val = validate.run(record["extract"]["merged"], line_items=record["extract"]["line_items"])
    record["validate"] = val
    yield emit("validate", "ok" if not val["failed_codes"] else "warn", val["summary"], t0,
               {"failed": val["failed_codes"]})

    # 4-6 stubs
    for name, msg in (("match_vendor", "Vendor matching arrives on day 2"),
                      ("match_po", "PO matching arrives on day 2"),
                      ("decide", "Decision rules arrive on day 2")):
        t0 = time.time()
        yield emit(name, "skipped", msg, t0)

    record["decision"] = {
        "status": "Not decided",
        "codes": val["failed_codes"],
        "next_action": "Day 1 build: extraction and validation only. Matching and the decision rules are wired on day 2.",
    }

    # 7 record
    t0 = time.time()
    record["elapsed_ms"] = int((time.time() - started) * 1000)
    store.save(record)
    yield emit("record", "ok", f"Run {run_id} saved to history ({record['elapsed_ms']} ms total)", t0)
    yield {"type": "done", "record": record}
