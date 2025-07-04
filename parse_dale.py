import os
import re
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
import pandas as pd
from decimal import Decimal

VENDOR_NAME = "Dale Petroleum Company"
ASCII_RATIO_THRESHOLD = 0.5
PDF_DPI = 300
TOLERANCE = Decimal("0.01")
HEADER_REGION_FRAC = (0.5, 0.0, 1.0, 0.2)

INV_NO_RX = re.compile(r"Invoice\s*No\W*:\s*(IN-[A-Za-z0-9-]+)", re.IGNORECASE)
INV_DT_RX = re.compile(r"Invoice\s*Date\W*:\s*(.+)", re.IGNORECASE)
FULL_NO_RX = re.compile(r"\b(IN-[A-Za-z0-9-]+)\b")
FULL_DT_RX = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
INV_TOTAL_RX = re.compile(r"Invoice\s*Total\W*[:\$]?\s*([\d,]+\.\d{1,2})", re.IGNORECASE)
HEADER_RX = re.compile(r"Description.*Total", re.IGNORECASE)
AMOUNT_RX = re.compile(r'([\d,]+\.\d{1,2}-|\([\d,]+\.\d{1,2}\)|[\d,]+\.\d{1,2})\s*$')

def normalize_amount(txt: str) -> Decimal:
    txt = txt.strip()
    m = re.match(r'([\d,]+\.\d{1,2})-', txt)
    if m:
        return Decimal(m.group(1).replace(",", "")).copy_negate()
    m = re.match(r'\(([\d,]+\.\d{1,2})\)', txt)
    if m:
        return Decimal(m.group(1).replace(",", "")).copy_negate()
    return Decimal(txt.replace(",", ""))

def strip_weekday(date_str: str) -> str:
    m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", date_str)
    return m.group(1) if m else date_str.strip()

def extract_text_lines(page, pdf_path, page_idx):
    txt = page.extract_text() or ""
    page.flush_cache()
    ratio = sum(1 for c in txt if ord(c)<128)/max(len(txt),1)
    if ratio < ASCII_RATIO_THRESHOLD:
        img = convert_from_path(pdf_path, dpi=PDF_DPI,
                                first_page=page_idx+1, last_page=page_idx+1)[0]
        txt = pytesseract.image_to_string(img)
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]

def extract_header_field(page, field_rx):
    x0f,y0f,x1f,y1f = HEADER_REGION_FRAC
    w,h = page.width, page.height
    x0,y0 = int(x0f*w), int(y0f*h)
    x1,y1 = int(x1f*w), int(y1f*h)
    cropped = page.crop((x0,y0,x1,y1))
    txt = cropped.extract_text() or ""
    cropped.flush_cache()
    lines = txt.splitlines()
    ratio = sum(1 for c in txt if ord(c)<128)/max(len(txt),1)
    if ratio < ASCII_RATIO_THRESHOLD:
        img = cropped.to_image(resolution=PDF_DPI).original
        lines = pytesseract.image_to_string(img).splitlines()
    for ln in lines:
        m = field_rx.search(ln)
        if m:
            return m.group(1).strip()
    return ""

def parse_page(page, pdf_path, page_idx):
    raw_inv_no = extract_header_field(page, INV_NO_RX)
    raw_inv_date = extract_header_field(page, INV_DT_RX)

    lines = extract_text_lines(page, pdf_path, page_idx)
    full_text = "\n".join(lines)

    inv_no = raw_inv_no or (FULL_NO_RX.search(full_text).group(1) if FULL_NO_RX.search(full_text) else "")
    inv_date = raw_inv_date or (FULL_DT_RX.search(full_text).group(1) if FULL_DT_RX.search(full_text) else "")
    inv_date = strip_weekday(inv_date)

    total_amount = None
    for ln in reversed(lines):
        m = INV_TOTAL_RX.search(ln)
        if m:
            total_amount = Decimal(m.group(1).replace(",", ""))
            break

    header_idx = next((i for i, ln in enumerate(lines) if HEADER_RX.search(ln)), None)

    items = []
    if header_idx is not None:
        for ln in lines[header_idx+1:]:
            if INV_TOTAL_RX.search(ln): 
                break
            if "Product Total" in ln:
                continue
            m = AMOUNT_RX.search(ln)
            if not m:
                continue
            amt = normalize_amount(m.group(1))
            desc = ln[:m.start()].strip().rstrip(":,-")
            items.append((desc, amt))

    sum_items = sum(a for _, a in items)
    issues = []
    if not inv_no: issues.append("invoice_number_missing")
    if not inv_date: issues.append("invoice_date_missing")
    if total_amount is None: issues.append("total_missing")
    if not items: issues.append("no_line_items")
    if total_amount is not None and abs(sum_items - total_amount) > TOLERANCE:
        issues.append("total_mismatch")

    check_needed = bool(issues)
    parsing_issues = ";".join(issues)

    rows = []
    for desc, amt in items:
        rows.append({
            "source_file": os.path.basename(pdf_path),
            "vendor_name": VENDOR_NAME,
            "invoice_number": inv_no,
            "invoice_date": inv_date,
            "total_amount": float(total_amount) if total_amount else "",
            "line_item_description": desc,
            "line_item_amount": float(amt),
            "check_needed": str(check_needed),
            "parsing_issues": parsing_issues
        })
    return rows

def parse(file_obj):
    rows = []
    with pdfplumber.open(file_obj) as pdf:
        for idx, page in enumerate(pdf.pages):
            rows.extend(parse_page(page, file_obj.name, idx))
    return rows
