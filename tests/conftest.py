import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "test-ledger.db")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def account(client):
    response = client.post("/accounts", json={"name": "Nimesh"})
    assert response.status_code == 201
    return response.json()
