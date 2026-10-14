"""
Run all eight sample invoices in demo order and save the results as
data/seed_runs.json, so the dashboard shows a populated history on first visit.

Seeds are display-only: the app never counts them for duplicates or the PO
ledger, so a live demo starts from a clean slate even though the dashboard is full.

Run this ONCE on your own machine with your .env in place (so the seeds show the
AI extractor working):

    python tools/make_seed_runs.py

Then upload the new data/seed_runs.json with the rest of the project.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# isolate this run's history from the real one
tmp = Path(tempfile.mkdtemp()) / "seed_runs.jsonl"
os.environ["INVOICE_AP_RUNS_FILE"] = str(tmp)
os.environ.pop("HF_TOKEN", None)  # never mirror seed generation

import pipeline  # noqa: E402
from pipeline import config  # noqa: E402

ORDER = [
    "inv01_sk_fasteners_SKF-26-27-0912.pdf",
    "inv08_nexora_NXR-TI-4471.pdf",
    "inv04_pune_packaging_scanned.pdf",
    "inv05_bharat_steel_BST-0882.pdf",
    "inv06_bharat_steel_BST-0907.pdf",
    "inv07_sk_fasteners_resent.pdf",
    "inv03_deccan_DP-2609-121.pdf",
    "inv02_deccan_DP-2609-114.pdf",
]

records = []
for name in ORDER:
    data = (config.SAMPLES_DIR / name).read_bytes()
    rec = None
    for ev in pipeline.run(data, name):
        if ev["type"] == "stage":
            print(f"  {ev['status']:7s} {ev['name']:13s} {ev['summary'][:100]}")
        else:
            rec = ev["record"]
    d = rec["decision"]
    print(f"{name}: {d['status']} {d['codes']}\n")
    rec["seed"] = True
    if isinstance(rec.get("text"), str) and len(rec["text"]) > 4000:
        rec["text"] = rec["text"][:4000] + "\n...[truncated]"
    records.append(rec)

config.SEED_RUNS_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(f"Wrote {len(records)} seed runs to {config.SEED_RUNS_FILE}")
