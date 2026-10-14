"""
Generate the eight test invoices for Meridian Components Pvt Ltd (the buyer).

Four layouts, deliberately different:
  A  classic boxed table, "Invoice No" / "Grand Total" labels          (invoices 1, 4, 7)
  B  compact, "Inv #" / "Bill From" / "Total Amount" labels            (invoices 2, 3)
  C  two-column modern, "Invoice Number" / "Total Payable" labels      (invoices 5, 6)
  D  unusual, "Document No." / "Dated" / "Ref PO" / "Amount Payable",
     bundled single line item, Indian lakh digit grouping              (invoice 8)

Invoice 4 is rendered to an image, rotated slightly, given noise and saved
back as an image-only PDF so there is no text layer: the OCR path.
Invoice 7 is invoice 1 regenerated with a "resent" footer: same invoice
number, different bytes.

Run:  python tools/make_invoices.py
"""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from PIL import Image, ImageFilter
import numpy as np
import random

OUT = Path(__file__).resolve().parent.parent / "data" / "samples"
OUT.mkdir(parents=True, exist_ok=True)

BUYER = {
    "name": "Meridian Components Pvt Ltd",
    "addr": "Plot 14, MIDC Bhosari, Pune 411026, Maharashtra",
    "gstin": "27AAHCM6789N1Z6",
}

VENDORS = {
    "V001": dict(name="Shree Krishna Fasteners Pvt Ltd", addr="Gat 221, Chakan Industrial Area, Pune 410501, Maharashtra", gstin="27AABCS1234F1Z5", state="Maharashtra"),
    "V002": dict(name="Deccan Polymers LLP", addr="S-17, Ranjangaon MIDC, Pune 412220, Maharashtra", gstin="27AAFFD5678K1Z3", state="Maharashtra"),
    "V003": dict(name="Bharat Steel Tubes Ltd", addr="Survey 88, GIDC Vatva, Ahmedabad 382445, Gujarat", gstin="24AAACB9012H1Z7", state="Gujarat"),
    "V004": dict(name="Pune Packaging Co", addr="Unit 6, Talawade Industrial Estate, Pune 412114, Maharashtra", gstin="27AAEFP3456M1Z9", state="Maharashtra"),
    "V005": dict(name="Nexora Industrial Supplies Pvt Ltd", addr="No. 42, Peenya 2nd Stage, Bengaluru 560058, Karnataka", gstin="29AACCN7890P1Z1", state="Karnataka"),
}


def inr(x, lakh=False):
    """Format a number as Indian currency text. lakh=True uses 1,77,000.00 grouping."""
    s = f"{x:,.2f}"
    if not lakh:
        return s
    whole, frac = f"{x:.2f}".split(".")
    if len(whole) <= 3:
        return f"{whole}.{frac}"
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail + "." + frac


def taxes(taxable, intra_state, rate=0.18):
    tax = round(taxable * rate, 2)
    if intra_state:
        return dict(cgst=round(tax / 2, 2), sgst=round(tax / 2, 2), igst=0.0, total=round(taxable + tax, 2))
    return dict(cgst=0.0, sgst=0.0, igst=tax, total=round(taxable + tax, 2))


# ---------------------------------------------------------------- layout A
def layout_a(path, v, inv_no, inv_date, po, items, footer=None, omit_invoice_no=False):
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    intra = v["state"] == "Maharashtra"
    taxable = sum(i[3] for i in items)
    t = taxes(taxable, intra)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, H - 22 * mm, v["name"])
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, H - 27 * mm, v["addr"])
    c.drawString(20 * mm, H - 31.5 * mm, f"GSTIN: {v['gstin']}")
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(W - 20 * mm, H - 22 * mm, "TAX INVOICE")

    c.setFont("Helvetica", 10)
    y = H - 45 * mm
    c.drawString(20 * mm, y, "Invoice No: " + ("" if omit_invoice_no else inv_no))
    c.drawString(110 * mm, y, f"Invoice Date: {inv_date}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"PO No: {po}")
    c.drawString(110 * mm, y, "Place of Supply: Maharashtra (27)")

    y -= 12 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Bill To:")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y - 5 * mm, BUYER["name"])
    c.drawString(20 * mm, y - 10 * mm, BUYER["addr"])
    c.drawString(20 * mm, y - 15 * mm, f"GSTIN: {BUYER['gstin']}")

    y -= 26 * mm
    cols = [20, 30, 105, 125, 150, 190]
    heads = ["#", "Description", "HSN", "Qty", "Rate", "Amount"]
    c.setLineWidth(0.6)
    c.rect(20 * mm, y - 2 * mm, 170 * mm, 7 * mm)
    c.setFont("Helvetica-Bold", 9)
    for x, h in zip(cols, heads):
        if h in ("Rate", "Amount", "Qty"):
            c.drawRightString((x + (20 if h != "Amount" else 0)) * mm, y, h) if h != "Amount" else c.drawRightString(x * mm, y, h)
        else:
            c.drawString((x + 1) * mm, y, h)
    c.setFont("Helvetica", 9)
    for n, (desc, hsn, qty, amt, rate) in enumerate(items, 1):
        y -= 7 * mm
        c.rect(20 * mm, y - 2 * mm, 170 * mm, 7 * mm)
        c.drawString(21 * mm, y, str(n))
        c.drawString(31 * mm, y, desc)
        c.drawString(106 * mm, y, hsn)
        c.drawRightString(145 * mm, y, f"{qty:,}")
        c.drawRightString(170 * mm, y, inr(rate))
        c.drawRightString(190 * mm, y, inr(amt))

    y -= 12 * mm
    c.setFont("Helvetica", 10)
    rows = [("Sub Total", taxable)]
    if intra:
        rows += [("CGST @ 9%", t["cgst"]), ("SGST @ 9%", t["sgst"])]
    else:
        rows += [("IGST @ 18%", t["igst"])]
    for label, val in rows:
        c.drawRightString(160 * mm, y, label)
        c.drawRightString(190 * mm, y, inr(val))
        y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(160 * mm, y, "Grand Total")
    c.drawRightString(190 * mm, y, "INR " + inr(t["total"]))

    y -= 16 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, "Bank: HDFC Bank, A/c 50200012345678, IFSC HDFC0000123")
    c.drawString(20 * mm, y - 5 * mm, "Terms: Net 30 days. Goods once sold will not be taken back.")
    if footer:
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(20 * mm, 15 * mm, footer)
    c.setFont("Helvetica", 9)
    c.drawRightString(W - 20 * mm, 25 * mm, f"For {v['name']}")
    c.drawRightString(W - 20 * mm, 15 * mm, "Authorised Signatory")
    c.save()
    return t


# ---------------------------------------------------------------- layout B
def layout_b(path, v, inv_no, inv_date, po, items):
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    intra = v["state"] == "Maharashtra"
    taxable = sum(i[3] for i in items)
    t = taxes(taxable, intra)

    c.setFillGray(0.15)
    c.rect(0, H - 30 * mm, W, 30 * mm, fill=1, stroke=0)
    c.setFillGray(1)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(15 * mm, H - 19 * mm, v["name"].upper())
    c.setFillGray(0)

    c.setFont("Helvetica", 9)
    y = H - 42 * mm
    c.drawString(15 * mm, y, f"Inv # {inv_no}")
    c.drawString(70 * mm, y, f"Date {inv_date}")
    c.drawString(120 * mm, y, f"P.O. Ref {po}")
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(15 * mm, y, "Bill From")
    c.drawString(110 * mm, y, "Bill To")
    c.setFont("Helvetica", 9)
    for i, line in enumerate([v["name"], v["addr"], f"GSTIN {v['gstin']}"]):
        c.drawString(15 * mm, y - (5 + 4.5 * i) * mm, line)
    for i, line in enumerate([BUYER["name"], BUYER["addr"], f"GSTIN {BUYER['gstin']}"]):
        c.drawString(110 * mm, y - (5 + 4.5 * i) * mm, line)

    y -= 28 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(15 * mm, y, "Item")
    c.drawString(100 * mm, y, "HSN")
    c.drawRightString(135 * mm, y, "Qty")
    c.drawRightString(160 * mm, y, "Unit Price")
    c.drawRightString(195 * mm, y, "Line Total")
    c.line(15 * mm, y - 2 * mm, 195 * mm, y - 2 * mm)
    c.setFont("Helvetica", 9)
    for desc, hsn, qty, amt, rate in items:
        y -= 7 * mm
        c.drawString(15 * mm, y, desc)
        c.drawString(100 * mm, y, hsn)
        c.drawRightString(135 * mm, y, f"{qty:,} kg")
        c.drawRightString(160 * mm, y, inr(rate))
        c.drawRightString(195 * mm, y, inr(amt))
    c.line(15 * mm, y - 3 * mm, 195 * mm, y - 3 * mm)

    y -= 12 * mm
    c.drawRightString(160 * mm, y, "Taxable Value")
    c.drawRightString(195 * mm, y, inr(taxable))
    if intra:
        for label, val in (("CGST 9%", t["cgst"]), ("SGST 9%", t["sgst"])):
            y -= 6 * mm
            c.drawRightString(160 * mm, y, label)
            c.drawRightString(195 * mm, y, inr(val))
    else:
        y -= 6 * mm
        c.drawRightString(160 * mm, y, "IGST 18%")
        c.drawRightString(195 * mm, y, inr(t["igst"]))
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(160 * mm, y, "Total Amount (INR)")
    c.drawRightString(195 * mm, y, inr(t["total"]))

    c.setFont("Helvetica", 8)
    c.drawString(15 * mm, 20 * mm, "Payment: NEFT/RTGS to ICICI Bank A/c 123405006789, IFSC ICIC0001234. Due in 30 days.")
    c.drawString(15 * mm, 15 * mm, "This is a computer generated invoice.")
    c.save()
    return t


# ---------------------------------------------------------------- layout C
def layout_c(path, v, inv_no, inv_date, po, items):
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    intra = v["state"] == "Maharashtra"
    taxable = sum(i[3] for i in items)
    t = taxes(taxable, intra)

    c.setStrokeGray(0.6)
    c.setLineWidth(2)
    c.line(20 * mm, H - 15 * mm, W - 20 * mm, H - 15 * mm)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(20 * mm, H - 30 * mm, "Invoice")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, H - 37 * mm, v["name"])
    c.drawString(20 * mm, H - 42 * mm, v["addr"])
    c.drawString(20 * mm, H - 47 * mm, f"GSTIN {v['gstin']}")

    x2 = 120 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x2, H - 30 * mm, "Invoice Number")
    c.drawString(x2, H - 36 * mm, "Invoice Date")
    c.drawString(x2, H - 42 * mm, "Purchase Order")
    c.drawString(x2, H - 48 * mm, "Payment Due")
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(W - 20 * mm, H - 30 * mm, inv_no)
    c.drawRightString(W - 20 * mm, H - 36 * mm, inv_date)
    c.drawRightString(W - 20 * mm, H - 42 * mm, po)
    c.drawRightString(W - 20 * mm, H - 48 * mm, "45 days from invoice")

    y = H - 65 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Billed to")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y - 5 * mm, BUYER["name"])
    c.drawString(20 * mm, y - 10 * mm, BUYER["addr"])
    c.drawString(20 * mm, y - 15 * mm, f"GSTIN {BUYER['gstin']}")

    y -= 30 * mm
    c.setFillGray(0.92)
    c.rect(20 * mm, y - 3 * mm, W - 40 * mm, 8 * mm, fill=1, stroke=0)
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(22 * mm, y, "Description")
    c.drawString(105 * mm, y, "HSN")
    c.drawRightString(135 * mm, y, "Quantity")
    c.drawRightString(160 * mm, y, "Rate")
    c.drawRightString(W - 22 * mm, y, "Amount")
    c.setFont("Helvetica", 9)
    for desc, hsn, qty, amt, rate in items:
        y -= 8 * mm
        c.drawString(22 * mm, y, desc)
        c.drawString(105 * mm, y, hsn)
        c.drawRightString(135 * mm, y, f"{qty:,} m")
        c.drawRightString(160 * mm, y, inr(rate))
        c.drawRightString(W - 22 * mm, y, inr(amt))

    y -= 16 * mm
    c.setFont("Helvetica", 10)
    c.drawString(120 * mm, y, "Subtotal")
    c.drawRightString(W - 22 * mm, y, inr(taxable))
    if intra:
        for label, val in (("CGST (9%)", t["cgst"]), ("SGST (9%)", t["sgst"])):
            y -= 6 * mm
            c.drawString(120 * mm, y, label)
            c.drawRightString(W - 22 * mm, y, inr(val))
    else:
        y -= 6 * mm
        c.drawString(120 * mm, y, "IGST (18%)")
        c.drawRightString(W - 22 * mm, y, inr(t["igst"]))
    y -= 9 * mm
    c.setLineWidth(0.8)
    c.line(120 * mm, y + 5 * mm, W - 20 * mm, y + 5 * mm)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(120 * mm, y, "Total Payable")
    c.drawRightString(W - 22 * mm, y, "Rs. " + inr(t["total"]))

    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 22 * mm, "Dispatch against phased delivery schedule under the above PO. Partial supply; balance to follow.")
    c.drawString(20 * mm, 17 * mm, "Bank of Baroda A/c 29870100004567 IFSC BARB0VATVAX")
    c.save()
    return t


# ---------------------------------------------------------------- layout D
def layout_d(path, v, inv_no, inv_date, po, items):
    """Deliberately off-pattern: labels no regex was written for, bundled line, lakh grouping."""
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    intra = v["state"] == "Maharashtra"
    taxable = sum(i[3] for i in items)
    t = taxes(taxable, intra)

    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, H - 18 * mm, "TAX INVOICE")
    c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2, H - 23 * mm, "(Issued under Section 31 of the CGST Act, 2017)")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, H - 36 * mm, v["name"])
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, H - 41 * mm, v["addr"])
    c.drawString(20 * mm, H - 46 * mm, f"GSTIN/UIN: {v['gstin']}    State: {v['state']} (29)")

    y = H - 58 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, f"Document No.: {inv_no}")
    c.drawString(20 * mm, y - 5 * mm, f"Dated: {inv_date}")
    c.drawString(20 * mm, y - 10 * mm, f"Ref PO: {po} dt. 22-Sep-2026")
    c.drawString(110 * mm, y, "Consignee / Buyer:")
    c.drawString(110 * mm, y - 5 * mm, BUYER["name"])
    c.drawString(110 * mm, y - 10 * mm, BUYER["addr"])
    c.drawString(110 * mm, y - 15 * mm, f"GSTIN/UIN: {BUYER['gstin']}    Place of Supply: Maharashtra (27)")

    y -= 30 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Sl")
    c.drawString(30 * mm, y, "Particulars")
    c.drawString(120 * mm, y, "HSN/SAC")
    c.drawRightString(150 * mm, y, "Qty")
    c.drawRightString(190 * mm, y, "Value")
    c.line(20 * mm, y - 2 * mm, 190 * mm, y - 2 * mm)
    c.setFont("Helvetica", 9)
    for n, (desc, hsn, qty, amt, rate) in enumerate(items, 1):
        y -= 7 * mm
        c.drawString(20 * mm, y, str(n))
        c.drawString(30 * mm, y, desc)
        c.drawString(120 * mm, y, hsn)
        c.drawRightString(150 * mm, y, f"{qty} Lot")
        c.drawRightString(190 * mm, y, inr(amt, lakh=True))

    y -= 14 * mm
    c.drawString(120 * mm, y, "Value of Supply")
    c.drawRightString(190 * mm, y, inr(taxable, lakh=True))
    y -= 6 * mm
    if intra:
        c.drawString(120 * mm, y, "Central Tax 9%")
        c.drawRightString(190 * mm, y, inr(t["cgst"], lakh=True))
        y -= 6 * mm
        c.drawString(120 * mm, y, "State Tax 9%")
        c.drawRightString(190 * mm, y, inr(t["sgst"], lakh=True))
    else:
        c.drawString(120 * mm, y, "Integrated Tax 18%")
        c.drawRightString(190 * mm, y, inr(t["igst"], lakh=True))
    y -= 9 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(120 * mm, y, "Amount Payable")
    c.drawRightString(190 * mm, y, "INR " + inr(t["total"], lakh=True))
    y -= 7 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20 * mm, y, "Amount in words: Indian Rupees One Lakh Seventy Seven Thousand Only")

    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 25 * mm, "Declaration: We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.")
    c.drawString(20 * mm, 20 * mm, "E. & O.E.   Subject to Bengaluru jurisdiction.")
    c.save()
    return t


# ---------------------------------------------------------------- scan
def make_scan(src_pdf, dst_pdf, seed=7):
    """Photocopy-grade scan: low render DPI, slight skew, grain, speckle, JPEG artefacts.
    Lands around 84% mean Tesseract confidence: readable, but below the 90% bar that routes a scan to the AI."""
    import io
    from pdf2image import convert_from_path
    random.seed(seed)
    np.random.seed(seed)
    img = convert_from_path(str(src_pdf), dpi=100)[0].convert("L")
    img = img.rotate(1.8, resample=Image.BICUBIC, expand=False, fillcolor=255)
    arr = np.asarray(img).astype(np.int16)
    arr = np.clip(arr + np.random.normal(0, 16, arr.shape), 0, 255)
    speck = np.random.rand(*arr.shape) < 0.006
    arr[speck] = np.random.choice([0, 255], size=speck.sum())
    img = Image.fromarray(arr.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=25)
    buf.seek(0)
    Image.open(buf).convert("L").save(str(dst_pdf), "PDF", resolution=100.0)


def main():
    spec = []

    # 1  happy path, exact
    p1 = OUT / "inv01_sk_fasteners_SKF-26-27-0912.pdf"
    layout_a(p1, VENDORS["V001"], "SKF/26-27/0912", "29/09/2026", "PO-1037",
             [("M8 x 40 hex bolts, zinc plated", "73181500", 20000, 70000.0, 3.5),
              ("M8 hex nuts, zinc plated", "73181600", 20000, 30000.0, 1.5)])
    spec.append((p1.name, "Approve, exact match to PO-1037"))

    # 2  tolerance inside (1.5% over 236,000 = 239,540)
    p2 = OUT / "inv02_deccan_DP-2609-114.pdf"
    layout_b(p2, VENDORS["V002"], "DP/2609/114", "01-10-2026", "PO-1040",
             [("HDPE granules, injection grade", "39012000", 2030, 203000.0, 100.0)])
    spec.append((p2.name, "Approve, 1.5% over PO-1040, within 2% tolerance"))

    # 3  tolerance outside (3% over 236,000 = 243,080)
    p3 = OUT / "inv03_deccan_DP-2609-121.pdf"
    layout_b(p3, VENDORS["V002"], "DP/2609/121", "06-10-2026", "PO-1041",
             [("HDPE granules, injection grade", "39012000", 2060, 206000.0, 100.0)])
    spec.append((p3.name, "Hold, 3% over PO-1041, outside 2% tolerance"))

    # 4  scanned, invoice number missing
    tmp = OUT / "_tmp_inv04_text.pdf"
    layout_a(tmp, VENDORS["V004"], "", "05/10/2026", "PO-1045",
             [("Corrugated cartons 5-ply, 600x400x400", "48191010", 2500, 50000.0, 20.0)],
             omit_invoice_no=True)
    p4 = OUT / "inv04_pune_packaging_scanned.pdf"
    make_scan(tmp, p4)
    tmp.unlink()
    spec.append((p4.name, "Hold, scanned (OCR path), invoice number missing"))

    # 5  split PO, first part (PO-1042 already 300,000 invoiced; this adds 149,860)
    p5 = OUT / "inv05_bharat_steel_BST-0882.pdf"
    layout_c(p5, VENDORS["V003"], "BST/0882", "26 Sep 2026", "PO-1042",
             [("ERW steel tubes 50mm OD, 2.5mm wall", "73063090", 2540, 127000.0, 50.0)])
    spec.append((p5.name, "Approve, cumulative 449,860 of 500,000 on PO-1042"))

    # 6  split PO, second part (adds 120,360 -> cumulative 570,220, over PO)
    p6 = OUT / "inv06_bharat_steel_BST-0907.pdf"
    layout_c(p6, VENDORS["V003"], "BST/0907", "08 Oct 2026", "PO-1042",
             [("ERW steel tubes 50mm OD, 2.5mm wall", "73063090", 2040, 102000.0, 50.0)])
    spec.append((p6.name, "Hold, cumulative 570,220 exceeds PO-1042 amount 500,000"))

    # 7  duplicate of invoice 1, resent
    p7 = OUT / "inv07_sk_fasteners_resent.pdf"
    layout_a(p7, VENDORS["V001"], "SKF/26-27/0912", "29/09/2026", "PO-1037",
             [("M8 x 40 hex bolts, zinc plated", "73181500", 20000, 70000.0, 3.5),
              ("M8 hex nuts, zinc plated", "73181600", 20000, 30000.0, 1.5)],
             footer="Copy resent on request of accounts department, 10/10/2026")
    spec.append((p7.name, "Reject, duplicate of SKF/26-27/0912 (invoice 1)"))

    # 8  unseen format
    p8 = OUT / "inv08_nexora_NXR-TI-4471.pdf"
    layout_d(p8, VENDORS["V005"], "NXR/TI/4471", "03-Oct-2026", "PO-1048",
             [("Bearings and seals kit, per PO spec (bundled)", "84829900", 1, 150000.0, 150000.0)])
    spec.append((p8.name, "Approve, exact match to PO-1048; rules miss most fields, AI extracts them"))

    print("Generated:")
    for name, expect in spec:
        print(f"  {name:45s} -> {expect}")


if __name__ == "__main__":
    main()
