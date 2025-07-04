def parse(f):
    import pdfplumber
    import re
    import os
    import pytesseract
    from pdf2image import convert_from_bytes
    from decimal import Decimal, InvalidOperation
    from io import BytesIO

    VENDOR_NAME  = "BB Energy USA LLC"
    PDF_DPI      = 300
    TOLERANCE    = Decimal("0.01")

    INV_NO_RX     = re.compile(r"Invoice\s*(?:Number|#)[:\s]*(\S+)", re.IGNORECASE)
    INV_DT_RX     = re.compile(r"(?:Invoice\s*Date|Date)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", re.IGNORECASE)
    TABLE_HDR_RX  = re.compile(r"Date\s+Time\s+BOL", re.IGNORECASE)
    BREAK_RX      = re.compile(r"Invoice\s+Terms", re.IGNORECASE)
    AMOUNT_RX     = re.compile(r"(\(?-?[\d,]+\.\d{2}\)?)\s*$")
    INVTOT_HDR_RX = re.compile(r"Invoice\s*Total", re.IGNORECASE)

    def normalize_amount(txt: str) -> Decimal:
        raw = txt.replace(',', '').strip()
        sign = 1
        if raw.startswith('(') and raw.endswith(')'):
            raw = raw[1:-1]
            sign = -1
        elif raw.endswith('-'):
            raw = raw[:-1]
            sign = -1
        elif raw.startswith('-'):
            raw = raw[1:]
            sign = -1
        try:
            val = Decimal(raw)
        except InvalidOperation:
            raise InvalidOperation(f"Cannot parse amount '{txt}'")
        return val * sign

    def extract_text_lines(page, binary_data, pidx):
        txt = page.extract_text() or ''
        ascii_ratio = sum(1 for c in txt if ord(c) < 128) / max(len(txt), 1)
        if ascii_ratio < 0.5:
            images = convert_from_bytes(binary_data, dpi=PDF_DPI, first_page=pidx+1, last_page=pidx+1)
            txt = pytesseract.image_to_string(images[0])
        return [ln.strip() for ln in txt.splitlines() if ln.strip()]

    # Read file in memory for OCR fallback
    binary_data = f.read()
    f.seek(0)

    results = []
    with pdfplumber.open(BytesIO(binary_data)) as pdf:
        for pidx, page in enumerate(pdf.pages):
            lines = extract_text_lines(page, binary_data, pidx)

            inv_no, inv_dt = '', ''
            for ln in lines[:10]:
                if not inv_no:
                    m = INV_NO_RX.search(ln)
                    if m: inv_no = m.group(1)
                if not inv_dt:
                    m = INV_DT_RX.search(ln)
                    if m: inv_dt = m.group(1)

            start_idx = next((i for i, ln in enumerate(lines) if TABLE_HDR_RX.search(ln)), None)
            if start_idx is None:
                continue

            break_idx = next((i for i, ln in enumerate(lines) if BREAK_RX.search(ln)), None)
            end_idx = break_idx if break_idx is not None else len(lines)

            items = []
            for ln in lines[start_idx+1:end_idx]:
                m = AMOUNT_RX.search(ln)
                if not m:
                    continue
                desc = ln[:m.start()].strip()
                if desc == 'Total:':
                    continue
                try:
                    amt = normalize_amount(m.group(1))
                except InvalidOperation:
                    continue
                items.append((desc, amt))

            total_val = None
            for i, ln in enumerate(lines):
                if INVTOT_HDR_RX.search(ln):
                    m = AMOUNT_RX.search(ln)
                    if not m and i+1 < len(lines):
                        m = AMOUNT_RX.search(lines[i+1])
                    if m:
                        try:
                            total_val = normalize_amount(m.group(1))
                        except InvalidOperation:
                            pass
                    break

            if total_val is None and items:
                sum_items = sum(amt for _, amt in items)
                candidates = [amt for _, amt in items if abs(amt) >= abs(sum_items)]
                if candidates:
                    total_val = max(candidates, key=lambda x: abs(x))

            issues = []
            if not inv_no: issues.append('invoice_number_missing')
            if not inv_dt: issues.append('invoice_date_missing')
            if not items: issues.append('no_line_items')
            if total_val is None: issues.append('total_missing')
            elif items and abs(sum(amt for _, amt in items) - total_val) > TOLERANCE:
                issues.append('total_mismatch')

            for desc, amt in items:
                results.append({
                    'source_file': "uploaded_file.pdf",
                    'vendor_name': VENDOR_NAME,
                    'invoice_number': inv_no,
                    'invoice_date': inv_dt,
                    'total_amount': float(total_val) if total_val is not None else '',
                    'line_item_description': desc,
                    'line_item_amount': float(amt),
                    'check_needed': bool(issues),
                    'parsing_issues': ';'.join(issues)
                })

    return results
