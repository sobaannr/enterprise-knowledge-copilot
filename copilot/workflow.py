"""A bounded LangGraph workflow. Retrieved text is evidence, never executable instructions."""

import hashlib
import json
import re
from time import perf_counter
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from copilot.models import Customer, Impact, Incident, Order, Subscription
from copilot.retrieval import search_documents, visible_documents
from copilot.query import decompose_question
from copilot.security import guard_question


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def incident_snapshot(session, tenant, incident_id, user=None):
    incident = session.scalar(select(Incident).where(Incident.id == incident_id, Incident.tenant == tenant))
    if not incident:
        raise ValueError("Incident not found")
    impacts = list(
        session.scalars(select(Impact).where(Impact.incident_id == incident_id).order_by(Impact.id))
    )
    doc_ids = {incident.report_id, incident.workaround_id, incident.policy_id} | {
        x.evidence_id for x in impacts
    }
    docs = sorted(visible_documents(session, tenant, user, document_ids=list(doc_ids)), key=lambda d: d.id)
    doc_map = {d.id: d for d in docs}
    customers = []
    for impact in impacts:
        customer = session.scalar(
            select(Customer).where(Customer.id == impact.customer_id, Customer.tenant == tenant)
        )
        if not customer:
            continue
        subscription = session.scalar(select(Subscription).where(Subscription.customer_id == customer.id))
        orders = list(
            session.scalars(select(Order).where(Order.customer_id == customer.id).order_by(Order.id))
        )
        customers.append(
            {
                "id": customer.id,
                "name": customer.name,
                "account_manager": customer.account_manager,
                "tier": subscription.tier if subscription else None,
                "status": subscription.status if subscription else None,
                "subscription_id": subscription.id if subscription else None,
                "certainty": impact.certainty,
                "failed_logins": impact.failed_logins,
                "evidence_id": impact.evidence_id if impact.evidence_id in doc_map else None,
                "impact_id": impact.id,
                "orders": [{"id": o.id, "description": o.description, "status": o.status} for o in orders],
            }
        )
    return {
        "incident": {
            "id": incident.id,
            "title": incident.title,
            "started_at": aware(incident.started_at).isoformat(),
            "ended_at": aware(incident.ended_at).isoformat(),
            "report_id": incident.report_id,
            "workaround_id": incident.workaround_id,
            "policy_id": incident.policy_id,
            "workaround_approved": incident.workaround_approved,
        },
        "documents": [
            {"id": d.id, "title": d.title, "body": d.body, "revision": d.revision, "kind": d.kind}
            for d in docs
        ],
        "customers": customers,
    }


class State(TypedDict, total=False):
    subqueries: list[str]
    question: str
    incident_id: str | None
    now: datetime
    snapshot: dict
    evidence: list
    result: dict
    error: str


def build_workflow(session, settings, user):
    def resolve(state):
        guard_question(state["question"])
        query = select(Incident).where(Incident.tenant == user.tenant)
        incident_id = state.get("incident_id")
        match = re.search(r"\bINC-\d+\b", state["question"], re.I)
        if not incident_id and match:
            incident_id = f"{user.tenant}:{match[0].upper()}"
        if incident_id:
            query = query.where(Incident.id == incident_id)
        elif "last week" in state["question"].lower() and re.search(
            r"\b(login|saml|sso|sign.in)\b", state["question"], re.I
        ):
            today = state["now"].astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            monday = today - timedelta(days=today.weekday())
            query = query.where(
                Incident.started_at >= monday - timedelta(days=7),
                Incident.started_at < monday,
                Incident.title.ilike("%login%"),
            )
        else:
            return {
                "error": "Choose an incident or ask about last week's login incident. "
                "This workflow supports incident follow-up, not arbitrary business questions."
            }
        incidents = list(session.scalars(query))
        if len(incidents) != 1:
            return {"error": "No unique incident matches. Select a specific incident from the incident list."}
        return {"snapshot": incident_snapshot(session, user.tenant, incidents[0].id, user)}

    def decompose(state):
        return {"subqueries": decompose_question(state["question"], state["snapshot"]["incident"]["id"])}

    def retrieve(state):
        return {
            "evidence": search_documents(
                session, settings, user.tenant, state["question"], user=user, subqueries=state["subqueries"]
            )
        }

    def synthesize(state):
        snapshot = state["snapshot"]
        incident = snapshot["incident"]
        docs = {d["id"]: d for d in snapshot["documents"]}
        sources = [
            {
                "id": d["id"],
                "title": d["title"],
                "kind": d["kind"],
                "revision": d["revision"],
                "excerpt": d["body"],
            }
            for d in docs.values()
        ]
        findings, gaps, conflicts, drafts = [], [], [], []
        for key in ["report_id", "workaround_id", "policy_id"]:
            if incident[key] not in docs:
                gaps.append(
                    {
                        "code": "missing_document",
                        "message": f"Required source {incident[key]} is unavailable.",
                    }
                )
        if not incident["workaround_approved"]:
            gaps.append({"code": "unapproved_workaround", "message": "No approved workaround is available."})
        can_draft = not gaps
        workaround = docs.get(incident["workaround_id"])
        policy = docs.get(incident["policy_id"])
        for d in docs.values():
            if d["kind"] == "support" and "disabling mfa" in d["body"].lower() and policy and workaround:
                conflicts.append(
                    {
                        "code": "superseded_security_advice",
                        "message": "An older support suggestion to disable MFA conflicts with the "
                        "approved procedure. Use the approved procedure only.",
                        "source_ids": [d["id"], incident["workaround_id"], policy["id"]],
                    }
                )
        affected, suspected, excluded = [], [], []
        for c in snapshot["customers"]:
            record_id = "record:" + c["id"]
            sources.append(
                {
                    "id": record_id,
                    "title": f"Customer, subscription and impact · {c['name']}",
                    "kind": "record",
                    "revision": None,
                    "excerpt": json.dumps(c, sort_keys=True),
                }
            )
            if c["tier"] is None or c["status"] is None:
                gaps.append(
                    {"code": "missing_subscription", "message": f"{c['name']}: subscription data missing."}
                )
                excluded.append({**c, "reason": "Subscription could not be verified"})
                continue
            if c["tier"] != "enterprise" or c["status"] != "active":
                excluded.append({**c, "reason": "Not an active enterprise subscription"})
                continue
            if c["certainty"] != "confirmed":
                suspected.append(c)
                gaps.append(
                    {"code": "unverified_impact", "message": f"{c['name']}: impact remains unverified."}
                )
                continue
            affected.append(c)
            source_ids = [record_id]
            if c["evidence_id"]:
                source_ids.append(c["evidence_id"])
            findings.append(
                {
                    "text": f"{c['name']} is a confirmed affected active enterprise customer, "
                    f"with {c['failed_logins']} failed logins.",
                    "source_ids": source_ids,
                    "basis": "structured_record",
                }
            )
            if not c["account_manager"]:
                gaps.append(
                    {"code": "missing_account_manager", "message": f"{c['name']}: account manager missing."}
                )
            if not c["evidence_id"]:
                gaps.append(
                    {"code": "missing_impact_evidence", "message": f"{c['name']}: impact source unavailable."}
                )
            if can_draft and c["account_manager"] and c["evidence_id"]:
                refs = source_ids + [incident["report_id"], incident["workaround_id"], incident["policy_id"]]
                drafts.append(
                    {
                        "customer_id": c["id"],
                        "customer_name": c["name"],
                        "assigned_to": c["account_manager"],
                        "title": f"Follow up: {incident['id'].split(':')[-1]} / {c['name']}",
                        "body": f"Confirm recovery with {c['name']} following {incident['title']}. "
                        f"Observed impact: {c['failed_logins']} failed logins.\n\n"
                        f"Approved procedure:\n{workaround['body']}\n\n"
                        f"Sources: {', '.join(refs)}",
                        "source_ids": refs,
                    }
                )
        if workaround and incident["workaround_approved"]:
            findings.append(
                {"text": workaround["body"], "source_ids": [workaround["id"]], "basis": "verbatim"}
            )
        return {
            "result": {
                "status": "ready" if drafts else "needs_information",
                "incident": incident,
                "summary": f"{len(affected)} confirmed affected enterprise customers; "
                f"{len(suspected)} require investigation. {len(drafts)} follow-up drafts prepared.",
                "findings": findings,
                "affected_customers": affected,
                "suspected_customers": suspected,
                "excluded_customers": excluded,
                "gaps": gaps,
                "conflicts": conflicts,
                "sources": sources,
                "retrieval_hits": state["evidence"],
                "subqueries": state["subqueries"],
                "drafts": drafts,
                "retrieval_mode": settings.retrieval_backend,
                "answer_mode": "deterministic_evidence_templates",
                "time_basis": "Previous calendar week, Monday–Sunday, UTC; subscription status is current.",
            }
        }

    def generate(state):
        if settings.generation_backend != "gemini":
            return {}
        from copilot.gemini import generate_claims

        result = state["result"]
        candidate = generate_claims(settings, state["question"], result["sources"])
        result["candidate_claims"] = [c.model_dump() for c in candidate.claims]
        result["answer_mode"] = "gemini"
        return {"result": result}

    def verify(state):
        result = state["result"]
        sources = {s["id"]: s for s in result["sources"]}
        errors = []
        for item in result["findings"] + result["drafts"]:
            if not item["source_ids"] or any(ref not in sources for ref in item["source_ids"]):
                errors.append("Unresolved source reference")
            if item.get("basis") == "verbatim" and item["text"] != sources[item["source_ids"][0]]["excerpt"]:
                errors.append("Verbatim evidence mismatch")
        result["verification"] = {
            "passed": not errors,
            "errors": errors,
            "method": "Source resolution and exact template provenance; no LLM judge.",
            "limitations": "Does not independently establish whether source records are true. "
            "Conflict detection covers the seeded MFA rule only.",
        }
        if settings.generation_backend == "gemini":
            from copilot.gemini import Claim, verify_claims

            claims = [Claim.model_validate(c) for c in result.pop("candidate_claims", [])]
            accepted, metrics = verify_claims(settings, claims, result["sources"])
            result["ai_findings"] = accepted
            if not claims or metrics["rejected"]:
                errors.append(
                    "Gemini answer contained unsupported claims or no supported answer; retry analysis."
                )
            result["verification"] = {**metrics, "passed": not errors, "errors": errors}
        if errors:
            result["drafts"] = []
            result["status"] = "verification_failed"
            result["summary"] = "Verification needs attention. No actionable proposal was saved."
        return {"result": result}

    def plan_actions(state):
        result = state["result"]
        if settings.generation_backend == "gemini" and result["drafts"]:
            from copilot.gemini import plan_followups

            result["action_plan"] = plan_followups(
                settings, state["question"], result["incident"]["id"], result["drafts"]
            )
        return {"result": result}

    def clarify(state):
        return {
            "result": {
                "status": "needs_information",
                "summary": state["error"],
                "drafts": [],
                "findings": [],
                "sources": [],
                "gaps": [],
                "conflicts": [],
            }
        }

    graph = StateGraph(State)
    for name, node in [
        ("resolve", resolve),
        ("decompose", decompose),
        ("retrieve", retrieve),
        ("synthesize", synthesize),
        ("generate", generate),
        ("verify", verify),
        ("plan_actions", plan_actions),
        ("clarify", clarify),
    ]:

        def timed(state, _node=node, _name=name):
            from copilot.monitoring import active

            started = perf_counter()
            try:
                return _node(state)
            finally:
                trace = active.get()
                if trace is not None:
                    trace.setdefault("stage_latency_ms", {})[_name] = round(
                        (perf_counter() - started) * 1000, 2
                    )

        graph.add_node(name, timed)
    graph.add_edge(START, "resolve")
    graph.add_conditional_edges("resolve", lambda state: "clarify" if state.get("error") else "decompose")
    graph.add_edge("decompose", "retrieve")
    graph.add_edge("retrieve", "synthesize")
    graph.add_edge("synthesize", "generate")
    graph.add_edge("generate", "verify")
    graph.add_edge("verify", "plan_actions")
    graph.add_edge("plan_actions", END)
    graph.add_edge("clarify", END)
    return graph.compile()
