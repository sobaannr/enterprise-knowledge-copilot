from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from copilot.models import AuditEvent, Proposal, Run, Ticket, utcnow
from copilot.workflow import aware, digest, incident_snapshot


def audit(session, user, action, target, details=None):
    session.add(
        AuditEvent(
            tenant=user.tenant, actor=user.actor, action=action, target_id=target, details=details or {}
        )
    )


def proposal_view(proposal):
    return {
        "id": proposal.id,
        "status": proposal.status,
        "digest": proposal.digest,
        "payload": proposal.payload,
        "expires_at": aware(proposal.expires_at).isoformat(),
        "approved_by": proposal.approved_by,
    }


def save_run(session, settings, user, question, state):
    result = state["result"]
    run = Run(tenant=user.tenant, actor=user.actor, question=question, result=result)
    session.add(run)
    session.flush()
    proposal = None
    if result["drafts"]:
        payload = {"incident_id": result["incident"]["id"], "tickets": result["drafts"]}
        proposal = Proposal(
            run_id=run.id,
            tenant=user.tenant,
            incident_id=payload["incident_id"],
            payload=payload,
            digest=digest(payload),
            evidence_digest=digest(state["snapshot"]),
            expires_at=utcnow() + timedelta(minutes=settings.proposal_ttl_minutes),
        )
        session.add(proposal)
        session.flush()
        audit(session, user, "proposal.prepared", proposal.id, {"digest": proposal.digest})
    audit(session, user, "run.completed", run.id, {"status": result["status"]})
    session.commit()
    return {"id": run.id, **result, "proposal": proposal_view(proposal) if proposal else None}


def get_proposal(session, user, id_):
    proposal = session.scalar(select(Proposal).where(Proposal.id == id_, Proposal.tenant == user.tenant))
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    return proposal


def ticket_view(ticket):
    return {
        "id": ticket.id,
        "incident_id": ticket.incident_id,
        "customer_id": ticket.customer_id,
        "title": ticket.title,
        "body": ticket.body,
        "assigned_to": ticket.assigned_to,
        "proposal_id": ticket.proposal_id,
        "created_at": aware(ticket.created_at).isoformat(),
    }


def receipt(session, user, proposal):
    from copilot.retrieval import visible_documents

    allowed = {d.id for d in visible_documents(session, user.tenant, user)}
    if any(
        ref not in allowed
        for row in proposal.payload["tickets"]
        for ref in row["source_ids"]
        if not ref.startswith("record:")
    ):
        raise HTTPException(403, "Ticket evidence access changed")
    ids = [row["customer_id"] for row in proposal.payload["tickets"]]
    tickets = session.scalars(
        select(Ticket)
        .where(
            Ticket.tenant == user.tenant,
            Ticket.incident_id == proposal.incident_id,
            Ticket.customer_id.in_(ids),
        )
        .order_by(Ticket.customer_id)
    )
    return {"proposal": proposal_view(proposal), "tickets": [ticket_view(t) for t in tickets]}


def decide(session, user, id_, expected_digest, decision):
    if user.role != "operator":
        raise HTTPException(403, "Operator role required")
    proposal = get_proposal(session, user, id_)
    if expected_digest != proposal.digest or digest(proposal.payload) != proposal.digest:
        raise HTTPException(409, "Proposal changed; review it again")
    if proposal.status == "executed" and decision == "approve":
        return receipt(session, user, proposal)
    if proposal.status != "pending":
        raise HTTPException(409, f"Proposal is {proposal.status}")
    if aware(proposal.expires_at) <= utcnow():
        raise HTTPException(409, "Proposal expired; prepare a new analysis")
    if decision == "approve":
        current = incident_snapshot(session, user.tenant, proposal.incident_id, user)
        if digest(current) != proposal.evidence_digest:
            raise HTTPException(409, "Evidence changed; prepare and review a new analysis")
    # Compare-and-swap serializes contenders on both SQLite and PostgreSQL.
    new_status = "executed" if decision == "approve" else "rejected"
    changed = session.execute(
        update(Proposal)
        .where(Proposal.id == id_, Proposal.status == "pending")
        .values(status=new_status, approved_by=user.actor),
        execution_options={"synchronize_session": False},
    )
    if changed.rowcount != 1:
        session.rollback()
        proposal = get_proposal(session, user, id_)
        if proposal.status == "executed" and decision == "approve":
            return receipt(session, user, proposal)
        raise HTTPException(409, "Another decision was recorded; refresh the proposal")
    created, reused = [], []
    try:
        if decision == "approve":
            for row in proposal.payload["tickets"]:
                existing = session.scalar(
                    select(Ticket).where(
                        Ticket.tenant == user.tenant,
                        Ticket.incident_id == proposal.incident_id,
                        Ticket.customer_id == row["customer_id"],
                    )
                )
                if existing:
                    reused.append(existing.id)
                    continue
                ticket = Ticket(
                    tenant=user.tenant,
                    incident_id=proposal.incident_id,
                    customer_id=row["customer_id"],
                    proposal_id=proposal.id,
                    title=row["title"],
                    body=row["body"],
                    assigned_to=row["assigned_to"],
                )
                session.add(ticket)
                session.flush()
                created.append(ticket.id)
            audit(session, user, "proposal.approved", proposal.id, {"digest": proposal.digest})
        audit(
            session,
            user,
            "proposal." + new_status,
            proposal.id,
            {"digest": proposal.digest, "created_ticket_ids": created, "reused_ticket_ids": reused},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "A concurrent follow-up was created. Retry the same approval safely."
        ) from None
    session.refresh(proposal)
    return receipt(session, user, proposal)
