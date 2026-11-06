from pathlib import Path

import pytest

from copilot.ingestion import extract_file, ingest
from copilot.retrieval import chunk_text


def test_chunk_overlap():
    chunks = chunk_text("one two three four five six", size=4, overlap=1)
    assert chunks == ["one two three four", "four five six"]
    with pytest.raises(ValueError):
        chunk_text("some text", size=2, overlap=2)


def test_ingestion_updates_revision(client, app, tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("Approved recovery procedure.", encoding="utf-8")
    with app.state.sessions() as session:
        first = ingest(session, path, "acme")
        assert ingest(session, path, "acme")["revision"] == first["revision"]
        path.write_text("Revised approved recovery procedure.", encoding="utf-8")
        changed = ingest(session, path, "acme")
        assert changed["id"] == first["id"]
        assert changed["revision"] == first["revision"] + 1


def test_unsupported_format():
    with pytest.raises(ValueError, match="Supported formats"):
        extract_file(Path("untrusted.exe"))
