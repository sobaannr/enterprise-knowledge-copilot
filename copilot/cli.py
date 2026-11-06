import argparse
import json

from copilot import models  # noqa: F401 -- register all tables before create_all

from copilot.config import get_settings
from copilot.db import Base, make_database


def main():
    parser = argparse.ArgumentParser(description="Manage the copilot's local corpus")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    commands.add_parser("index")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--offline", action="store_true", help="Run fixture evaluation with no API calls")
    evaluation.add_argument("--output", default="reports/evaluation.json")
    access = commands.add_parser("access")
    access.add_argument("document_id")
    access.add_argument("--roles", nargs="*", choices=["operator", "analyst"], default=[])
    doctor = commands.add_parser("doctor")
    doctor.add_argument(
        "--live", action="store_true", help="Make two small Gemini requests to check model access"
    )
    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("path")
    ingest_parser.add_argument("--title")
    ingest_parser.add_argument(
        "--kind", choices=["product", "support", "incident", "policy"], default="product"
    )
    ingest_parser.add_argument("--ocr", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "evaluate" and args.offline:
        settings = settings.model_copy(
            update={"retrieval_backend": "local", "generation_backend": "extractive", "rerank": False}
        )
    engine, sessions = make_database(settings.database_url)
    Base.metadata.create_all(engine)
    with sessions() as session:
        if args.command == "access":
            from copilot.models import Document, DocumentAccess

            doc = session.get(Document, args.document_id)
            if not doc or doc.tenant != settings.tenant:
                parser.error("Document not found in configured tenant")
            rule = session.get(DocumentAccess, doc.id)
            if rule:
                rule.allowed_roles = args.roles
            else:
                session.add(DocumentAccess(document_id=doc.id, allowed_roles=args.roles))
            session.commit()
            print("Document role access updated.")
        if args.command == "doctor":
            from copilot.gemini import Gemini, GeminiError, Rewrite
            from sqlalchemy import text

            session.execute(text("SELECT 1"))
            configured = bool(settings.gemini_api_key.get_secret_value().strip())
            print("Database: connected (tables initialize automatically)")
            print(f"Retrieval: {settings.retrieval_backend}; generation: {settings.generation_backend}")
            print(
                f"Gemini key: {'configured (hidden)' if configured else 'MISSING - fill GEMINI_API_KEY in .env'}"
            )
            print(f"Models: {settings.gemini_generation_model}, {settings.gemini_embedding_model}")
            if args.live:
                try:
                    provider = Gemini(settings)
                    provider.generate("Return query = 'connection check'.", {}, Rewrite)
                    provider.embed(["Connection check"], "RETRIEVAL_QUERY")
                    print("Live generation and embedding checks passed.")
                except GeminiError as exc:
                    print(str(exc))
                    raise SystemExit(1) from None
        if args.command == "seed":
            from copilot.seed import seed

            seed(session, settings.tenant)
            print("Fictional company data is ready.")
        elif args.command == "index":
            from copilot.retrieval import index_documents

            print(f"Indexed {index_documents(session, settings)} chunks.")
        elif args.command == "ingest":
            from copilot.ingestion import ingest

            print(json.dumps(ingest(session, args.path, settings.tenant, args.title, args.kind, args.ocr)))
        elif args.command == "evaluate":
            from copilot.evaluation import evaluate

            report = evaluate(session, settings)
            from pathlib import Path

            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            print(f"Report saved: {output.resolve()}")
            if not report["passed"]:
                raise SystemExit(1)
    engine.dispose()


if __name__ == "__main__":
    main()
