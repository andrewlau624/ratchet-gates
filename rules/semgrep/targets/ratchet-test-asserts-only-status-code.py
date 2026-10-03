def test_it():
    res = client.get("/x")
    # ruleid: ratchet-test-asserts-only-status-code
    assert res.status_code == 200


def test_ok():
    res = client.get("/x")
    # ok: ratchet-test-asserts-only-status-code
    assert res.json()["ok"] is True
