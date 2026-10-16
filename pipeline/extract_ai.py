"""
AI extraction, used as a fallback.

The pipeline calls this only when the rule extractor leaves a gap (or when a
scan's OCR confidence is poor). Each call asks for a specific list of fields,
nothing more, so the model's job is as narrow as possible and its output is
treated as a candidate to be checked, never a decision.

  run(text, fields=[...], want_line_items=False)          text -> Groq (default) or Gemini
  run(text, fields=[...], pdf_bytes=<bytes>)              the original PDF -> Gemini (needs GEMINI_API_KEY); image_png as fallback

Configuration (environment; app.py copies Streamlit secrets into it):
  AI_PROVIDER      groq | gemini | none
  GROQ_API_KEY     GROQ_MODEL     default openai/gpt-oss-120b
  GEMINI_API_KEY   GEMINI_MODEL   default gemini-2.5-flash
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import config

FIELD_HELP = {
    "vendor_name": f'the party ISSUING the invoice. The buyer is "{config.BUYER_NAME}" (GSTIN {config.BUYER_GSTIN}); never return the buyer',
    "vendor_gstin": "the issuer's 15-character GSTIN exactly as printed, uppercase",
    "invoice_number": 'the invoice / document / bill number exactly as printed (e.g. "SKF/26-27/0912"). Labels vary: "Invoice No", "Inv #", "Document No.", "Bill No"',
    "invoice_date": 'the invoice date as YYYY-MM-DD. Labels vary: "Invoice Date", "Date", "Dated"',
    "po_reference": 'the buyer\'s purchase order number (e.g. "PO-1048"). Labels vary: "PO No", "P.O. Ref", "Purchase Order", "Ref PO"',
    "subtotal": 'taxable value before GST, as a number. Labels vary: "Sub Total", "Taxable Value", "Value of Supply"',
    "cgst": 'CGST amount as a number (0 if not charged). "Central Tax" means CGST',
    "sgst": 'SGST amount as a number (0 if not charged). "State Tax" means SGST',
    "igst": 'IGST amount as a number (0 if not charged). "Integrated Tax" means IGST',
    "total": 'the final payable amount as a number. Labels vary: "Grand Total", "Total Amount", "Total Payable", "Amount Payable"',
}

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%Y/%m/%d"]


def build_prompt(fields, want_line_items):
    lines = [f"  {k:15s} {FIELD_HELP[k]}" for k in fields]
    if want_line_items:
        lines.append('  line_items      array of {"description","hsn","quantity","rate","amount"}; if goods are bundled into one line, return that one line')
    lines.append("  evidence        object mapping each non-null key above (except line_items) to the short text snippet it was read from")
    return f"""You extract specific fields from an Indian GST tax invoice. The text may come from OCR and contain small errors.
Return ONLY a JSON object with exactly these keys (use null when a value is not present):
{chr(10).join(lines)}

Rules:
- Never infer or calculate a value that is not on the document. If a field is blank on the invoice, return null for it.
- If the invoice is handwritten or a poor scan, read it carefully as a person would and transcribe what is written; return null only when a value is truly illegible or absent.
- Amounts are plain numbers: "1,50,000.00" -> 150000.00, "INR 118,000.00" -> 118000.00. No symbols, no separators.
- Return only the keys listed. No prose, no markdown fences."""


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
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in model output")
    return json.loads(content[start:end + 1])


def _normalise(raw: dict, fields) -> tuple:
    ev = raw.get("evidence") or {}
    out = {}

    def put(key, value):
        if key in fields and value not in (None, "", []):
            out[key] = {"value": value, "evidence": str(ev.get(key, ""))[:120]}

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
        if isinstance(li, dict):
            items.append({"description": str(li.get("description") or "").strip(), "hsn": str(li.get("hsn") or "").strip(),
                          "quantity": _to_number(li.get("quantity")), "rate": _to_number(li.get("rate")), "amount": _to_number(li.get("amount"))})
    return out, items


# ----------------------------------------------------------------- providers
def _call_groq(system: str, user: str, model: str, key: str) -> str:
    from groq import Groq
    client = Groq(api_key=key)
    resp = client.chat.completions.create(
        model=model, temperature=0, max_tokens=1200, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return resp.choices[0].message.content or ""


_GEMINI_RESOLVED = {}  # configured name -> name that actually exists for this key
_GEMINI_THINKING_OK = {}  # model -> whether it accepts thinkingConfig


def _list_gemini_models(key: str) -> list:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=200"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
        data = json.loads(r.read().decode())
    out = []
    for m in data.get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(m["name"].split("/", 1)[-1])
    return out


def _pick_gemini_model(names: list) -> str:
    """Prefer the newest plain Flash model: no lite/image/tts/live/exp/audio variants."""
    def version(n):
        m = re.search(r"gemini-(\d+)(?:\.(\d+))?", n)
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)
    bad = ("lite", "image", "tts", "live", "exp", "audio", "thinking", "embedding", "preview")
    flash = [n for n in names if "flash" in n and not any(b in n for b in bad)]
    if not flash:
        flash = [n for n in names if "flash" in n and not any(b in n for b in bad[:5])]
    if not flash:
        flash = [n for n in names if n.startswith("gemini")]
    return sorted(flash, key=lambda n: (version(n), -len(n)), reverse=True)[0] if flash else ""


def resolve_gemini_model(configured: str, key: str) -> str:
    """Return a model name that exists for this key; fall back to discovery when the configured one 404s."""
    if configured in _GEMINI_RESOLVED:
        return _GEMINI_RESOLVED[configured]
    return configured


def _call_gemini(system: str, user: str, model: str, key: str, image_png: bytes = None, pdf_bytes: bytes = None) -> str:
    model = resolve_gemini_model(model, key)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    parts = [{"text": user}]
    attached = False
    if pdf_bytes and len(pdf_bytes) <= 15_000_000:
        parts.insert(0, {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode()}})
        attached = True
    elif image_png:
        mime = "image/png" if image_png[:4] == b"\x89PNG" else "image/jpeg"
        parts.insert(0, {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_png).decode()}})
        attached = True
    gen = {"temperature": 0, "response_mime_type": "application/json", "maxOutputTokens": 4096}
    if _GEMINI_THINKING_OK.get(model, True):
        # printed text needs no deliberation; a document image (handwriting, poor scans) benefits from more
        gen["thinkingConfig"] = {"thinkingLevel": "medium" if attached else "low"}
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"parts": parts}], "generationConfig": gen}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as err:
        if err.code == 400 and "thinkingConfig" in gen:
            # this model does not take a thinking level (older Flash versions): retry once without it
            _GEMINI_THINKING_OK[model] = False
            return _call_gemini(system, user, model, key, image_png, pdf_bytes)
        if err.code == 404 and model not in _GEMINI_RESOLVED.values():
            # the configured model does not exist for this key: discover one that does, remember it, retry once
            found = _pick_gemini_model(_list_gemini_models(key))
            if not found or found == model:
                raise
            _GEMINI_RESOLVED[model] = found
            return _call_gemini(system, user, model, key, image_png, pdf_bytes)
        raise
    return data["candidates"][0]["content"]["parts"][0]["text"]


def gemini_model_in_use() -> str:
    configured = _env("GEMINI_MODEL", "gemini-3.8-flash")
    return _GEMINI_RESOLVED.get(configured, configured)


def _is_retryable(err) -> bool:
    code = getattr(err, "status_code", None) or getattr(err, "code", None)
    msg = str(err).lower()
    return code in (429, 500, 502, 503, 504) or "rate limit" in msg or "429" in msg or "timed out" in msg


def providers_in_order():
    primary = _env("AI_PROVIDER", "groq").lower()
    if primary == "none":
        return []
    order = [primary] + [p for p in ("groq", "gemini") if p != primary]
    return [p for p in order if _env(f"{p.upper()}_API_KEY")]


def vision_available() -> bool:
    return bool(_env("GEMINI_API_KEY")) and _env("AI_PROVIDER", "groq").lower() != "none"


# ----------------------------------------------------------------- entry point
def run(text: str, fields=None, want_line_items=False, image_png: bytes = None, purpose: str = "", max_retries: int = 2, pdf_bytes: bytes = None) -> dict:
    """Returns {"status": ok|unavailable, "provider", "model", "ms", "fields", "line_items", "requested", "purpose", "mode", "error", "attempts"}."""
    fields = list(fields or config.FIELDS)
    t0 = time.time()
    out = {"status": "unavailable", "provider": None, "model": None, "ms": 0, "fields": {}, "line_items": [],
           "requested": fields, "purpose": purpose, "mode": "pdf" if pdf_bytes else ("image" if image_png else "text"), "error": None, "attempts": []}
    system = build_prompt(fields, want_line_items)
    user = ("Read the attached invoice." if (image_png or pdf_bytes) else "Invoice text:\n\n" + text[:12000])

    if image_png or pdf_bytes:
        order = ["gemini"] if vision_available() else []
        if not order:
            out["error"] = "Image reading needs GEMINI_API_KEY; not set"
    else:
        order = providers_in_order()
        if not order:
            out["error"] = "No AI provider configured (set AI_PROVIDER and a key)"

    for provider in order:
        for attempt in range(1, max_retries + 2):
            try:
                if provider == "groq":
                    model = _env("GROQ_MODEL", "openai/gpt-oss-120b")
                    content = _call_groq(system, user, model, _env("GROQ_API_KEY"))
                else:
                    model = _env("GEMINI_MODEL", "gemini-3.8-flash")
                    content = _call_gemini(system, user, model, _env("GEMINI_API_KEY"), image_png, pdf_bytes)
                    model = gemini_model_in_use()
                raw = _parse(content)
                got, items = _normalise(raw, fields)
                out.update(status="ok", provider=provider, model=model, fields=got, line_items=items if want_line_items else [], error=None)
                out["attempts"].append({"provider": provider, "attempt": attempt, "result": "ok"})
                out["ms"] = int((time.time() - t0) * 1000)
                return out
            except Exception as e:  # noqa: BLE001 - any failure must degrade, not crash
                detail = str(e)
                body = getattr(e, "read", None)
                if callable(body):  # urllib HTTPError: include the server's message, it names the real cause
                    try:
                        detail += " " + body().decode("utf-8", "replace")[:300]
                    except Exception:  # noqa: BLE001
                        pass
                out["attempts"].append({"provider": provider, "attempt": attempt, "result": f"{type(e).__name__}: {detail[:300]}"})
                out["provider"] = provider
                out["error"] = f"{provider}: {type(e).__name__}: {detail[:400]}"
                if _is_retryable(e) and attempt <= max_retries:
                    time.sleep(1.5 * attempt)
                    continue
                break
    out["ms"] = int((time.time() - t0) * 1000)
    return out
