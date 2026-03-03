import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Folder where OCR outputs are stored
OUTPUT_PATH = os.path.join(BASE_DIR, "ocr_outputs")

# Supported file extensions
EXTENSION_LIST = [
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf"
]


