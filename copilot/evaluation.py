import json
import math
import time
import hashlib
from pathlib import Path

from copilot.auth import Principal
from copilot.models import utcnow, Document
from sqlalchemy import select
from copilot.retrieval import search_documents
from copilot.workflow import build_workflow


def evaluate(session, settings):
    started = time.perf_counter()
    cases = json.loads((Path(__file__).parent / "data" / "evaluation.json").read_text())
    user = Principal("evaluator", settings.tenant, "analyst")
    rows = []
    for case in cases:
        incident_id = f"{settings.tenant}:{case['incident']}" if case["incident"] else None
        result = build_workflow(session, settings, user).invoke(
            {"question": case["question"], "incident_id": incident_id, "now": utcnow()}
        )["result"]
        actual = sorted(c["id"].split(":")[-1] for c in result.get("affected_customers", []))
        source_ids = {s["id"].split(":")[-1] for s in result["sources"]}
        passed = (
            actual == sorted(case["customers"])
            and len(result["drafts"]) == case["draft_count"]
            and (case["source"] is None or case["source"] in source_ids)
        )
        refs = {s["id"] for s in result["sources"]}
        claims = result.get("findings", []) + result.get("ai_findings", [])
        citation_coverage = (
            sum(bool(c.get("source_ids")) and all(r in refs for r in c["source_ids"]) for c in claims)
            / len(claims)
            if claims
            else None
        )
        rows.append({"question": case["question"], "passed": passed, "citation_coverage": citation_coverage})
    queries = [
        ("approved SAML recovery metadata procedure", "KB-208"),
        ("customer follow-up policy approval", "POL-12"),
        ("API rate limits quota", "KB-301"),
        ("SAML metadata recovery", "KB-208"),
        ("approved workaround authentication", "KB-208"),
        ("human approval account manager follow-up", "POL-12"),
        ("429 retry quota", "KB-301"),
    ]
    retrieval = []
    for query, target in queries:
        ids = [
            h["document_id"].split(":")[-1]
            for h in search_documents(session, settings, user.tenant, query, 3)
        ]
        retrieval.append(
            {
                "query": query,
                "hit_at_3": target in ids,
                "retrieved_ids": ids,
                "expected_document": target,
                "precision_at_3": (1 / 3) if target in ids else 0,
                "ndcg_at_3": 1 / math.log2(ids.index(target) + 2) if target in ids else 0,
                "reciprocal_rank": 1 / (ids.index(target) + 1) if target in ids else 0,
            }
        )
    return {
        "schema_version": 1,
        "corpus_sha256": hashlib.sha256(
            json.dumps(
                [
                    (d.id, d.revision, d.body)
                    for d in session.scalars(
                        select(Document).where(Document.tenant == user.tenant).order_by(Document.id)
                    )
                ]
            ).encode()
        ).hexdigest(),
        "created_at": utcnow().isoformat(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "configuration": {
            "retrieval": settings.retrieval_backend,
            "generation": settings.generation_backend,
            "generation_model": settings.gemini_generation_model,
            "embedding_model": settings.gemini_embedding_model,
        },
        "dataset_sha256": hashlib.sha256(
            json.dumps({"workflow": cases, "retrieval": queries}, sort_keys=True).encode()
        ).hexdigest(),
        "thresholds": {"workflow_accuracy": 1.0, "retrieval_recall_at_3": 1.0},
        "workflow_accuracy": sum(r["passed"] for r in rows) / len(rows),
        "precision_at_3": sum(r["precision_at_3"] for r in retrieval) / len(retrieval),
        "ndcg_at_3": sum(r["ndcg_at_3"] for r in retrieval) / len(retrieval),
        "passed": all(r["passed"] for r in rows) and all(r["hit_at_3"] for r in retrieval),
        "workflow_cases": rows,
        "retrieval_cases": retrieval,
        "hit_rate_at_3": sum(r["hit_at_3"] for r in retrieval) / len(retrieval),
        "mrr_at_3": sum(r["reciprocal_rank"] for r in retrieval) / len(retrieval),
        "note": "Small synthetic regression set; requires independent human review and expansion.",
    }
