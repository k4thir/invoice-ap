"""
Stage 7 - Record, and the memory the other stages read.

History:
  live runs   data/runs.jsonl, appended on every run. On a free host the disk
              resets on reboot, so if HF_TOKEN and HF_DATASET_REPO are set we
              mirror the file to a private Hugging Face Dataset after each run
              and pull it back on startup.

What later stages ask of history:
  po_ledger()       {po_number: amount approved by this system}  (approvals only)
  find_duplicate()  same vendor + invoice number, or same file hash, already processed
"""
import json
import os
import re
import threading
from pathlib import Path

from . import config

_lock = threading.Lock()
_sync_state = {"last": None, "error": None}


# ----------------------------------------------------------------- paths & config
def _runs_path() -> Path:
    p = Path(os.environ.get("INVOICE_AP_RUNS_FILE") or config.RUNS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _hf_cfg():
    token = (os.environ.get("HF_TOKEN") or "").strip()
    repo = (os.environ.get("HF_DATASET_REPO") or "").strip()
    return (token, repo) if token and repo else (None, None)


def sync_status() -> dict:
    token, repo = _hf_cfg()
    return {**_sync_state, "configured": bool(token and repo), "repo": repo}


# ----------------------------------------------------------------- HF mirror
def pull_from_hf() -> None:
    """On startup: if there is no local history but a mirror exists, fetch it."""
    token, repo = _hf_cfg()
    if not token or _runs_path().exists():
        return
    try:
        from huggingface_hub import hf_hub_download
        src = hf_hub_download(repo_id=repo, filename="runs.jsonl", repo_type="dataset", token=token)
        _runs_path().write_bytes(Path(src).read_bytes())
        _sync_state.update(last="pulled", error=None)
    except Exception as e:  # noqa: BLE001 - no mirror yet on first run is normal
        _sync_state.update(error=f"pull: {type(e).__name__}: {str(e)[:120]}")


def push_to_hf() -> None:
    token, repo = _hf_cfg()
    if not token:
        return
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
        api.create_repo(repo_id=repo, repo_type="dataset", private=True, exist_ok=True)
        if _runs_path().exists():
            api.upload_file(path_or_fileobj=str(_runs_path()), path_in_repo="runs.jsonl", repo_id=repo,
                            repo_type="dataset", commit_message="run history")
        _sync_state.update(last="pushed", error=None)
    except Exception as e:  # noqa: BLE001
        _sync_state.update(error=f"push: {type(e).__name__}: {str(e)[:120]}")


# ----------------------------------------------------------------- read / write
def save(record: dict) -> None:
    slim = dict(record)
    if isinstance(slim.get("text"), str) and len(slim["text"]) > 6000:
        slim["text"] = slim["text"][:6000] + "\n...[truncated]"
    with _lock:
        with _runs_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(slim, ensure_ascii=False, default=str) + "\n")
    push_to_hf()


def load_live() -> list:
    p = _runs_path()
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def load_all() -> list:
    """All recorded runs, oldest to newest."""
    return load_live()


def clear_live() -> None:
    p = _runs_path()
    if p.exists():
        p.unlink()
    token, _ = _hf_cfg()
    if token:
        # push an empty file so the mirror is cleared too
        _runs_path().write_text("", encoding="utf-8")
        push_to_hf()
        _runs_path().unlink()


# ----------------------------------------------------------------- memory for other stages
def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def po_ledger() -> dict:
    """Amount this system has already approved per PO, from live runs only."""
    ledger = {}
    for r in load_live():
        d = r.get("decision") or {}
        if r.get("superseded_by"):
            continue
        po = (r.get("po") or {}).get("po_number")
        total = (((r.get("extract") or {}).get("merged") or {}).get("total") or {}).get("value")
        if d.get("status") == "Approve" and po and isinstance(total, (int, float)):
            ledger[po] = ledger.get(po, 0.0) + float(total)
    return ledger


def find_prior(vendor_id, vendor_name, invoice_number, file_hash) -> dict:
    """
    The most recent earlier run for the same invoice (same file, or same vendor + invoice number).
    Returns {"found": bool, "status", "run_id", "when", "filename", "by", "superseded"}.
    Decision semantics live in the pipeline: an APPROVED prior is a duplicate (never pay twice);
    a HELD or REJECTED prior is superseded by the new evaluation.
    """
    best = None
    for r in load_live():
        if r.get("superseded_by"):
            continue
        ing = r.get("ingest") or {}
        by = None
        if file_hash and ing.get("file_hash") == file_hash:
            by = "file_hash"
        else:
            m = (r.get("extract") or {}).get("merged") or {}
            prev_inv = (m.get("invoice_number") or {}).get("value")
            if invoice_number and prev_inv and _norm(prev_inv) == _norm(invoice_number):
                prev_vendor_id = (r.get("vendor") or {}).get("vendor_id")
                prev_vendor_name = (m.get("vendor_name") or {}).get("value")
                same_vendor = (vendor_id and prev_vendor_id == vendor_id) or (
                    not vendor_id and _norm(prev_vendor_name)[:12] == _norm(vendor_name)[:12])
                if same_vendor:
                    by = "vendor+invoice_number"
        if by:
            best = {"found": True, "status": (r.get("decision") or {}).get("status"), "run_id": r["run_id"],
                    "when": r.get("started_at"), "filename": r.get("filename"), "by": by}
    return best or {"found": False}


def mark_superseded(old_run_id: str, new_run_id: str) -> None:
    """Rewrite history so the earlier run points at the one that replaced it."""
    p = _runs_path()
    if not p.exists():
        return
    rows = load_live()
    changed = False
    for r in rows:
        if r.get("run_id") == old_run_id and not r.get("superseded_by"):
            r["superseded_by"] = new_run_id
            changed = True
    if changed:
        with _lock:
            with p.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        push_to_hf()
