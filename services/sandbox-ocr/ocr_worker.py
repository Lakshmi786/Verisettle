"""The actual OCR work, run as a Landlock-sandboxed subprocess by ocr.py.
Reads the file at INPUT_PATH (under the read-only /input mount), writes
/scratch/output.txt. No network, no other filesystem access, non-root, all
capabilities dropped - the sandbox-runner service enforces that at the
`docker run` layer; ocr.py enforces the Landlock ruleset (read-only /input,
read-write /scratch, no network) one level deeper before this script even
starts; this script just does the OCR work."""
import os
import sys

import pytesseract
from PIL import Image

SCRATCH = "/scratch"


def main():
    input_path = os.environ.get("INPUT_PATH")
    if not input_path or not os.path.exists(input_path):
        print(f"input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    image = Image.open(input_path)
    text = pytesseract.image_to_string(image)

    with open(f"{SCRATCH}/output.txt", "w") as f:
        f.write(text)
    print(f"OCR complete: {len(text)} chars extracted")


if __name__ == "__main__":
    main()
