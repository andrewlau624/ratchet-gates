# ruleid: ratchet-skip-without-ticket
@pytest.mark.skip
def test_it():
    pass

# ok: ratchet-skip-without-ticket
@pytest.mark.skip(reason="TICKET-1234 pending")
def test_it():
    pass
