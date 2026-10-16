"""
One place for the constants the whole pipeline agrees on.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SAMPLES_DIR = DATA_DIR / "samples"
RUNS_FILE = DATA_DIR / "runs.jsonl"          # local run history (day 2 adds HF Dataset sync)

BUYER_NAME = "KatLabs Pvt Ltd"
BUYER_GSTIN = "27AAHCM6789N1Z6"
BUYER_STATE_CODE = "27"
CURRENCY = "INR"

# The fields we extract. Order is the display order.
FIELDS = [
    "vendor_name",
    "vendor_gstin",
    "invoice_number",
    "invoice_date",
    "po_reference",
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "total",
]
REQUIRED_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total"]
IDENTITY_FIELDS = ["vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "po_reference"]
MONEY_FIELDS = ["subtotal", "cgst", "sgst", "igst", "total"]
AMOUNT_FIELDS = ["subtotal", "cgst", "sgst", "igst", "total"]

ROUNDING_TOLERANCE = 1.0      # rupees; arithmetic may differ by this much
GST_RATE = 0.18               # all our test goods are 18%; validation only checks structure, not rate
DEFAULT_TOLERANCE_PCT = 2.0   # used only if a vendor row lacks one
PO_INFER_WINDOW_DAYS = 90     # when no PO is stated, look this far back for an open PO
VENDOR_MATCH_THRESHOLD = 0.80 # fuzzy name similarity needed to accept a vendor match
DATE_MAX_AGE_DAYS = 365

# AI usage policy
OCR_AI_THRESHOLD = 90.0       # scans below this mean OCR confidence are read whole by the AI:
                              # the page IMAGE goes to Gemini vision when GEMINI_API_KEY is set, else the OCR text goes to Groq
