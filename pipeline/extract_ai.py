"""
Stage 2b - AI extraction.

One call per invoice: the invoice text goes in, a JSON object with our fields
comes back. The model is asked to return null for anything it cannot see and
never to compute or guess. Its output is treated as a candidate, not a fact:
merge.py reconciles it with the rule extractor and validate.py checks the
arithmetic, so a wrong value is caught rather than paid.

Provider: AI_PROVIDER=groq (default) or gemini. If the primary fails after
retries and the other provider's key exists, we flip to it. If nothing works,
we return status="unavailable" and the pipeline continues on rules alone.

Configuration (environment variables; Streamlit secrets are copied into the
environment by app.py):
  AI_PROVIDER      groq | gemini | none
  GROQ_API_KEY     GROQ_MODEL     (e.g. openai/gpt-oss-120b)
  GEMINI_API_KEY   GEMINI_MODEL   (defaults to gemini-2.5-flash)
"""
import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime

from . import config

SYSTEM_PROMPT = f"""You extract fields from Indian GST tax invoices. The text may come from OCR and contain small errors.
Return ONLY a JSON object. No prose, no markdown fences.

Keys (all required, use null when the value is not present in the text):
  vendor_name      the party ISSUING the invoice. The buyer is "{config.BUYER_NAME}" (GSTIN {config.BUYER_GSTIN}); never return the buyer as vendor.
  vendor_gstin     the issuer's 15-character GSTIN, uppercase, exactly as printed
  invoice_number   the invoice/document/bill number exactly as printed (e.g. "SKF/26-27/0912")
  invoice_date     YYYY-MM-DD
  po_reference     the buyer's purchase order number (e.g. "PO-1048")
  subtotal         taxable value before GST, as a number
  cgst, sgst, igst each as a number, 0 if that tax is not charged
  total            the final payable amount, as a number
  line_items       array of {{"description","hsn","quantity","rate","amount"}}; if goods are bundled into one line, return that one line
  evidence         object mapping each non-null key above (except line_items) to the short text snippet it was read from

Rules:
- Never guess, infer or calculate a value that is not printed. If the invoice number is blank, invoice_number is null.
- Amounts are plain numbers: "1,50,000.00" -> 150000.00, "INR 118,000.00" -> 118000.00. No symbols, no separators.
- "Central Tax" means CGST, "State Tax" means SGST, "Integrated Tax" means IGST.
- Labels vary: "Document No.", "Inv #", "Bill No" are all invoice numbers; "Dated", "Date", "Invoice Date" are all dates; "Amount Payable", "Grand Total", "Total Payable" are all the total.
"""

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%Y/%m/%d"]


# ----------------------------------------------------------------- helpers
def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def _to_number(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[^\d.\-]", "", str(x))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _to_iso(x):
    if not x:
        return None
    s = str(x).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse(content: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in model output")
    return json.loads(content[start:end + 1])


def _normalise(raw: dict) -> tuple:
    """Turn the model's JSON into our {field: {value, evidence}} shape plus line items."""
    ev = raw.get("evidence") or {}
    fields = {}

    def put(key, value):
        if value in (None, "", []):
            return
        fields[key] = {"value": value, "evidence": str(ev.get(key, ""))[:120]}

    vn = raw.get("vendor_name")
    if vn and config.BUYER_NAME.lower() not in str(vn).lower():
        put("vendor_name", str(vn).strip())
    g = raw.get("vendor_gstin")
    if g:
        g = re.sub(r"\s+", "", str(g)).upper()
        if g != config.BUYER_GSTIN:
            put("vendor_gstin", g)
    inv = raw.get("invoice_number")
    if inv and re.search(r"\d", str(inv)):
        put("invoice_number", str(inv).strip())
    put("invoice_date", _to_iso(raw.get("invoice_date")))
    po = raw.get("po_reference")
    if po:
        m = re.search(r"PO-?\s?\d{3,6}", str(po), re.I)
        put("po_reference", ("PO-" + re.sub(r"\D", "", m.group(0))) if m else str(po).strip())
    for key in ("subtotal", "cgst", "sgst", "igst", "total"):
        n = _to_number(raw.get(key))
        if n is not None and not (key in ("cgst", "sgst", "igst") and n == 0):
            put(key, round(n, 2))

    items = []
    for li in raw.get("line_items") or []:
        if not isinstance(li, dict):
            continue
        items.append({
            "description": str(li.get("description") or "").strip(),
            "hsn": str(li.get("hsn") or "").strip(),
            "quantity": _to_number(li.get("quantity")),
            "rate": _to_number(li.get("rate")),
            "amount": _to_number(li.get("amount")),
        })
    return fields, items


# ----------------------------------------------------------------- providers
def _call_groq(text: str, model: str, key: str) -> str:
    from groq import Groq  # imported lazily so the app runs without the package when AI is off
    client = Groq(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": "Invoice text:\n\n" + text}],
        temperature=0,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


def _call_gemini(text: str, model: str, key: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": "Invoice text:\n\n" + text}]}],
        "generationConfig": {"temperature": 0, "response_mime_type": "application/json", "maxOutputTokens": 1500},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _is_retryable(err) -> bool:
    code = getattr(err, "status_code", None) or getattr(err, "code", None)
    msg = str(err).lower()
    return code in (429, 500, 502, 503, 504) or "rate limit" in msg or "429" in msg or "timed out" in msg


def _attempt(provider: str, text: str):
    if provider == "groq":
        key, model = _env("GROQ_API_KEY"), _env("GROQ_MODEL", "openai/gpt-oss-120b")
        if not key:
            raise RuntimeError("GROQ_API_KEY not set")
        return _call_groq(text, model, key), model
    if provider == "gemini":
        key, model = _env("GEMINI_API_KEY"), _env("GEMINI_MODEL", "gemini-2.5-flash")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        return _call_gemini(text, model, key), model
    raise RuntimeError(f"unknown provider {provider}")


def providers_in_order():
    primary = _env("AI_PROVIDER", "groq").lower()
    if primary == "none":
        return []
    order = [primary] + [p for p in ("groq", "gemini") if p != primary]
    return [p for p in order if _env(f"{p.upper()}_API_KEY")]


# ----------------------------------------------------------------- entry point
def run(text: str, max_retries: int = 2) -> dict:
    """Returns {"status": "ok"|"unavailable", "provider", "model", "ms", "fields", "line_items", "raw", "error", "attempts"}."""
    t0 = time.time()
    out = {"status": "unavailable", "provider": None, "model": None, "ms": 0, "fields": {}, "line_items": [], "raw": None, "error": None, "attempts": []}
    order = providers_in_order()
    if not order:
        out["error"] = "No AI provider configured (set AI_PROVIDER and a key)"
        out["ms"] = int((time.time() - t0) * 1000)
        return out

    text = text[:12000]  # more than enough for an invoice; keeps tokens predictable
    for provider in order:
        for attempt in range(1, max_retries + 2):
            try:
                content, model = _attempt(provider, text)
                raw = _parse(content)
                fields, items = _normalise(raw)
                out.update(status="ok", provider=provider, model=model, fields=fields, line_items=items, raw=raw, error=None)
                out["attempts"].append({"provider": provider, "attempt": attempt, "result": "ok"})
                out["ms"] = int((time.time() - t0) * 1000)
                return out
            except Exception as e:  # noqa: BLE001 - any failure here must degrade, not crash
                out["attempts"].append({"provider": provider, "attempt": attempt, "result": f"{type(e).__name__}: {str(e)[:160]}"})
                out["error"] = f"{provider}: {type(e).__name__}: {str(e)[:200]}"
                if _is_retryable(e) and attempt <= max_retries:
                    time.sleep(1.5 * attempt)
                    continue
                break  # non-retryable or out of retries -> next provider
    out["ms"] = int((time.time() - t0) * 1000)
    return out
