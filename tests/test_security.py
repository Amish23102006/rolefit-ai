import pytest

from app.security.ssrf import UnsafeURL, validate_url
from app.security.uploads import EICAR, UploadRejected, validate_and_extract
from tests.conftest import make_docx

ALLOW = ("boards.greenhouse.io",)
PUB = lambda h, p: ["93.184.216.34"]


def test_ssrf_accepts_allowlisted():
    assert validate_url("https://boards.greenhouse.io/x/jobs/1", ALLOW, True, PUB)


@pytest.mark.parametrize("url", [
    "http://boards.greenhouse.io/x", "https://127.0.0.1/", "https://169.254.169.254/latest/meta-data/",
    "https://evil.example.com/", "https://boards.greenhouse.io.evil.com/", "https://user:pw@boards.greenhouse.io/",
    "https://boards.greenhouse.io:8443/", "file:///etc/passwd", "https://[::1]/"])
def test_ssrf_rejects(url):
    with pytest.raises(UnsafeURL):
        validate_url(url, ALLOW, True, PUB)


def test_ssrf_rejects_dns_rebinding_to_private_and_metadata():
    for ip in ("10.0.0.5", "127.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"):
        with pytest.raises(UnsafeURL):
            validate_url("https://boards.greenhouse.io/", ALLOW, True, lambda h, p, ip=ip: [ip])


def test_upload_text_ok_and_docx_ok():
    assert validate_and_extract("cv.txt", b"hello world", 1000).text == "hello world"
    d = validate_and_extract("cv.docx", make_docx("<w:p><w:r><w:t>Python &amp; SQL</w:t></w:r></w:p>"), 10 ** 6)
    assert "Python & SQL" in d.text


def test_upload_rejections():
    cases = [("a.exe", b"MZ"), ("a.txt", b"MZ\x90\x00"), ("a.docx", b"not a zip"), ("a.pdf", b"nope"),
             ("a.txt", b""), ("a.txt", EICAR), ("a.txt", b"x" * 2000),
             ("a.docx", make_docx("", {"word/vbaProject.bin": "x"})),
             ("a.pdf", b"%PDF-1.4 /JavaScript (app.alert(1))"),
             ("a.docx", make_docx("", {"../evil.txt": "x"}))]
    for name, data in cases:
        with pytest.raises(UploadRejected):
            validate_and_extract(name, data, 1000 if len(data) < 1500 else 1500)


def test_zip_bomb_rejected():
    with pytest.raises(UploadRejected):
        validate_and_extract("a.docx", make_docx("", {"word/big.xml": "0" * (30 * 1024 * 1024)}), 10 ** 7)


def test_hidden_text_flagged():
    d = validate_and_extract("a.docx", make_docx('<w:p><w:r><w:rPr><w:color w:val="FFFFFF"/></w:rPr><w:t>secret</w:t></w:r></w:p>'), 10 ** 6)
    assert "HIDDEN_TEXT_SUSPECTED" in d.flags
