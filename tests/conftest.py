import shutil
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


def make_pdf(pages: list[str]) -> bytes:
    """PDF minimal valide, une page par chaîne (lignes séparées par \\n), lisible par pypdf."""

    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # arbre des pages, complété plus bas
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    page_refs = []
    for text in pages:
        lines = " T* ".join(f"({escape(line)}) Tj" for line in text.split("\n"))
        stream = f"BT /F1 10 Tf 14 TL 40 800 Td {lines} ET".encode("cp1252")
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        content_ref = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_ref
        )
        page_refs.append(len(objects))
    kids = " ".join(f"{ref} 0 R" for ref in page_refs).encode()
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


@pytest.fixture
def lab_root(tmp_path, monkeypatch) -> Path:
    """Dépôt temporaire avec la vraie configuration, sans attente entre requêtes ni relances lentes."""
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    sources_file = tmp_path / "config" / "academic-sources.yaml"
    sources = yaml.safe_load(sources_file.read_text())
    sources["retry"]["backoff_seconds"] = 0
    for provider in sources["providers"].values():
        provider["min_interval_seconds"] = 0
    sources["fulltext"]["min_interval_seconds"] = 0
    sources["fulltext"]["min_extracted_chars"] = 50
    sources_file.write_text(yaml.safe_dump(sources))
    monkeypatch.setenv("RESEARCH_LAB_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)
    return tmp_path
