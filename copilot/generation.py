"""Gemini answer generation, with an explicit offline extractive test mode."""

import re

from pydantic import BaseModel, ConfigDict, Field

from copilot.retrieval import search_documents


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(max_length=200)
    text: str = Field(min_length=20, max_length=8000)


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quotes: list[Quote] = Field(max_length=5)


def normalize(value):
    return re.sub(r"\s+", " ", value).strip()


def verify_quotes(answer, hits):
    sources = {hit["chunk_id"]: hit for hit in hits}
    accepted, rejected = [], []
    seen = set()
    for quote in answer.quotes:
        source = sources.get(quote.source_id)
        if not source or normalize(quote.text) not in normalize(source["excerpt"]):
            rejected.append(
                {"source_id": quote.source_id, "reason": "Quote is not supported by retrieved text"}
            )
        elif (quote.source_id, normalize(quote.text)) not in seen:
            seen.add((quote.source_id, normalize(quote.text)))
            accepted.append({"text": quote.text, "source_id": quote.source_id, "title": source["title"]})
    return accepted, rejected


def answer_question(session, settings, user, question):
    from copilot.security import guard_question
    guard_question(question)
    hits = search_documents(session, settings, user.tenant, question, 8, user=user)
    if settings.generation_backend == "gemini":
        from copilot.gemini import generate_claims, verify_claims

        sources = [{"id": h["chunk_id"], "title": h["title"], "excerpt": h["excerpt"]} for h in hits]
        candidate = generate_claims(settings, question, sources) if sources else None
        claims, verification = verify_claims(settings, candidate.claims if candidate else [], sources)
        return {
            "mode": "gemini",
            "claims": claims,
            "quotes": [],
            "sources": hits,
            "status": "evidence_found" if claims else "insufficient_evidence",
            "verification": {**verification, "limitation": verification["limitations"]},
        }
    candidate = ModelAnswer(
        quotes=[Quote(source_id=h["chunk_id"], text=h["excerpt"]) for h in hits[:3] if len(h["excerpt"]) >= 20]
    )
    quotes, rejected = verify_quotes(candidate, hits)
    return {
        "mode": settings.generation_backend,
        "quotes": quotes,
        "sources": hits,
        "status": "evidence_found" if quotes else "insufficient_evidence",
        "verification": {
            "accepted": len(quotes),
            "rejected": len(rejected),
            "unsupported_quote_rate": len(rejected) / len(candidate.quotes) if candidate.quotes else 0,
            "rejections": rejected,
            "limitation": "Exact quote support does not establish relevance, completeness, "
            "source truth or policy authority. This view cannot authorize actions.",
        },
    }
