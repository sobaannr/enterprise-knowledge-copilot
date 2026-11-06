import pytest
from fastapi.testclient import TestClient

from copilot.api import create_app
from copilot.config import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            seed_demo=True,
            admin_token="test-admin-token-123",
            reader_token="test-reader-token-123",
            retrieval_backend="local",
            rerank=False,
            generation_backend="extractive",
            _env_file=None,
        )
    )


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def admin():
    return {"Authorization": "Bearer test-admin-token-123"}


@pytest.fixture
def analyst():
    return {"Authorization": "Bearer test-reader-token-123"}


def analyze(client, headers):
    response = client.post(
        "/api/runs",
        headers=headers,
        json={
            "question": "Which enterprise customers were affected by last week's login incident? Prepare follow-ups."
        },
    )
    assert response.status_code == 200, response.text
    return response.json()
