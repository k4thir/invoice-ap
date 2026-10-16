"""
Diagnose the AI providers with the keys in .env: one Groq text call, one Gemini text call,
one Gemini call with the sample scan attached as a PDF. Prints the raw error if any fails.

    python tools/check_ai.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from pipeline import extract_ai  # noqa: E402

gk, gm = os.environ.get("GROQ_API_KEY", ""), os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
ak, am = os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
print(f"AI_PROVIDER={os.environ.get('AI_PROVIDER')}  GROQ key={'set' if gk else 'MISSING'} model={gm}  GEMINI key={'set' if ak else 'MISSING'} model={am}\n")

sys_prompt = 'Return ONLY JSON: {"ok": true, "model_sees": "<one word describing the input>"}'

if gk:
    try:
        print("Groq text  :", extract_ai._call_groq(sys_prompt, "hello", gm, gk)[:120])
    except Exception as e:  # noqa: BLE001
        print("Groq text  : FAILED", type(e).__name__, str(e)[:300])
else:
    print("Groq text  : skipped (no key)")

if ak:
    for label, kwargs in (("Gemini text", {}),
                          ("Gemini PDF ", {"pdf_bytes": (ROOT / "data/samples/inv04_pune_packaging_scanned.pdf").read_bytes()})):
        try:
            print(f"{label}:", extract_ai._call_gemini(sys_prompt, "describe the input", am, ak, **kwargs)[:120],
                  "| model in use:", extract_ai.gemini_model_in_use())
        except urllib.error.HTTPError as e:
            print(f"{label}: FAILED HTTP {e.code}", e.read().decode("utf-8", "replace")[:600])
        except Exception as e:  # noqa: BLE001
            print(f"{label}: FAILED", type(e).__name__, str(e)[:300])
    try:
        names = extract_ai._list_gemini_models(ak)
        print("\nModels this key can call (generateContent):", ", ".join(n for n in names if "flash" in n or "pro" in n)[:600])
    except urllib.error.HTTPError as e:
        print("\nListing models FAILED HTTP", e.code, e.read().decode("utf-8", "replace")[:300])
else:
    print("Gemini     : skipped (no key)")
