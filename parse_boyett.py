def parse(f):
    import pdfplumber
    import re
    import os
    import pytesseract
    from decimal import Decimal, InvalidOperation
    from pdf2image import convert_from_bytes
    from io import BytesIO

    VENDOR_NAME = "Boyett Petroleum"
    ASCII_RATIO_THRESHOLD = 0.5
    PDF_DPI = 300
    TOLERANCE = Decimal("0.01")

    INV_NO_RX = re.compile(r"Invoice\s*No\W*[:\-]?\s*(\S+)", re.IGNORECASE)
    INV_DT_RX = re.compile(r"Invoice\s*Date\W*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", re.IGNORECASE)
    TABLE_HDR_RX = re.compile(r"Description.*Unit", re.IGNORECASE)
    BREAK_RX = re.compile(r"Tax\s*and\s*Other\s*Charges\s*Summary", re.IGNORECASE)
    AMOUNT_RX = re.compile(r"([\d,]+\.\d{1,2})\s*$")
    INVOICE_TOTAL_LABEL_RX = re.compile(r"Invoice\s*Total", re.IGNORECASE)

    def normalize_amount(txt):
        cleaned = re.sub(r"[^0-9,\.\-\(\)]", "", txt).replace(',', '')
        try:
            if cleaned.endswith('-'):
                return Decimal(cleaned.rstrip('-')).copy_negate()
            if cleaned.startswith('(') and cleaned.endswith(')'):
                return Decimal(cleaned.strip('()')).copy_negate()
            return Decimal(cleaned)
        except InvalidOperation:
            raise InvalidOperation(f"Could not parse amount: '{txt}'")

    def extract_text_lines(page, img_bytes, idx):
        txt = page.extract_text() or ''
        ratio = sum(1 for c in txt if ord(c) < 128) / max(len(txt), 1)
        if ratio < ASCII_RATIO_THRESHOLD:
            image = convert_from_bytes(img_bytes, dpi=PDF_DPI, first_page=idx + 1, last_page=idx + 1)[0]
            txt = pytesseract.image_to_string(image)
        return [ln.strip() for ln in txt.splitlines() if ln.strip()]

    from tempfile import NamedTemporaryFile
    temp_file = NamedTemporaryFile(delete=False, suffix=".pdf")
    temp_file.write(f.read())
    temp_file.flush()
    temp_file.close()
    path = temp_file.name

    rows = []
    with pdfplumber.open(path) as pdf:
        for pidx, page in enumerate(pdf.pages):
            with open(path, "rb") as fh:
                img_bytes = fh.read()
            lines = extract_text_lines(page, img_bytes, pidx)
            text_all = "\n".join(lines)

            inv_no, inv_dt = '', ''
            for ln in lines[:10]:
                m_no = INV_NO_RX.search(ln)
                if m_no: inv_no = m_no.group(1).strip()
                m_dt = INV_DT_RX.search(ln)
                if m_dt: inv_dt = m_dt.group(1).strip()
            if not inv_no:
                m = re.search(r"(\d{4}-\d+[A-Z]?)", text_all)
                inv_no = m.group(1) if m else ''
            if not inv_dt:
                m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})", text_all)
                inv_dt = m.group(1) if m else ''

            start_items = next((i for i, ln in enumerate(lines) if TABLE_HDR_RX.search(ln)), None)
            break_idx = next((i for i, ln in enumerate(lines) if BREAK_RX.search(ln)), None)

            parsed_items, tax_items = [], []
            if start_items is not None:
                end_items = break_idx if break_idx is not None else len(lines)
                for ln in lines[start_items + 1:end_items]:
                    m = AMOUNT_RX.search(ln)
                    if m:
                        try:
                            amt = normalize_amount(m.group(1))
                        except InvalidOperation:
                            continue
                        desc = ln[:m.start()].strip()
                        parsed_items.append((desc, amt))

            if break_idx is not None:
                end_tax = next((i for i, ln in enumerate(lines) if INVOICE_TOTAL_LABEL_RX.search(ln)), len(lines))
                for ln in lines[break_idx + 1:end_tax]:
                    m = AMOUNT_RX.search(ln)
                    if m:
                        try:
                            amt = normalize_amount(m.group(1))
                        except InvalidOperation:
                            continue
                        desc = ln[:m.start()].strip()
                        tax_items.append((desc, amt))

            total_val = None
            for i, ln in enumerate(lines):
                if INVOICE_TOTAL_LABEL_RX.search(ln) and i + 1 < len(lines):
                    m = AMOUNT_RX.search(lines[i + 1])
                    if m:
                        try:
                            total_val = normalize_amount(m.group(1))
                        except InvalidOperation:
                            pass
                        break

            all_sum = sum(a for _, a in parsed_items + tax_items)
            if total_val is None:
                for ln in reversed(lines):
                    m = AMOUNT_RX.search(ln)
                    if m:
                        try:
                            val = normalize_amount(m.group(1))
                        except InvalidOperation:
                            continue
                        if val >= all_sum:
                            total_val = val
                            break

            issues = []
            if not inv_no: issues.append('invoice_number_missing')
            if not inv_dt: issues.append('invoice_date_missing')
            if not parsed_items: issues.append('no_line_items')
            if total_val is None: issues.append('total_missing')
            elif abs(all_sum - total_val) > TOLERANCE: issues.append('total_mismatch')

            for desc, amt in parsed_items + tax_items:
                rows.append({
                    'source_file': os.path.basename(path),
                    'vendor_name': VENDOR_NAME,
                    'invoice_number': inv_no,
                    'invoice_date': inv_dt,
                    'total_amount': f"{total_val:.2f}" if total_val is not None else '',
                    'line_item_description': desc,
                    'line_item_amount': f"{amt:.2f}",
                    'check_needed': str(bool(issues)).upper(),
                    'parsing_issues': ';'.join(issues)
                })

    return rows
