from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"model", "model_off", "store", "rules_version", "git_sha"}
    assert isinstance(body["model_off"], bool)
