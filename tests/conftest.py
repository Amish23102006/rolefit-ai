import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

PUBLIC_RESOLVER = lambda host, port: ["93.184.216.34"]
PW = "correct-horse-battery-staple"


@pytest.fixture
def make_client(tmp_path):
    def _make(llm=None, **overrides):
        st = Settings(db_path=str(tmp_path / "t.db"), jwt_secret="s" * 48, **overrides)
        return TestClient(create_app(st, resolver=PUBLIC_RESOLVER, llm_transport=llm))
    return _make


@pytest.fixture
def client(make_client):
    return make_client()


def signup(client, email="alice@example.test"):
    assert client.post("/auth/register", json={"email": email, "password": PW}).status_code == 201
    tok = client.post("/auth/login", json={"email": email, "password": PW}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def make_docx(body_xml: str, extra: dict = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types></Types>")
        z.writestr("word/document.xml", f"<w:document><w:body>{body_xml}</w:body></w:document>")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


def read_fixture(name):
    with open(f"tests/fixtures/{name}", encoding="utf8") as f:
        return f.read()
