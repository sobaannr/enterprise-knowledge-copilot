from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from copilot.actions import decide
from copilot.auth import Principal
from copilot.models import AuditEvent, Document, Proposal, Ticket, utcnow
from tests.conftest import analyze


def approve(client, admin, proposal, **changes):
    return client.post(
        f"/api/proposals/{proposal['id']}/decision",
        headers=admin,
        json={"digest": proposal["digest"], "decision": "approve", **changes},
    )


def test_auth_and_roles(client, admin, analyst):
    assert client.get("/api/tickets").status_code == 401
    proposal = analyze(client, analyst)["proposal"]
    assert approve(client, analyst, proposal).status_code == 403
    assert client.get("/api/audit", headers=analyst).status_code == 403
    assert approve(client, admin, proposal).status_code == 200


def test_exact_digest_and_idempotency_across_runs(client, admin):
    proposal = analyze(client, admin)["proposal"]
    assert approve(client, admin, proposal, digest="0" * 64).status_code == 409
    first = approve(client, admin, proposal)
    assert first.status_code == 200, first.text
    assert len(first.json()["tickets"]) == 2
    assert approve(client, admin, proposal).json() == first.json()
    second_proposal = analyze(client, admin)["proposal"]
    second = approve(client, admin, second_proposal)
    assert second.status_code == 200, second.text
    assert {t["id"] for t in first.json()["tickets"]} == {t["id"] for t in second.json()["tickets"]}
    assert len(client.get("/api/tickets", headers=admin).json()) == 2
    events = client.get("/api/audit", headers=admin).json()
    executions = [e for e in events if e["action"] == "proposal.executed"]
    assert len(executions) == 2
    assert len(executions[0]["details"]["reused_ticket_ids"]) == 2


def test_stale_evidence_and_expiration(client, app, admin):
    proposal = analyze(client, admin)["proposal"]
    with app.state.sessions() as session:
        session.get(Document, "acme:KB-208").revision += 1
        session.commit()
    assert approve(client, admin, proposal).status_code == 409
    fresh = analyze(client, admin)["proposal"]
    with app.state.sessions() as session:
        session.get(Proposal, fresh["id"]).expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert approve(client, admin, fresh).status_code == 409
    assert not client.get("/api/tickets", headers=admin).json()


def test_rejection_cannot_execute(client, admin):
    proposal = analyze(client, admin)["proposal"]
    assert approve(client, admin, proposal, decision="reject").status_code == 200
    assert approve(client, admin, proposal).status_code == 409
    assert not client.get("/api/tickets", headers=admin).json()


def test_payload_tampering_fails_closed(client, app, admin):
    proposal = analyze(client, admin)["proposal"]
    with app.state.sessions() as session:
        saved = session.get(Proposal, proposal["id"])
        saved.payload = {**saved.payload, "tickets": []}
        session.commit()
    assert approve(client, admin, proposal).status_code == 409


def test_parallel_approval_never_duplicates(client, app, admin):
    proposal = analyze(client, admin)["proposal"]

    def execute(_):
        with app.state.sessions() as session:
            try:
                return decide(
                    session,
                    Principal("operator", "acme", "operator"),
                    proposal["id"],
                    proposal["digest"],
                    "approve",
                )
            except HTTPException as exc:
                assert exc.status_code == 409
                return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(execute, range(4)))
    assert any(results)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 2
        assert (
            session.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "proposal.executed")
            )
            == 1
        )


def test_cross_tenant_cannot_decide(client, app, admin):
    proposal = analyze(client, admin)["proposal"]
    with app.state.sessions() as session:
        try:
            decide(
                session,
                Principal("other", "other", "operator"),
                proposal["id"],
                proposal["digest"],
                "approve",
            )
            assert False, "Cross-tenant decision succeeded"
        except HTTPException as exc:
            assert exc.status_code == 404
