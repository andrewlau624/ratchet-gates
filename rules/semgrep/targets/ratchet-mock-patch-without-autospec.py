# ruleid: ratchet-mock-patch-without-autospec
@patch("module.SomeClass")
def test_it(mock):
    pass

# ok: ratchet-mock-patch-without-autospec
@patch("module.SomeClass", autospec=True)
def test_it(mock):
    pass
