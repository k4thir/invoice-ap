# Setup (day 1)

## 1. System tools (one time)

**macOS** (Homebrew):
    brew install tesseract poppler

**Windows**:
  - Tesseract: install from https://github.com/UB-Mannheim/tesseract/wiki (tick "add to PATH").
  - Poppler: download the latest release zip from https://github.com/oschwartz10612/poppler-windows/releases,
    unzip to C:\poppler, and add C:\poppler\Library\bin to your PATH.
  - Open a new terminal afterwards so PATH changes apply.

**Ubuntu/Debian**:
    sudo apt install tesseract-ocr poppler-utils

Check: `tesseract --version` and `pdftoppm -v` both print a version.

## 2. Python environment

    cd invoice-ap
    python -m venv .venv
    # macOS/Linux:   source .venv/bin/activate
    # Windows:       .venv\Scripts\activate
    pip install -r requirements.txt

(If you are on a company-managed laptop with a private package mirror, point pip at it per your IT guidance.)

## 3. Keys

    cp .env.example .env        # Windows: copy .env.example .env
Leave the model fields empty for now; day 2 wires them.

## 4. Regenerate the sample invoices (already included, but this is how)

    python tools/make_invoices.py

## 5. Run

    streamlit run app.py

Open the URL it prints (usually http://localhost:8501). Pick a sample, press Run.

## 6. Put the skeleton on Hugging Face today

  1. huggingface.co → New Space → SDK: Streamlit → Hardware: CPU basic (free) → Create.
  2. Upload everything in this folder except .env and .venv (the Space reads requirements.txt and packages.txt).
  3. Wait for the build log to finish; open the public URL; run a sample.
  Doing this on day 1 surfaces install problems while there is time to fix them.

# Day 2

## Keys
Edit `.env`:
    AI_PROVIDER=groq
    GROQ_API_KEY=gsk_...
    GROQ_MODEL=openai/gpt-oss-120b
Optional: a Gemini key as fallback; an HF write token + dataset repo name to mirror history.

## Install the new dependency and run
    pip install -r requirements.txt
    streamlit run app.py
The sidebar shows "AI extractor: groq · openai/gpt-oss-120b" when the key is picked up.

## Demo order (start with a clean history: Dashboard → Reset → Clear live history)
    1  inv01  Approve  EXACT_MATCH
    2  inv08  Approve  EXACT_MATCH        rules found 3 fields, AI found 8
    3  inv04  Hold     MISSING_FIELD      scanned, OCR path, no invoice number (+ GSTIN_INVALID from an OCR misread)
    4  inv05  Approve  PARTIAL_DELIVERY   449,860 of 500,000 on PO-1042
    5  inv06  Hold     CUMULATIVE_EXCEEDS_PO   570,220 vs 500,000
    6  inv07  Reject   DUPLICATE_INVOICE  same number as run 1
    7  inv03  Hold     OUTSIDE_TOLERANCE  +3.00% vs 2%
    8  inv02  Approve  WITHIN_TOLERANCE   +1.50% vs 2%
Then flip the sidebar toggle "Use AI extractor" off and run inv08 again: Hold, MISSING_FIELD, with "AI unavailable" in the log.

## Streamlit Community Cloud secrets (Manage app → Settings → Secrets)
    AI_PROVIDER = "groq"
    GROQ_API_KEY = "gsk_..."
    GROQ_MODEL = "openai/gpt-oss-120b"
    HF_TOKEN = "hf_..."                       # optional
    HF_DATASET_REPO = "your-username/invoice-ap-runs"   # optional
Reboot the app after changing secrets.


# Day 3 (redesign + tiered AI)

- New files: ui.py, pipeline/reference.py, .streamlit/config.toml. Replace the whole folder again, keep .env.
- The sample picker is gone: upload PDFs (several at once is fine). Reviewers can download the 8 samples from the sidebar.
- Seed runs are gone. To keep history across cloud restarts, set HF_TOKEN and HF_DATASET_REPO in secrets (optional).
- IMPORTANT: upload the hidden folder .streamlit (it holds config.toml, the theme). On a Mac press Cmd+Shift+. in Finder to show hidden files.
- Reference data page: upload a CSV in the template format (download the template there), or add one row by hand. Session-only by design.
- If you later add GEMINI_API_KEY, scans under 70% OCR confidence are read from the page image.
