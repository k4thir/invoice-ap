"""
Stage 1 - Ingest.

Takes PDF bytes. Returns the text we will work from, plus how we got it.
- If the PDF has a usable text layer, use it (fast, exact).
- If not (scanned image), render the page and OCR it with Tesseract.
Also computes a hash of the file for exact-duplicate detection.
"""
import hashlib
import io
import re

import pdfplumber

MIN_TEXT_CHARS = 50  # below this we assume there is no real text layer


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def read_text_layer(data: bytes):
    """Return (text, page_count). Text from all pages joined with form feeds."""
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n\f\n".join(pages), len(pages)


def ocr(data: bytes, dpi: int = 300):
    """Render each page and OCR it. Returns (text, page_count, mean_confidence)."""
    from pdf2image import convert_from_bytes
    import pytesseract

    images = convert_from_bytes(data, dpi=dpi)
    texts, confs = [], []
    first_png = None
    for img in images:
        gray = img.convert("L")
        if first_png is None:
            buf = io.BytesIO()
            img.convert("RGB").resize((img.width // 2, img.height // 2)).save(buf, "PNG", optimize=True)
            first_png = buf.getvalue()
        texts.append(pytesseract.image_to_string(gray))
        try:
            d = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
            confs += [int(c) for c in d["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
        except Exception:
            pass
    mean_conf = round(sum(confs) / len(confs), 1) if confs else None
    return "\n\f\n".join(texts), len(images), mean_conf, first_png


def clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def run(data: bytes, filename: str) -> dict:
    result = {
        "filename": filename,
        "file_hash": file_hash(data),
        "size_bytes": len(data),
        "path": None,
        "pages": 0,
        "ocr_confidence": None,
        "text": "",
        "page_image_png": None,
        "summary": "",
    }
    text, pages = read_text_layer(data)
    if len(text.strip()) >= MIN_TEXT_CHARS:
        result.update(path="text_layer", pages=pages, text=clean(text))
        result["summary"] = f"Text layer found: {len(result['text']):,} characters across {pages} page(s)"
        return result

    text, pages, conf, png = ocr(data)
    result.update(path="ocr", pages=pages, text=clean(text), ocr_confidence=conf, page_image_png=png)
    conf_txt = f", OCR confidence {conf}%" if conf is not None else ""
    result["summary"] = f"No text layer; OCR produced {len(result['text']):,} characters from {pages} page(s){conf_txt}"
    return result
