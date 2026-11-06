from datetime import timedelta

import pytest
from sqlalchemy import select

from copilot.auth import Principal
from copilot.evaluation import evaluate
from copilot.models import Customer, Document, Incident, Subscription, utcnow
from copilot.seed import seed
from copilot.workflow import build_workflow
from tests.conftest import analyze


def test_evidence_and_approval_boundary(client, admin):
    result = analyze(client, admin)
    assert {c["name"] for c in result["affected_customers"]} == {"Northstar Analytics", "Atlas Logistics"}
    assert len(result["drafts"]) == 2
    assert result["verification"]["passed"]
    assert result["conflicts"][0]["code"] == "superseded_security_advice"
    assert "Meridian Health" in result["gaps"][0]["message"]
    assert result["excluded_customers"][0]["name"] == "Cedar Labs"
    source_ids = {source["id"] for source in result["sources"]}
    assert all(set(f["source_ids"]) <= source_ids for f in result["findings"])
    assert client.get("/api/tickets", headers=admin).json() == []


def test_stream_defers_result_until_verification(client, admin):
    response = client.post("/api/runs/stream", headers=admin, json={"question": "Analyze INC-1042"})
    assert response.status_code == 200
    assert response.text.index('"stage": "verify"') < response.text.index("event: result")
    assert "event: error" not in response.text


def test_unsupported_and_missing_incident_do_not_act(client, admin):
    for question in ["What is for lunch today?", "Analyze INC-9999"]:
        result = client.post("/api/runs", headers=admin, json={"question": question}).json()
        assert result["status"] == "needs_information"
        assert result["proposal"] is None


def test_missing_manager_excludes_only_that_draft(client, app, admin):
    with app.state.sessions() as session:
        session.get(Customer, "acme:atlas").account_manager = None
        session.commit()
    result = analyze(client, admin)
    assert len(result["affected_customers"]) == 2
    assert len(result["drafts"]) == 1
    assert any(g["code"] == "missing_account_manager" for g in result["gaps"])


@pytest.mark.parametrize("document_id", ["acme:POL-12", "acme:KB-208"])
def test_missing_policy_blocks_all_actions(client, app, admin, document_id):
    with app.state.sessions() as session:
        session.get(Document, document_id).visibility = "restricted"
        session.commit()
    result = analyze(client, admin)
    assert not result["drafts"]
    assert any(g["code"] == "missing_document" for g in result["gaps"])
    source_ids = {source["id"] for source in result["sources"]}
    assert all(set(conflict["source_ids"]) <= source_ids for conflict in result["conflicts"])


def test_inactive_subscription_excluded(client, app, admin):
    with app.state.sessions() as session:
        session.get(Subscription, "acme:sub-atlas").status = "canceled"
        session.commit()
    assert len(analyze(client, admin)["drafts"]) == 1


def test_calendar_week_not_rolling_seven_days(client, app):
    with app.state.sessions() as session:
        incident = session.get(Incident, "acme:INC-1042")
        now = utcnow().replace(hour=12)
        this_monday = now - timedelta(days=now.weekday())
        incident.started_at = this_monday
        session.commit()
        graph = build_workflow(session, app.state.settings, Principal("test", "acme", "analyst"))
        result = graph.invoke({"question": "last week's login incident", "now": now})["result"]
        assert result["status"] == "needs_information"


def test_tenant_isolation(client, app, admin):
    with app.state.sessions() as session:
        seed(session, "other")
        assert session.scalar(select(Incident).where(Incident.tenant == "other"))
    assert client.get("/api/sources/other:KB-208", headers=admin).status_code == 404
    hits = client.get("/api/search", headers=admin, params={"q": "SAML metadata"}).json()
    assert hits and all(h["document_id"].startswith("acme:") for h in hits)
    result = client.post(
        "/api/runs", headers=admin, json={"question": "Analyze incident", "incident_id": "other:INC-1042"}
    ).json()
    assert result["proposal"] is None


def test_regression_dataset(client, app):
    with app.state.sessions() as session:
        report = evaluate(session, app.state.settings)
        assert report["passed"], report
