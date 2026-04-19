"""Tests for alert subscription and rule management endpoints."""


def test_subscribe(client, seed_locations):
    resp = client.post("/api/alerts/subscribe", json={
        "phone_number": "+19999999999",
        "name": "Test User",
        "location": "alpine",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "subscribed"
    assert "subscriber_id" in data


def test_subscribe_duplicate(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999998"})
    resp = client.post("/api/alerts/subscribe", json={"phone_number": "+19999999998"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_subscribed"


def test_subscribe_invalid_phone(client, seed_locations):
    resp = client.post("/api/alerts/subscribe", json={
        "phone_number": "not-a-phone",
    })
    assert resp.status_code == 422


def test_add_rule(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999997"})
    resp = client.post("/api/alerts/rules", json={
        "phone_number": "+19999999997",
        "target_name": "snowfall_24h",
        "operator": ">",
        "threshold": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rule_created"
    assert data["target_name"] == "snowfall_24h"
    assert data["threshold"] == 10


def test_add_rule_unsubscribed(client, seed_locations):
    resp = client.post("/api/alerts/rules", json={
        "phone_number": "+19999999996",
        "target_name": "snowfall_24h",
        "operator": ">",
        "threshold": 10,
    })
    assert resp.status_code == 404


def test_add_rule_invalid_target(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999995"})
    resp = client.post("/api/alerts/rules", json={
        "phone_number": "+19999999995",
        "target_name": "invalid_target",
        "operator": ">",
        "threshold": 10,
    })
    assert resp.status_code == 422


def test_add_rule_invalid_operator(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999994"})
    resp = client.post("/api/alerts/rules", json={
        "phone_number": "+19999999994",
        "target_name": "snowfall_24h",
        "operator": "!=",
        "threshold": 10,
    })
    assert resp.status_code == 422


def test_list_rules(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999993"})
    client.post("/api/alerts/rules", json={
        "phone_number": "+19999999993",
        "target_name": "snowfall_24h",
        "operator": ">",
        "threshold": 10,
    })
    client.post("/api/alerts/rules", json={
        "phone_number": "+19999999993",
        "target_name": "wind_6h",
        "operator": ">",
        "threshold": 50,
    })

    resp = client.get("/api/alerts/rules/+19999999993")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rules"]) == 2


def test_delete_rule(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999992"})
    create_resp = client.post("/api/alerts/rules", json={
        "phone_number": "+19999999992",
        "target_name": "snowfall_24h",
        "operator": ">",
        "threshold": 10,
    })
    rule_id = create_resp.json()["rule_id"]

    resp = client.delete(f"/api/alerts/rules/{rule_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_unsubscribe(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999991"})
    resp = client.post("/api/alerts/unsubscribe", json={"phone_number": "+19999999991"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unsubscribed"


def test_resubscribe_after_unsub(client, seed_locations):
    client.post("/api/alerts/subscribe", json={"phone_number": "+19999999990"})
    client.post("/api/alerts/unsubscribe", json={"phone_number": "+19999999990"})
    resp = client.post("/api/alerts/subscribe", json={"phone_number": "+19999999990"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "reactivated"


def test_alert_history(client):
    resp = client.get("/api/alerts/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
