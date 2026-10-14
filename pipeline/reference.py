"""
Reference data: the approved-vendor register and the PO register.

The app keeps a working copy per session (defaults from data/*.csv, plus
whatever the person uploads or adds). Uploads must use the same columns as the
bundled files; this module validates them and explains exactly what is wrong.
"""
import io
import re

import pandas as pd

from . import config

VENDOR_COLUMNS = ["vendor_id", "legal_name", "aliases", "gstin", "state_code", "state", "tolerance_pct", "status"]
PO_COLUMNS = ["po_number", "vendor_id", "po_date", "currency", "po_amount", "invoiced_to_date", "status", "description"]
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
VENDOR_STATUSES = {"approved", "inactive", "blocked"}
PO_STATUSES = {"open", "closed", "cancelled"}


def load_default_vendors() -> pd.DataFrame:
    return _coerce_vendors(pd.read_csv(config.DATA_DIR / "vendors.csv", dtype=str).fillna(""))


def load_default_pos() -> pd.DataFrame:
    return _coerce_pos(pd.read_csv(config.DATA_DIR / "purchase_orders.csv", dtype=str).fillna(""))


def template_csv(kind: str) -> str:
    if kind == "vendors":
        return ",".join(VENDOR_COLUMNS) + "\nV101,Example Industries Pvt Ltd,Example Ind|EIPL,27AAACE1234F1Z5,27,Maharashtra,2,approved\n"
    return ",".join(PO_COLUMNS) + "\nPO-2001,V101,2026-10-01,INR,118000,0,open,Example goods\n"


# ----------------------------------------------------------------- coercion
def _coerce_vendors(df):
    df = df.copy()
    for c in VENDOR_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df["tolerance_pct"] = pd.to_numeric(df["tolerance_pct"], errors="coerce").fillna(config.DEFAULT_TOLERANCE_PCT)
    df["gstin"] = df["gstin"].astype(str).str.strip().str.upper()
    df["status"] = df["status"].astype(str).str.strip().str.lower()
    return df[VENDOR_COLUMNS]


def _coerce_pos(df):
    df = df.copy()
    for c in PO_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    for c in ("po_amount", "invoiced_to_date"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["po_number"] = df["po_number"].astype(str).str.strip().str.upper()
    df["status"] = df["status"].astype(str).str.strip().str.lower()
    return df[PO_COLUMNS]


# ----------------------------------------------------------------- validation
def validate_upload(kind: str, file_bytes: bytes, existing_vendors: pd.DataFrame = None):
    """Returns (clean_df or None, errors: list[str], warnings: list[str], preview_df)."""
    errors, warnings = [], []
    try:
        raw = pd.read_csv(io.BytesIO(file_bytes), dtype=str).fillna("")
    except Exception as e:  # noqa: BLE001
        return None, [f"Could not read the file as CSV: {e}"], [], None
    raw.columns = [c.strip().lower() for c in raw.columns]
    expected = VENDOR_COLUMNS if kind == "vendors" else PO_COLUMNS
    missing = [c for c in expected if c not in raw.columns]
    extra = [c for c in raw.columns if c not in expected]
    if missing:
        errors.append("Missing columns: " + ", ".join(missing) + ". Download the template and keep the header row exactly.")
    if extra:
        warnings.append("Ignored columns not in the template: " + ", ".join(extra))
    if raw.empty:
        errors.append("The file has a header but no rows.")
    if errors:
        return None, errors, warnings, raw.head(10)

    if kind == "vendors":
        df = _coerce_vendors(raw)
        for i, row in df.iterrows():
            n = i + 2  # 1-based + header
            if not row["vendor_id"].strip():
                errors.append(f"Row {n}: vendor_id is empty")
            if not row["legal_name"].strip():
                errors.append(f"Row {n}: legal_name is empty")
            if row["gstin"] and not GSTIN_RE.match(row["gstin"]):
                warnings.append(f"Row {n}: GSTIN '{row['gstin']}' is not a valid 15-character format")
            if row["status"] not in VENDOR_STATUSES:
                errors.append(f"Row {n}: status must be one of {sorted(VENDOR_STATUSES)}, got '{row['status']}'")
        dup = df["vendor_id"][df["vendor_id"].duplicated()].unique().tolist()
        if dup:
            errors.append("Duplicate vendor_id inside the file: " + ", ".join(dup))
    else:
        df = _coerce_pos(raw)
        known = set(existing_vendors["vendor_id"]) if existing_vendors is not None else set()
        for i, row in df.iterrows():
            n = i + 2
            if not re.match(r"^PO-\d{3,6}$", str(row["po_number"])):
                errors.append(f"Row {n}: po_number must look like PO-1234, got '{row['po_number']}'")
            if pd.isna(row["po_amount"]) or row["po_amount"] <= 0:
                errors.append(f"Row {n}: po_amount must be a positive number")
            if pd.isna(row["invoiced_to_date"]):
                errors.append(f"Row {n}: invoiced_to_date must be a number (use 0 if nothing invoiced yet)")
            elif not pd.isna(row["po_amount"]) and row["invoiced_to_date"] > row["po_amount"]:
                warnings.append(f"Row {n}: invoiced_to_date exceeds po_amount")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(row["po_date"])):
                errors.append(f"Row {n}: po_date must be YYYY-MM-DD, got '{row['po_date']}'")
            if row["status"] not in PO_STATUSES:
                errors.append(f"Row {n}: status must be one of {sorted(PO_STATUSES)}, got '{row['status']}'")
            if known and row["vendor_id"] not in known:
                warnings.append(f"Row {n}: vendor_id '{row['vendor_id']}' is not in the vendor register; invoices against it will hold as PO_VENDOR_MISMATCH")
        dup = df["po_number"][df["po_number"].duplicated()].unique().tolist()
        if dup:
            errors.append("Duplicate po_number inside the file: " + ", ".join(dup))

    return (None if errors else df), errors, warnings, df.head(10)


# ----------------------------------------------------------------- apply
def merge_into(kind: str, existing: pd.DataFrame, incoming: pd.DataFrame, mode: str) -> pd.DataFrame:
    """mode: 'append' (incoming rows override existing rows with the same key) or 'replace'."""
    key = "vendor_id" if kind == "vendors" else "po_number"
    if mode == "replace":
        return incoming.reset_index(drop=True)
    kept = existing[~existing[key].isin(incoming[key])]
    return pd.concat([kept, incoming], ignore_index=True)


def add_row(kind: str, existing: pd.DataFrame, row: dict):
    """Validate a single row (from the add form) and return (new_df or None, errors)."""
    df = pd.DataFrame([row]).astype(str)
    csv_bytes = df.to_csv(index=False).encode()
    clean, errors, _, _ = validate_upload(kind, csv_bytes, existing if kind == "pos" else None)
    if errors:
        return None, errors
    return merge_into(kind, existing, clean, "append"), []
