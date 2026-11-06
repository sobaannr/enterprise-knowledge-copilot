import json
import os
import subprocess
import sys

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from copilot.config import Settings
from copilot.gemini import Answer, Claim, Gemini, GeminiError, Rewrite, plan_followups, verify_claims
from copilot.gemini_retrieval import cached_vectors
from copilot.models import Document, EmbeddingCache
from tests.conftest import analyze


@pytest.fixture
def gemini_app(app, monkeypatch):
    settings = app.state.settings
    settings.retrieval_backend = "gemini"
    settings.generation_backend = "gemini"
    settings.gemini_api_key = SecretStr("test-key-not-real")
    calls = []

    def respond(self, model, method, payload):
        calls.append((method, payload))
        if method == "batchEmbedContents":
            return {
                "embeddings": [
                    {"values": [1.0] + [0.0] * (settings.gemini_dimensions - 1)} for _ in payload["requests"]
                ]
            }
        instruction = payload["systemInstruction"]["parts"][0]["text"]
        data = json.loads(payload["contents"][0]["parts"][0]["text"])
        if "tools" in payload:
            part = {
                "functionCall": {
                    "name": "prepare_followups",
                    "args": {
                        "incident_id": data["incident_id"],
                        "customer_ids": data["eligible_customer_ids"],
                    },
                }
            }
        else:
            if instruction.startswith("Rewrite"):
                output = {"query": data["question"]}
            elif instruction.startswith("Rank"):
                output = {"chunk_ids": [c["chunk_id"] for c in data["chunks"]]}
            elif instruction.startswith("Answer"):
                source = next(s for s in data["sources"] if "KB-208" in s["id"])
                output = {
                    "claims": [
                        {
                            "text": "The approved workaround refreshes SAML metadata.",
                            "source_ids": [source["id"]],
                        }
                    ]
                }
            else:
                output = {
                    "verdicts": [{"claim_index": i, "supported": True} for i in range(len(data["claims"]))]
                }
            part = {"text": json.dumps(output)}
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [part]}}]}

    monkeypatch.setattr(Gemini, "post", respond)
    return calls


def test_gemini_workflow_and_approval(client, app, admin, gemini_app):
    result = analyze(client, admin)
    assert result["answer_mode"] == "gemini"
    assert result["verification"]["passed"]
    assert result["ai_findings"][0]["source_ids"] == ["acme:KB-208"]
    assert result["action_plan"]["requires_human_approval"]
    assert len(result["drafts"]) == 2
    assert client.get("/api/tickets", headers=admin).json() == []
    proposal = result["proposal"]
    decision = {"digest": proposal["digest"], "decision": "approve"}
    path = f"/api/proposals/{proposal['id']}/decision"
    first = client.post(path, headers=admin, json=decision)
    assert first.status_code == 200
    assert client.post(path, headers=admin, json=decision).json() == first.json()
    assert len(first.json()["tickets"]) == 2
    assert sum(method == "generateContent" for method, _ in gemini_app) == 5


def test_embeddings_reused_and_content_changes_invalidate(client, app, admin, gemini_app):
    query = {"q": "SAML metadata"}
    client.get("/api/search", headers=admin, params=query)
    count = sum(m == "batchEmbedContents" for m, _ in gemini_app)
    client.get("/api/search", headers=admin, params=query)
    assert sum(m == "batchEmbedContents" for m, _ in gemini_app) == count
    with app.state.sessions() as session:
        session.get(Document, "acme:KB-208").body += " New revision."
        session.commit()
    client.get("/api/search", headers=admin, params=query)
    assert sum(m == "batchEmbedContents" for m, _ in gemini_app) == count + 1


def test_embedding_cache_tenant_partition(client, app, gemini_app):
    with app.state.sessions() as session:
        for tenant in ["acme", "other"]:
            cached_vectors(session, app.state.settings, tenant, ["Same text"], "RETRIEVAL_DOCUMENT")
        assert session.scalar(select(func.count()).select_from(EmbeddingCache)) == 2


def test_missing_key_is_actionable_and_hidden(client, app, admin):
    app.state.settings.generation_backend = "gemini"
    app.state.settings.gemini_api_key = SecretStr("")
    response = client.post("/api/runs", headers=admin, json={"question": "Analyze INC-1042"})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
    assert not client.get("/api/tickets", headers=admin).json()


def test_invalid_citations_and_missing_verdicts_fail_closed(monkeypatch):
    settings = Settings(gemini_api_key=SecretStr("fake"), _env_file=None)
    from copilot.gemini import Verification, Verdict

    monkeypatch.setattr(
        Gemini, "generate", lambda *a, **k: Verification(verdicts=[Verdict(claim_index=0, supported=True)])
    )
    claims = [Claim(text="Unsupported", source_ids=["invented"])]
    accepted, metrics = verify_claims(settings, claims, [{"id": "real", "excerpt": "Text"}])
    assert not accepted and metrics["unsupported_claim_rate"] == 1
    claims = [Claim(text="Text", source_ids=["real"]), Claim(text="Text two", source_ids=["real"])]
    accepted, metrics = verify_claims(settings, claims, [{"id": "real", "excerpt": "Text"}])
    assert not accepted and metrics["rejected"] == 2


def test_tool_plan_cannot_expand_scope(monkeypatch):
    settings = Settings(gemini_api_key=SecretStr("fake"), _env_file=None)
    monkeypatch.setattr(
        Gemini,
        "generate",
        lambda *a, **k: {
            "name": "approve_tickets",
            "args": {"incident_id": "acme:INC-1042", "customer_ids": ["acme:northstar", "other:target"]},
        },
    )
    with pytest.raises(GeminiError, match="did not match"):
        plan_followups(settings, "Do it", "acme:INC-1042", [{"customer_id": "acme:northstar"}])


def test_http_uses_header_and_redacts_provider_error(monkeypatch):
    settings = Settings(gemini_api_key=SecretStr("fake-secret"), _env_file=None)

    def respond(url, **kwargs):
        assert "fake-secret" not in url
        assert kwargs["headers"]["x-goog-api-key"] == "fake-secret"
        return httpx.Response(403, json={"error": {"message": "fake-secret"}})

    monkeypatch.setattr("copilot.gemini.httpx.post", respond)
    with pytest.raises(GeminiError) as error:
        Gemini(settings).generate("Rewrite", {}, Rewrite)
    assert "fake-secret" not in str(error.value)


def test_embedding_dimension_validation(monkeypatch):
    settings = Settings(gemini_api_key=SecretStr("fake"), _env_file=None)
    monkeypatch.setattr(Gemini, "post", lambda *a, **k: {"embeddings": [{"values": [1, 2]}]})
    with pytest.raises(GeminiError, match="dimensions"):
        Gemini(settings).embed(["test"], "RETRIEVAL_QUERY")


def test_rejected_ai_answer_blocks_proposals(client, app, admin, gemini_app, monkeypatch):
    from copilot import gemini

    monkeypatch.setattr(
        gemini,
        "verify_claims",
        lambda *args: ([], {"accepted": 0, "rejected": 1, "method": "test rejection", "limitations": "test"}),
    )
    result = analyze(client, admin)
    assert result["status"] == "verification_failed"
    assert result["proposal"] is None
    assert not result["drafts"]


def test_seed_cli_initializes_empty_database(tmp_path):
    env = {**os.environ, "COPILOT_DATABASE_URL": f"sqlite:///{tmp_path / 'fresh.db'}"}
    result = subprocess.run(
        [sys.executable, "-m", "copilot.cli", "seed"], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "fresh.db").exists()


def test_blocked_and_invalid_generation_are_errors(monkeypatch):
    settings = Settings(gemini_api_key=SecretStr("fake"), _env_file=None)
    monkeypatch.setattr(Gemini, "post", lambda *a, **k: {"candidates": [{"finishReason": "SAFETY"}]})
    with pytest.raises(GeminiError, match="blocked"):
        Gemini(settings).generate("Answer", {}, Answer)
