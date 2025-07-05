import streamlit as st
import zipfile
import os
import tempfile
import importlib.util
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# Title
st.title("Vendor Invoice Parser with Caching & Parallelism")

# Vendor parser map (vendor name → module name without .py)
VENDOR_PARSERS = {
    "Flint Hills": "parse_flinthills",
    "Boyett":      "parse_boyett",
    "Dale":        "parse_dale",
    "Marathon":    "parse_marathon",
    "BB Energy":   "parse_bbenergy",
}

# 1. Vendor selection
vendor = st.selectbox("Select vendor", list(VENDOR_PARSERS.keys()))
parser_module_name = VENDOR_PARSERS[vendor]

# 2. File uploader
uploaded_zip = st.file_uploader(
    "Upload ZIP file containing PDF invoices", type="zip"
)

@st.cache_data(show_spinner=False)
def run_full_parse(zip_bytes, parser_module_name):
    # Unzip and parse all PDFs, returning rows list
    with tempfile.TemporaryDirectory() as tmpdir:
        # write and extract zip
        zip_path = os.path.join(tmpdir, "invoices.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmpdir)

        # load parser module
        spec = importlib.util.spec_from_file_location(
            parser_module_name, os.path.join(os.getcwd(), f"{parser_module_name}.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "parse"):
            raise RuntimeError(f"Parser {parser_module_name}.py has no parse() function.")
        parse_function = module.parse

        # discover PDF files
        pdf_files = [fname for fname in os.listdir(tmpdir) if fname.lower().endswith('.pdf')]
        all_rows = []
        # parallel parse
        def parse_one(fname):
            path = os.path.join(tmpdir, fname)
            try:
                with open(path, 'rb') as f:
                    rows = parse_function(f) or []
                for row in rows:
                    row['source_file'] = fname
                return fname, rows, None
            except Exception as e:
                return fname, [], str(e)

        with ThreadPoolExecutor(max_workers=4) as executor:
            for fname, rows, err in executor.map(parse_one, pdf_files):
                if rows:
                    all_rows.extend(rows)
                # We ignore errors here; rows empty will mark failure
        return all_rows, pdf_files

if st.button("Run Parser") and uploaded_zip:
    # Run and cache
    all_rows, pdf_files = run_full_parse(uploaded_zip.getvalue(), parser_module_name)

    # Compute parsed vs failed
    parsed_files = set(row['source_file'] for row in all_rows)
    total = len(pdf_files)
    parsed = len(parsed_files)
    failed = sorted(set(pdf_files) - parsed_files)

    # Display summary
    st.markdown(f"**Uploaded:** {total}   **Parsed:** {parsed}   **Failed:** {len(failed)}")
    if failed:
        st.error("Files with no parsed rows:")
        for fn in failed:
            st.write(f"• {fn}")

    # Show DataFrame
    if all_rows:
        df = pd.DataFrame(all_rows)
        st.success(f"Parsed {len(df)} rows total.")
        st.dataframe(df)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Download CSV", csv, file_name="parsed_output.csv", mime="text/csv")
    else:
        st.warning("No rows parsed.")
