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

        # Gather all PDF filenames once
        pdf_files = [
            fname
            for fname in os.listdir(tmpdir)
            if fname.lower().endswith(".pdf")
        ]

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

        # 5. Run parsing
        all_rows = []
        for fname in pdf_files:
            pdf_path = os.path.join(tmpdir, fname)
            try:
                with open(pdf_path, "rb") as f:
                    rows = parse_function(f) or []
                # Tag each row
                for row in rows:
                    row["source_file"] = fname
                all_rows.extend(rows)
            except Exception as e:
                # In case of exception, we still continue (zero rows added)
                st.warning(f"Error parsing {fname}: {e}")

        # 6. Compute success/failure by presence in all_rows
        parsed_files = set(row["source_file"] for row in all_rows)
        total_unique  = len(pdf_files)
        parsed_unique = len(parsed_files)
        failed_files  = sorted(set(pdf_files) - parsed_files)
        failed_unique = len(failed_files)

        # 7. Display summary
        st.markdown(
            f"**Uploaded:** {total_unique}   "
            f"**Parsed:** {parsed_unique}   "
            f"**Failed:** {failed_unique}"
        )
        if failed_files:
            st.error("The following files produced no rows:")
            for fn in failed_files:
                st.write(f"• {fn}")

        # 8. Show DataFrame & download button
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
            st.warning("No valid rows parsed in any file.")
