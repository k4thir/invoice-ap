"""
Stage 7 - Record.

Day 1: append each run to data/runs.jsonl and read it back for the dashboard.
Day 2: add sync to a private Hugging Face Dataset so history survives Space restarts,
       and load bundled seed runs so the dashboard is never empty.
"""
import json
from pathlib import Path

from . import config


def _path() -> Path:
    config.RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    return config.RUNS_FILE


def save(record: dict) -> None:
    slim = dict(record)
    # keep the raw text but cap it so the history file stays small
    if isinstance(slim.get("text"), str) and len(slim["text"]) > 6000:
        slim["text"] = slim["text"][:6000] + "\n...[truncated]"
    with _path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(slim, ensure_ascii=False) + "\n")


def load_all() -> list:
    p = _path()
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


def clear() -> None:
    p = _path()
    if p.exists():
        p.unlink()
