def parse(f):
    import os
    import re
    import pdfplumber
    import pytesseract
    from pdf2image import convert_from_bytes
    from io import BytesIO

    VENDOR_NAME = "Marathon Petroleum Company"
    ASCII_THRESHOLD = 0.5
    PDF_DPI = 300
    TOLERANCE = 0.01

    INV_NO_RX = re.compile(r"Invoice\s*Number\s*[:\-]?\s*(\S+)", re.IGNORECASE)
    INV_DT_RX = re.compile(r"Invoice\s*Date\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE)
    FULL_NO_RX = re.compile(r"\b(IN-[A-Za-z0-9-]+|\d{10,})\b")
    DATE_RX = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
    INV_TOTAL_RX = re.compile(r"Invoice\s*Total\W*[:\$]?\s*([\d,]+\.\d{1,2})", re.IGNORECASE)
    YOU_OWE_RX = re.compile(r"You\s*Owe\s*([\d,]+\.\d{1,2})", re.IGNORECASE)
    TABLE1_HDR_RX = re.compile(r"Ship\s*Date.*Price\s*USD", re.IGNORECASE)
    FEES_HDR_RX = re.compile(r"^Basis\s+Rate\s+Amount", re.IGNORECASE)
    AMOUNT_RX = re.compile(r"\(?[\d,]+\.\d{1,2}\)?-?$")
    SKIP_NUMBER_RX = re.compile(r"^[\d\(\),\.\- ]+$")
    SKIP_SUMMARY_RX = re.compile(r"Total\s*Current\s*Taxes\s*and\s*Fees|TotalCurrentTaxesandFees|Deferred\s*Taxes|DeferredTaxes", re.IGNORECASE)

    def normalize_amount(txt):
        t = txt.strip().replace(",", "")
        if t.startswith("(") and t.endswith(")"):
            return -float(t.strip("()"))
        if t.endswith("-"):
            return -float(t.rstrip("-"))
        return float(t)

    def extract_text(page, pdf_bytes, idx):
        txt = page.extract_text() or ""
        ratio = sum(1 for c in txt if ord(c) < 128) / max(len(txt), 1)
        if ratio < ASCII_THRESHOLD:
            images = convert_from_bytes(pdf_bytes, dpi=PDF_DPI, first_page=idx + 1, last_page=idx + 1)
            txt = pytesseract.image_to_string(images[0])
        return [l.strip() for l in txt.splitlines() if l.strip()]

    rows = []
    pdf_bytes = f.read()
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for pidx, page in enumerate(pdf.pages):
            lines = extract_text(page, pdf_bytes, pidx)
            full = "\n".join(lines)

            m_no = INV_NO_RX.search(full)
            inv_no = m_no.group(1) if m_no else (FULL_NO_RX.search(full).group(0) if FULL_NO_RX.search(full) else "")
            m_dt = INV_DT_RX.search(full)
            inv_dt = m_dt.group(1) if m_dt else (DATE_RX.search(full).group(1) if DATE_RX.search(full) else "")

            total = 0.0
            for rx in (INV_TOTAL_RX, YOU_OWE_RX):
                for m in rx.finditer(full):
                    total += float(m.group(1).replace(",", ""))
            total_amount = total if total != 0.0 else None

            items = []

            # Fuel rows
            start_idx = next((i for i, ln in enumerate(lines) if TABLE1_HDR_RX.search(ln)), None)
            if start_idx is not None:
                for ln in lines[start_idx + 1:]:
                    if FEES_HDR_RX.search(ln) or INV_TOTAL_RX.search(ln) or YOU_OWE_RX.search(ln):
                        break
                    if SKIP_SUMMARY_RX.search(ln) or SKIP_NUMBER_RX.match(ln):
                        continue
                    m_amt = AMOUNT_RX.search(ln)
                    if not m_amt:
                        continue
                    amt = normalize_amount(m_amt.group(0))
                    parts = ln[:m_amt.start()].split()
                    desc = " ".join(parts[2:]).rstrip(":,-")
                    items.append((desc, amt))

            # Fees rows
            fees_idx = next((i for i, ln in enumerate(lines) if FEES_HDR_RX.search(ln)), None)
            if fees_idx is not None:
                for ln in lines[fees_idx + 1:]:
                    if INV_TOTAL_RX.search(ln) or YOU_OWE_RX.search(ln):
                        break
                    if SKIP_SUMMARY_RX.search(ln) or SKIP_NUMBER_RX.match(ln):
                        continue
                    m_amt = AMOUNT_RX.search(ln)
                    if not m_amt:
                        continue
                    amt = normalize_amount(m_amt.group(0))
                    desc = ln[:m_amt.start()].strip().rstrip(":,-")
                    items.append((desc, amt))

            sum_items = sum(a for _, a in items)
            issues = []
            if not inv_no:
                issues.append("invoice_number_missing")
            if not inv_dt:
                issues.append("invoice_date_missing")
            if total_amount is None:
                issues.append("total_missing")
            if not items:
                issues.append("no_line_items")
            if total_amount is not None and abs(sum_items - total_amount) > TOLERANCE:
                issues.append("total_mismatch")

            check_needed = bool(issues)
            parsing_issues = ";".join(issues)

            for desc, amt in items:
                rows.append({
                    "source_file":           f.name,
                    "vendor_name":           VENDOR_NAME,
                    "invoice_number":        inv_no,
                    "invoice_date":          inv_dt,
                    "total_amount":          f"{total_amount:.2f}" if total_amount is not None else "",
                    "line_item_description": desc,
                    "line_item_amount":      f"{amt:.2f}",
                    "check_needed":          str(check_needed),
                    "parsing_issues":        parsing_issues
                })

    return rows
