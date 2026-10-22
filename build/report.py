"""Show a log file on the GitHub build page (as a note), so problems can be read
without downloading anything.   python build/report.py <file> <title> [error]"""
import sys
from pathlib import Path

path, title = sys.argv[1], sys.argv[2]
kind = "error" if len(sys.argv) > 3 else "notice"
try:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
except OSError:
    text = "(no log)"
print(text)
tail = text[-3500:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
print(f"::{kind} title={title}::{tail}")
