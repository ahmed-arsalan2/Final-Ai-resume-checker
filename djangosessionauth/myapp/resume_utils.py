import os
import requests
from pdfminer.high_level import extract_text


def extract_text_with_ocr_space(file_path):
    """
    Uses OCR.Space API as fallback when PDF extraction fails
    or for image files.
    """
    api_key = os.getenv("OCR_SPACE_API_KEY")
    if not api_key:
        return ""

    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                "https://api.ocr.space/parse/image",
                files={"file": f},
                data={
                    "apikey": api_key,
                    "language": "eng",
                },
                timeout=15
            )

        result = response.json()
        parsed = result.get("ParsedResults")

        if parsed and len(parsed) > 0:
            return parsed[0].get("ParsedText", "").strip()

    except Exception:
        return ""

    return ""


def extract_resume_text(file_path):
    """
    Main extraction function.
    - First try pdfminer for PDFs.
    - If empty or file is image → fallback to OCR.Space.
    """

    ext = file_path.split(".")[-1].lower()

    text = ""

    # 1️⃣ If PDF → try pdfminer first
    if ext == "pdf":
        try:
            text = extract_text(file_path).strip()
        except Exception:
            text = ""

        # If PDF extraction failed → OCR fallback
        if not text:
            text = extract_text_with_ocr_space(file_path)

    # 2️⃣ If image → directly use OCR
    elif ext in ["jpg", "jpeg", "png"]:
        text = extract_text_with_ocr_space(file_path)

    return text.strip()