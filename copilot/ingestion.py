"""Extract embedded PDF text first; OCR only pages without sufficient text."""

import hashlib
from pathlib import Path

from copilot.models import Document


def extract_file(path: Path, ocr=False):
    if path.suffix.lower() in {".txt", ".md"}:
        return path.read_text(encoding="utf-8"), {"pages": 1, "ocr_pages": []}
    if path.suffix.lower() != ".pdf":
        raise ValueError("Supported formats: .txt, .md, .pdf")
    import pdfplumber

    texts, ocr_pages = [], []
    with pdfplumber.open(path) as reader:
        for i, page in enumerate(reader.pages):
            content = page.extract_text() or ""
            if len(content.strip()) < 30:
                if not ocr:
                    raise ValueError(f"Page {i + 1} has little text. Inspect it or rerun with --ocr.")
                import pytesseract

                content = pytesseract.image_to_string(page.to_image(resolution=200).original)
                ocr_pages.append(i + 1)
            if not content.strip():
                raise ValueError(f"No text extracted from page {i + 1}")
            texts.append(f"[Page {i + 1}]\n{content}")
    return "\n\n".join(texts), {"pages": len(texts), "ocr_pages": ocr_pages}


def ingest(session, path, tenant, title=None, kind="product", ocr=False):
    path = Path(path)
    body, stats = extract_file(path, ocr)
    if not body.strip():
        raise ValueError("No text extracted")
    key = f"{tenant}:upload-{hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20]}"
    doc = session.get(Document, key)
    if doc:
        if doc.body != body or doc.title != (title or path.stem) or doc.kind != kind:
            doc.body, doc.title, doc.kind = body, title or path.stem, kind
            doc.revision += 1
    else:
        doc = Document(id=key, tenant=tenant, title=title or path.stem, kind=kind, body=body)
        session.add(doc)
    session.commit()
    return {"id": doc.id, "revision": doc.revision, **stats}
