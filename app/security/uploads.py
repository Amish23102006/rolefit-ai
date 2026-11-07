"""Defensive upload validation + safe static text extraction. Nothing is ever executed."""
import hashlib
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

ALLOWED_EXT = {".txt", ".docx", ".pdf"}
MAX_ZIP_ENTRIES, MAX_UNCOMPRESSED, MAX_RATIO, MAX_PDF_PAGES = 200, 20 * 1024 * 1024, 100, 20
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class UploadRejected(ValueError):
    pass


@dataclass
class Extracted:
    filename: str
    sha256: str
    size: int
    mime: str
    text: str
    flags: list = field(default_factory=list)


def safe_filename(name: str) -> str:
    base = PurePosixPath((name or "upload").replace("\\", "/")).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:100] or "upload"


def scan_malware(data: bytes) -> None:
    """Hook for a real scanner (e.g. ClamAV via clamd). MVP detects only the EICAR test string."""
    if EICAR in data:
        raise UploadRejected("Malware signature detected; file quarantined")


def _docx_text(data: bytes, flags: list) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UploadRejected("Malformed DOCX")
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UploadRejected("Archive has too many entries")
    total = 0
    for i in infos:
        n = i.filename
        if n.startswith("/") or ".." in PurePosixPath(n).parts:
            raise UploadRejected("Unsafe path inside archive")
        if "vbaproject" in n.lower() or n.lower().endswith((".bin", ".exe", ".dll")) and "vba" in n.lower():
            raise UploadRejected("Macros are not accepted")
        total += i.file_size
        if i.compress_size and i.file_size / max(i.compress_size, 1) > MAX_RATIO:
            raise UploadRejected("Suspicious compression ratio (archive bomb)")
    if total > MAX_UNCOMPRESSED:
        raise UploadRejected("Archive too large when decompressed")
    ct = zf.read("[Content_Types].xml").decode("utf8", "ignore") if "[Content_Types].xml" in zf.namelist() else ""
    if "macroEnabled" in ct:
        raise UploadRejected("Macro-enabled document rejected")
    if "word/document.xml" not in zf.namelist():
        raise UploadRejected("Not a valid DOCX")
    xml = zf.read("word/document.xml").decode("utf8", "ignore")
    if re.search(r'<w:vanish\b|w:color w:val="FFFFFF"', xml, re.I):
        flags.append("HIDDEN_TEXT_SUSPECTED")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab\s*/>", "\t", xml)
    parts = re.findall(r"<w:t[^>]*>(.*?)</w:t>|(\n)", xml, re.S)
    text = "".join(t or nl for t, nl in parts)
    return html.unescape(text)


def _pdf_text(data: bytes, flags: list) -> str:
    for token in (b"/JavaScript", b"/JS", b"/Launch", b"/OpenAction", b"/EmbeddedFile"):
        if token in data:
            raise UploadRejected("PDF contains active/embedded content and was rejected")
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        raise UploadRejected("PDF text extraction is not enabled on this server (install pypdf)")
    try:
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise UploadRejected("PDF has too many pages")
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except UploadRejected:
        raise
    except Exception:
        raise UploadRejected("Malformed PDF")
    if len(text.strip()) < 20:
        flags.append("NO_EXTRACTABLE_TEXT_POSSIBLY_SCANNED")
    return text


def validate_and_extract(filename: str, data: bytes, max_bytes: int) -> Extracted:
    name = safe_filename(filename)
    ext = PurePosixPath(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UploadRejected("Unsupported file type")
    if not data:
        raise UploadRejected("Empty file")
    if len(data) > max_bytes:
        raise UploadRejected("File too large")
    flags: list = []
    scan_malware(data)
    if ext == ".docx":
        if not data.startswith(b"PK\x03\x04"):
            raise UploadRejected("File signature does not match DOCX")
        text, mime = _docx_text(data, flags), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise UploadRejected("File signature does not match PDF")
        text, mime = _pdf_text(data, flags), "application/pdf"
    else:
        if b"\x00" in data or data.startswith((b"PK\x03\x04", b"%PDF-", b"MZ")):
            raise UploadRejected("File content does not match text type")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadRejected("Text files must be UTF-8")
        mime = "text/plain"
    return Extracted(name, hashlib.sha256(data).hexdigest(), len(data), mime, text, flags)
