"""Turn an uploaded brief (.docx / .pdf / .txt) into plain text.

These files come from the user and are untrusted, so this runs inside the
sealed app container and refuses anything past hard caps rather than trying
to be clever about what is hostile:

  * 10 MB upload
  * .docx: 50 MB total uncompressed (zip/docx expansion bombs), only the
    document and footnote/endnote parts are read -- briefs cite in footnotes
  * .pdf: 300 pages
No external converters, no shelling out.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

MAX_UPLOAD = 10 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_PDF_PAGES = 300

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ExtractError(ValueError):
    pass


def _docx(data: bytes) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExtractError("not a .docx (not a zip container)")
    total = sum(i.file_size for i in z.infolist())
    if total > MAX_DOCX_UNCOMPRESSED:
        raise ExtractError(f"docx expands to {total/1e6:.0f} MB; cap is {MAX_DOCX_UNCOMPRESSED/1e6:.0f} MB")
    parts = ["word/document.xml", "word/footnotes.xml", "word/endnotes.xml"]
    out = []
    for name in parts:
        if name not in z.namelist():
            continue
        try:
            root = ET.fromstring(z.read(name))
        except ET.ParseError:
            raise ExtractError(f"{name} is not well-formed XML")
        # one line per paragraph; tabs and breaks become spaces
        for p in root.iter(_W + "p"):
            texts = []
            for node in p.iter():
                if node.tag == _W + "t" and node.text:
                    texts.append(node.text)
                elif node.tag in (_W + "tab",):
                    texts.append(" ")
                elif node.tag in (_W + "br", _W + "cr"):
                    texts.append(" ")
            line = "".join(texts).strip()
            if line:
                out.append(line)
        if name == "word/document.xml" and out:
            out.append("")          # blank line before footnotes
    text = "\n".join(out)
    if not text.strip():
        raise ExtractError("no text found in the .docx")
    return text


def _pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ExtractError("PDF support not installed (pypdf)")
    try:
        r = PdfReader(io.BytesIO(data))
        n = len(r.pages)
    except Exception as e:
        raise ExtractError(f"could not open PDF: {str(e)[:80]}")
    if n > MAX_PDF_PAGES:
        raise ExtractError(f"{n} pages; cap is {MAX_PDF_PAGES}")
    if getattr(r, "is_encrypted", False):
        try:
            r.decrypt("")
        except Exception:
            raise ExtractError("PDF is encrypted")
    out = []
    for i in range(n):
        try:
            out.append(r.pages[i].extract_text() or "")
        except Exception as e:
            raise ExtractError(f"page {i+1}: {str(e)[:80]}")
    text = "\n".join(out)
    if len(re.sub(r"\s", "", text)) < 50:
        raise ExtractError("PDF has no extractable text (scanned image? run OCR first)")
    return text


def extract(filename: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD:
        raise ExtractError(f"file is {len(data)/1e6:.1f} MB; cap is {MAX_UPLOAD/1e6:.0f} MB")
    name = (filename or "").lower()
    if name.endswith(".docx") or data[:2] == b"PK":
        return _docx(data)
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return _pdf(data)
    if name.endswith((".txt", ".md")) or not name:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")
    if name.endswith(".doc"):
        raise ExtractError("legacy .doc is not supported; save as .docx or PDF")
    raise ExtractError("unsupported file type; use .docx, .pdf or .txt")
