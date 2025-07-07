import re
from io import BytesIO
from decimal import Decimal

import pdfplumber
import pytesseract

# ── Configuration ─────────────────────────────────────────────────────────────
TOLERANCE = Decimal("0.01")

INV_NO_RX    = re.compile(r"Invoice\s*(?:No|Number)\s*[:\-]?\s*(\S+)", re.IGNORECASE)
INV_DT_RX    = re.compile(r"Invoice\s*Date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.IGNORECASE)
TOTAL_RX     = re.compile(r"Invoice\s*Total\s*[:\-]?\s*\$?([\d,]+\.\d{1,2})", re.IGNORECASE)
TOTAL_ALT_RX = re.compile(r"(?:Total\s*Invoice|Amount\s*Due)\s*[:\$]?\s*([\d,]+\.\d{1,2})", re.IGNORECASE)

LINE_RX = re.compile(r"^(.+?)\s+(\(?-?\d{1,3}(?:,\d{3})*\.\d{1,2}\)?-?)$")

BLOCK_EXCLUDE_PATTERNS = [
    r"TICKET\s+DATE\s+TIME",
    r"FLINT\s+HILLS\s+RESOURCES",
    r"EPA\s*#",
    r"INVOICE\s+NO\b",
    r"PAGE\s+NO\b",
    r"INVOICE\s+DT\b",
    r"DUE\s+DT\b",
    r"^TO:",
    r"PLEASE\s+REFERENCE\s+NOTE",
    r"Payment\s+Terms:",
    r"Before\s+Discount",
    r"After\s+Discount",
    r"Total\s+Invoice",
    r"Invoice\s+Total",
]
BLOCK_EXCLUDE_REGEX = [re.compile(p, re.IGNORECASE) for p in BLOCK_EXCLUDE_PATTERNS]
# ───────────────────────────────────────────────────────────────────────────────


def normalize_amount(txt: str) -> Decimal:
    t = txt.replace(",", "").strip()
    if t.startswith("(") and t.endswith(")"):
        return Decimal(t.strip("()")).copy_negate()
    if t.endswith("-"):
        return Decimal(t.rstrip("-")).copy_negate()
    return Decimal(t)


def ocr_page_lines(page) -> list[str]:
    img = page.to_image(resolution=300).original
    txt = pytesseract.image_to_string(img)
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]


def extract_header(lines: list[str]) -> tuple[str, str, Decimal, list[str]]:
    inv_no = ""
    inv_dt = ""
    total = None
    issues: list[str] = []

    for ln in lines:
        if not inv_no:
            m = INV_NO_RX.search(ln)
            if m:
                inv_no = m.group(1).strip()
        if inv_no:
            break

    for ln in lines:
        if not inv_dt:
            m = INV_DT_RX.search(ln)
            if m:
                inv_dt = m.group(1).strip()
        if inv_dt:
            break

    for ln in lines:
        if total is None:
            m = TOTAL_RX.search(ln)
            if m:
                try:
                    total = normalize_amount(m.group(1))
                except:
                    total = None
        if total is None:
            m2 = TOTAL_ALT_RX.search(ln)
            if m2:
                try:
                    total = normalize_amount(m2.group(1))
                except:
                    total = None
        if total is not None:
            break

    if not inv_no:
        issues.append("Missing invoice_number")
    if not inv_dt:
        issues.append("Missing invoice_date")
    if total is None:
        total = Decimal("0")
        issues.append("Missing total_amount")

    return inv_no, inv_dt, total, issues


def extract_line_items(lines: list[str]) -> tuple[list[tuple[str, Decimal, str]], list[str]]:
    items: list[tuple[str, Decimal, str]] = []
    file_issues: list[str] = []

    for ln in lines:
        if any(rx.search(ln) for rx in BLOCK_EXCLUDE_REGEX):
            continue

        m = LINE_RX.match(ln)
        if not m:
            continue

        desc = m.group(1).strip().rstrip(":,")
        amt_txt = m.group(2).strip()
        try:
            amt = normalize_amount(amt_txt)
            items.append((desc, amt, ""))
        except:
            items.append((desc, Decimal("0"), f"Could not parse amount '{amt_txt}'"))

    if not items:
        file_issues.append("No line items found after filtering")

    return items, file_issues


def parse(f) -> list[dict]:
    """
    f: a file‐like object containing PDF bytes.
    Returns list of rows:
      {
        source_file, vendor_name, invoice_number, invoice_date,
        total_amount, line_item_description, line_item_amount,
        check_needed, parsing_issue
      }
    """
    data = f.read()
    rows: list[dict] = []

    try:
        pdf = pdfplumber.open(BytesIO(data))
    except Exception:
        return []

    all_lines: list[str] = []
    for page in pdf.pages:
        txt = page.extract_text() or ""
        if txt.strip():
            page_lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        else:
            page_lines = ocr_page_lines(page)
        all_lines.extend(page_lines)

    if not all_lines:
        pdf.close()
        return []

    inv_no, inv_dt, total_amt, hdr_issues = extract_header(all_lines)
    items, item_issues = extract_line_items(all_lines)

    if not items:
        pdf.close()
        return []

    sum_amt = sum(amt for (_, amt, _) in items)
    mismatch = ""
    if abs(sum_amt - total_amt) > TOLERANCE:
        mismatch = "Line-item sum does not match total"

    check_flag = bool(mismatch)

    for desc, amt, line_issue in items:
        issues = hdr_issues + item_issues
        if line_issue:
            issues.append(line_issue)
        if mismatch:
            issues.append(mismatch)

        rows.append({
            "source_file":           getattr(f, "name", ""),
            "vendor_name":           "Flint Hills Resources LP",
            "invoice_number":        inv_no,
            "invoice_date":          inv_dt,
            "total_amount":          f"{total_amt:.2f}",
            "line_item_description": desc,
            "line_item_amount":      f"{amt:.2f}",
            "check_needed":          check_flag,
            "parsing_issue":         "; ".join(issues)
        })

    pdf.close()
    return rows
