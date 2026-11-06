"""Idempotent fictional dataset. Seed dates align to the previous UTC calendar week."""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from copilot.models import Customer, Document, Impact, Incident, Order, Subscription


def seed(session, tenant="acme", today=None):
    if session.scalar(select(Incident.id).where(Incident.tenant == tenant)):
        return
    today = today or datetime.now(timezone.utc).date()
    day = today - timedelta(days=today.weekday() + 5)  # Previous Wednesday.
    start = datetime.combine(day, time(9, 10), tzinfo=timezone.utc)
    prefix = f"{tenant}:"
    documents = [
        (
            "INC-1042",
            "Login incident · final report",
            "incident",
            f"Incident INC-1042 occurred on {day} from 09:10 to 10:05 UTC. A certificate cache regression "
            "caused SAML login failures for some EU enterprise tenants. Confirmed affected customers: "
            "Northstar Analytics and Atlas Logistics. Meridian Health is suspected, pending telemetry validation. "
            "Cedar Labs had failures but has a Business subscription. All service was restored at 10:05 UTC. "
            "Do not infer that every enterprise customer was affected.",
        ),
        (
            "KB-208",
            "Approved SAML recovery procedure",
            "product",
            "For INC-1042, ask an organization administrator to refresh the SAML metadata from Settings > "
            "Identity > Refresh metadata, then retry sign-in in a new browser session. If recovery fails, "
            "escalate to Identity Support. Never disable MFA or SSO enforcement. This procedure was approved "
            "by the Identity Engineering lead after incident validation.",
        ),
        (
            "POL-12",
            "Incident customer follow-up policy",
            "policy",
            "Create one follow-up per confirmed affected active enterprise customer per incident. Assign it "
            "to the named account manager. Include the incident, observed impact, approved workaround, and "
            "sources. Suspected impact requires investigation before outreach. A human operator must approve "
            "the exact proposal before ticket creation. Missing account managers block that customer's ticket. "
            "Never promise compensation or disable security controls.",
        ),
        (
            "SUP-441",
            "Northstar login support ticket",
            "support",
            "Northstar Analytics reported SAML sign-in failures during INC-1042. Telemetry confirms 184 "
            "failed logins. Support suggested disabling MFA before the final procedure was approved. "
            "That suggestion is superseded by KB-208 and must not be used.",
        ),
        (
            "SUP-442",
            "Atlas login support ticket",
            "support",
            "Atlas Logistics reported SAML sign-in failures during INC-1042. Telemetry confirms 73 failed "
            "logins. The organization administrator recovered access using the metadata refresh procedure.",
        ),
        (
            "SUP-443",
            "Meridian unverified login report",
            "support",
            "Meridian Health reported intermittent login delays around INC-1042. No correlated failure "
            "telemetry is available. Impact remains suspected; confirm before outreach.",
        ),
        (
            "SUP-444",
            "Cedar Labs login report",
            "support",
            "Cedar Labs telemetry confirms 12 failed logins during INC-1042. Subscription tier is Business.",
        ),
        (
            "KB-301",
            "API rate limits",
            "product",
            "Enterprise API requests have a default quota of 1,000 requests per minute. Retry HTTP 429 "
            "responses using exponential backoff. This document does not describe login incidents.",
        ),
    ]
    for id_, title, kind, body in documents:
        session.add(Document(id=prefix + id_, tenant=tenant, title=title, kind=kind, body=body))
    session.flush()
    incident_id = prefix + "INC-1042"
    session.add(
        Incident(
            id=incident_id,
            tenant=tenant,
            title="EU SAML login disruption",
            started_at=start,
            ended_at=start + timedelta(minutes=55),
            report_id=prefix + "INC-1042",
            workaround_id=prefix + "KB-208",
            policy_id=prefix + "POL-12",
            workaround_approved=True,
        )
    )
    customers = [
        ("northstar", "Northstar Analytics", "Maya Chen", "enterprise", "confirmed", 184, "SUP-441"),
        ("atlas", "Atlas Logistics", "Jon Bell", "enterprise", "confirmed", 73, "SUP-442"),
        ("meridian", "Meridian Health", None, "enterprise", "suspected", 0, "SUP-443"),
        ("cedar", "Cedar Labs", "Sam Rivera", "business", "confirmed", 12, "SUP-444"),
        ("orbit", "Orbit Financial", "Maya Chen", "enterprise", None, 0, None),
    ]
    for key, name, manager, tier, certainty, failures, evidence in customers:
        customer_id = prefix + key
        session.add(Customer(id=customer_id, tenant=tenant, name=name, account_manager=manager))
        session.flush()
        session.add(
            Subscription(id=prefix + "sub-" + key, customer_id=customer_id, tier=tier, status="active")
        )
        session.add(
            Order(
                id=prefix + "order-" + key,
                customer_id=customer_id,
                description=f"Annual {tier} subscription",
                status="fulfilled",
            )
        )
        if certainty:
            session.add(
                Impact(
                    id=prefix + "impact-" + key,
                    incident_id=incident_id,
                    customer_id=customer_id,
                    evidence_id=prefix + evidence,
                    certainty=certainty,
                    failed_logins=failures,
                )
            )
    session.commit()
