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
    "Boyett": "parse_boyett",
    "Dale": "parse_dale",
    "Marathon": "parse_marathon",
    "BB Energy": "parse_bbenergy"
}

# Vendor selection
vendor = st.selectbox("Select Vendor", list(VENDOR_PARSERS.keys()))
uploaded_zip = st.file_uploader("Upload ZIP file containing PDFs", type="zip")

if uploaded_zip and vendor:
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "invoices.zip")
        with open(zip_path, "wb") as f:
            f.write(uploaded_zip.read())

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(tmpdir)

        # Load the parser module dynamically
        module_name = VENDOR_PARSERS[vendor]
        parser_path = os.path.join(os.path.dirname(__file__), f"{module_name}.py")

        if not os.path.exists(parser_path):
            st.error(f"Parser file not found: {module_name}.py")
            st.stop()

        spec = importlib.util.spec_from_file_location(module_name, parser_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Always call the 'parse' function
        try:
            parse_function = getattr(module, "parse")
        except AttributeError:
            st.error(f"'{module_name}.py' does not contain a 'parse' function.")
            st.stop()

        # Process each PDF file
        all_rows = []
        for fname in os.listdir(tmpdir):
            if fname.lower().endswith(".pdf"):
                try:
                    pdf_path = os.path.join(tmpdir, fname)
                    with open(pdf_path, "rb") as f:
                        rows = parse_function(f)
                        for row in rows:
                            row["source_file"] = fname
                        all_rows.extend(rows)
                except Exception as e:
                    st.error(f"Error parsing {fname}: {e}")

        if all_rows:
            df = pd.DataFrame(all_rows)
            st.success(f"Parsed {len(df)} rows.")
            st.dataframe(df)

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", csv, file_name="parsed_output.csv", mime="text/csv")
        else:
            st.warning("No valid rows parsed.")
