import streamlit as st
import zipfile
import os
import tempfile
import importlib.util
import pandas as pd

# Title
st.title("Vendor Invoice Parser")

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

if uploaded_zip:
    # 3. Extract ZIP to temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "invoices.zip")
        with open(zip_path, "wb") as f:
            f.write(uploaded_zip.getvalue())
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmpdir)

        # 4. Dynamically load the parser module
        spec = importlib.util.spec_from_file_location(
            parser_module_name, os.path.join(os.getcwd(), f"{parser_module_name}.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "parse"):
            st.error(f"'{parser_module_name}.py' does not contain a 'parse' function.")
            st.stop()
        parse_function = module.parse

        # 5. Process each PDF file with success/failure tracking
        all_rows        = []
        successful_pdfs = []
        failed_pdfs     = []

        for fname in os.listdir(tmpdir):
            if not fname.lower().endswith(".pdf"):
                continue
            pdf_path = os.path.join(tmpdir, fname)
            try:
                with open(pdf_path, "rb") as f:
                    rows = parse_function(f)
                # Tag each row with its source filename
                for row in rows:
                    row["source_file"] = fname
                all_rows.extend(rows)
                successful_pdfs.append(fname)
            except Exception as e:
                failed_pdfs.append(fname)

        # 6. Show upload vs parse summary
        total_pdfs   = len(successful_pdfs) + len(failed_pdfs)
        parsed_count = len(successful_pdfs)
        failed_count = len(failed_pdfs)

        st.markdown(
            f"**Uploaded:** {total_pdfs}   "
            f"**Parsed:** {parsed_count}   "
            f"**Failed:** {failed_count}"
        )

        if failed_pdfs:
            st.error("The following files failed to parse:")
            for fn in failed_pdfs:
                st.write(f"• {fn}")

        # 7. Display results
        if all_rows:
            df = pd.DataFrame(all_rows)
            st.success(f"Parsed {len(df)} rows total.")
            st.dataframe(df)

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV",
                csv,
                file_name="parsed_output.csv",
                mime="text/csv",
            )
        else:
            st.warning("No valid rows parsed.")
