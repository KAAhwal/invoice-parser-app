
# Vendor Invoice Parser App

This Streamlit app allows you to upload a ZIP of invoice PDFs from different vendors and parse them using their specific logic.

## 🧾 Supported Vendors

- Flint Hills
- Boyett
- Dale
- Marathon
- BB Energy

## ⚙️ How to Use

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Launch the app:

```bash
streamlit run app.py
```

3. Select a vendor, upload a ZIP of PDF invoices, and download the extracted CSV.

Each vendor has its own parser defined in a separate `.py` file.
