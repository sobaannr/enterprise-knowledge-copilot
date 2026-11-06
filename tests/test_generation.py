from copilot.generation import ModelAnswer, Quote, verify_quotes


def test_unsupported_quotes_rejected():
    source = {"chunk_id": "source#0", "title": "Policy", "excerpt": "Never disable MFA or SSO enforcement."}
    candidate = ModelAnswer(
        quotes=[
            Quote(source_id="source#0", text="Never disable MFA or SSO enforcement."),
            Quote(source_id="source#0", text="Always disable MFA for every customer."),
            Quote(source_id="invented", text="Never disable MFA or SSO enforcement."),
        ]
    )
    accepted, rejected = verify_quotes(candidate, [source])
    assert len(accepted) == 1
    assert len(rejected) == 2


def test_knowledge_endpoint_cannot_create_tickets(client, admin):
    response = client.post("/api/answers", headers=admin, json={"question": "What are our API rate limits?"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert any("1,000" in quote["text"] for quote in result["quotes"])
    assert not result["verification"]["rejected"]
    assert client.get("/api/tickets", headers=admin).json() == []
