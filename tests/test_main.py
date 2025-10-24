from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json().get("message")

def test_items_crud():
    # start with empty list
    r = client.get("/api/items")
    assert r.status_code == 200
    assert r.json() == []

    # create item
    r = client.post("/api/items", json={"name": "foo", "description": "bar"})
    assert r.status_code == 201
    item = r.json()
    assert item["id"] == 1
    assert item["name"] == "foo"

    # retrieve
    r = client.get(f"/api/items/{item['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "foo"
