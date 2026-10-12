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
