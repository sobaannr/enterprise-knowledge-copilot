import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from copilot.actions import decide, proposal_view, save_run, ticket_view
from copilot.auth import Principal, operator, principal
from copilot.config import Settings, get_settings
from copilot.db import Base, make_database
from copilot.gemini import GeminiError
from copilot.models import AuditEvent, Incident, Proposal, Run, Ticket, utcnow
from copilot.retrieval import search_documents, visible_documents
from copilot.memory import context, remember
from copilot.monitoring import operation
from copilot.security import guard_question
from copilot.models import ConversationTurn, OperationMetric
from copilot.seed import seed
from copilot.workflow import aware, build_workflow

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class AnalyzeRequest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=100)
    question: str = Field(min_length=5, max_length=4000)
    incident_id: str | None = Field(default=None, max_length=100)


class DecisionRequest(BaseModel):
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")
    decision: Literal["approve", "reject"]


def database(request: Request):
    with request.app.state.sessions() as session:
        yield session


def create_app(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.admin_token == settings.reader_token:
        raise ValueError("Operator and analyst tokens must differ")
    engine, sessions = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        if settings.seed_demo:
            with sessions() as session:
                seed(session, settings.tenant)
        yield
        engine.dispose()

    app = FastAPI(title="Enterprise Knowledge & Action Copilot", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.sessions = settings, sessions

    @app.exception_handler(GeminiError)
    async def gemini_error(request, error):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path in {"/docs", "/redoc"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self'; frame-ancestors 'none'"
            )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health(session=Depends(database)):
        session.execute(text("SELECT 1"))
        return {"status": "ok", "retrieval": settings.retrieval_backend}

    @app.get("/api/me")
    def me(user: Principal = Depends(principal)):
        return {
            "actor": user.actor,
            "role": user.role,
            "tenant": user.tenant,
            "retrieval": settings.retrieval_backend,
            "rerank": settings.rerank,
            "generation": settings.generation_backend,
            "gemini_configured": bool(settings.gemini_api_key.get_secret_value().strip()),
            "generation_model": settings.gemini_generation_model,
            "embedding_model": settings.gemini_embedding_model,
            "gemini_rerank": settings.gemini_rerank,
        }

    @app.get("/api/incidents")
    def incidents(user: Principal = Depends(principal), session=Depends(database)):
        rows = session.scalars(
            select(Incident).where(Incident.tenant == user.tenant).order_by(Incident.started_at.desc())
        )
        return [
            {
                "id": i.id,
                "title": i.title,
                "started_at": aware(i.started_at).isoformat(),
                "ended_at": aware(i.ended_at).isoformat(),
            }
            for i in rows
        ]

    @app.get("/api/search")
    def search(
        q: str = "",
        kinds: list[str] | None = Query(None),
        document_ids: list[str] | None = Query(None),
        min_revision: int | None = Query(None, ge=1),
        user: Principal = Depends(principal),
        session=Depends(database),
    ):
        if not 2 <= len(q) <= 2000:
            raise HTTPException(422, "Query must be between 2 and 2000 characters")
        guard_question(q)
        return search_documents(
            session,
            settings,
            user.tenant,
            q,
            user=user,
            filters={"kinds": kinds, "document_ids": document_ids, "min_revision": min_revision},
        )

    @app.post("/api/answers")
    def answer(body: AnalyzeRequest, user: Principal = Depends(principal), session=Depends(database)):
        from copilot.generation import answer_question

        try:
            guard_question(body.question)
            with operation(sessions, user, "answer") as metrics:
                cid, incident_id = context(
                    session, user, body.question, body.conversation_id, body.incident_id
                )
                question = body.question + (f" Context incident: {incident_id}" if incident_id else "")
                result = answer_question(session, settings, user, question)
                remember(session, cid, body.question, incident_id)
                metrics["verification"] = result.get("verification", {})
                return {**result, "conversation_id": cid}
        except HTTPException:
            session.rollback()
            raise
        except GeminiError:
            session.rollback()
            raise
        except Exception:
            logger.exception("Knowledge answer failed")
            raise HTTPException(
                503, "Knowledge answer unavailable. Check retrieval and local model configuration."
            ) from None

    @app.get("/api/sources/{source_id}")
    def source(source_id: str, user: Principal = Depends(principal), session=Depends(database)):
        docs = visible_documents(session, user.tenant, user, document_ids=[source_id])
        doc = docs[0] if docs else None
        if not doc:
            raise HTTPException(404, "Source not found")
        return {
            "id": doc.id,
            "title": doc.title,
            "kind": doc.kind,
            "revision": doc.revision,
            "body": doc.body,
        }

    @app.post("/api/runs")
    def analyze(body: AnalyzeRequest, user: Principal = Depends(principal), session=Depends(database)):
        guard_question(body.question)
        with operation(sessions, user, "incident") as metrics:
            try:
                cid, incident_id = context(
                    session, user, body.question, body.conversation_id, body.incident_id
                )
                state = build_workflow(session, settings, user).invoke(
                    {"question": body.question, "incident_id": incident_id, "now": utcnow()}
                )
                result = save_run(session, settings, user, body.question, state)
                remember(session, cid, body.question, result.get("incident", {}).get("id"), result["id"])
                metrics["verification"] = result.get("verification", {})
                return {**result, "conversation_id": cid}
            except Exception:
                session.rollback()
                raise

    @app.post("/api/runs/stream")
    def stream(body: AnalyzeRequest, user: Principal = Depends(principal)):
        def events():
            def event(kind, value):
                return f"event: {kind}\ndata: {json.dumps(value, default=str)}\n\n"

            yield event("progress", {"stage": "started", "message": "Resolving incident and access scope"})
            with operation(sessions, user, "incident_stream") as metrics, sessions() as session:
                try:
                    guard_question(body.question)
                    cid, incident_id = context(
                        session, user, body.question, body.conversation_id, body.incident_id
                    )
                    graph = build_workflow(session, settings, user)
                    state = {"question": body.question, "incident_id": incident_id, "now": utcnow()}
                    for update in graph.stream(state, stream_mode="updates"):
                        for stage, values in update.items():
                            if values:
                                state.update(values)
                            yield event("progress", {"stage": stage, "message": f"Completed {stage}"})
                    result = save_run(session, settings, user, body.question, state)
                    remember(session, cid, body.question, result.get("incident", {}).get("id"), result["id"])
                    metrics["verification"] = result.get("verification", {})
                    yield event("result", {**result, "conversation_id": cid})
                except GeminiError as exc:
                    metrics["status"] = "error"
                    session.rollback()
                    yield event("error", {"message": str(exc)})
                except Exception:
                    metrics["status"] = "error"
                    session.rollback()
                    logger.exception("Analysis failed")
                    yield event(
                        "error",
                        {"message": "Analysis failed. Check service logs and retrieval configuration."},
                    )

        # Starlette resumes sync iterators in fresh worker contexts; preserve our trace context.
        from contextvars import copy_context

        stream_context = copy_context()
        iterator = events()

        def contextual_events():
            try:
                while True:
                    try:
                        value = stream_context.run(next, iterator)
                    except StopIteration:
                        return
                    yield value
            finally:
                stream_context.run(iterator.close)

        return StreamingResponse(
            contextual_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}")
    def run(run_id: str, user: Principal = Depends(principal), session=Depends(database)):
        saved = session.scalar(
            select(Run).where(Run.id == run_id, Run.tenant == user.tenant, Run.actor == user.actor)
        )
        if not saved:
            raise HTTPException(404, "Run not found")
        allowed = {d.id for d in visible_documents(session, user.tenant, user)}
        if any(s["id"] not in allowed for s in saved.result.get("sources", []) if s.get("kind") != "record"):
            raise HTTPException(403, "Evidence access changed; run a new analysis")
        proposal = session.scalar(
            select(Proposal).where(Proposal.run_id == run_id, Proposal.tenant == user.tenant)
        )
        return {"id": saved.id, **saved.result, "proposal": proposal_view(proposal) if proposal else None}

    @app.post("/api/proposals/{proposal_id}/decision")
    def decision(
        proposal_id: str,
        body: DecisionRequest,
        user: Principal = Depends(operator),
        session=Depends(database),
    ):
        return decide(session, user, proposal_id, body.digest, body.decision)

    @app.get("/api/tickets")
    def tickets(user: Principal = Depends(principal), session=Depends(database)):
        rows = session.scalars(
            select(Ticket).where(Ticket.tenant == user.tenant).order_by(Ticket.created_at.desc())
        )
        allowed = {d.id for d in visible_documents(session, user.tenant, user)}
        visible = []
        for ticket in rows:
            proposal = session.get(Proposal, ticket.proposal_id)
            draft = next(
                (d for d in proposal.payload["tickets"] if d["customer_id"] == ticket.customer_id), None
            )
            if draft and all(ref.startswith("record:") or ref in allowed for ref in draft["source_ids"]):
                visible.append(ticket_view(ticket))
        return visible

    @app.get("/api/audit")
    def audits(user: Principal = Depends(operator), session=Depends(database)):
        rows = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant == user.tenant)
            .order_by(AuditEvent.created_at.desc())
            .limit(200)
        )
        return [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "target_id": row.target_id,
                "details": row.details,
                "created_at": aware(row.created_at).isoformat(),
            }
            for row in rows
        ]

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str, user: Principal = Depends(principal), session=Depends(database)):
        context(session, user, "history", conversation_id)
        rows = session.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.created_at)
            .limit(100)
        )
        return {
            "id": conversation_id,
            "turns": [
                {
                    "question": t.question,
                    "incident_id": t.incident_id,
                    "run_id": t.run_id,
                    "created_at": t.created_at.isoformat(),
                }
                for t in rows
            ],
        }

    @app.get("/api/metrics")
    def metrics(user: Principal = Depends(operator), session=Depends(database)):
        rows = list(
            session.scalars(
                select(OperationMetric)
                .where(OperationMetric.tenant == user.tenant)
                .order_by(OperationMetric.created_at.desc())
                .limit(200)
            )
        )
        durations = sorted(r.data["latency_ms"] for r in rows)

        def percentile(p):
            import math

            return durations[max(0, math.ceil(len(durations) * p) - 1)] if durations else None

        return {
            "count": len(rows),
            "p50_ms": percentile(0.5),
            "p95_ms": percentile(0.95),
            "error_rate": sum(r.data["status"] == "error" for r in rows) / len(rows) if rows else None,
            "recent": [
                {"id": r.id, "operation": r.operation, "created_at": r.created_at.isoformat(), **r.data}
                for r in rows
            ],
        }

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
