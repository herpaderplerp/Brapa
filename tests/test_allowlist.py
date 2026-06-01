from app.config import Settings


def test_empty_allowlist_is_open():
    s = Settings(allowed_emails="")
    assert s.email_allowed("anyone@example.com") is True
    assert s.email_allowed(None) is True


def test_allowlist_admits_only_listed():
    s = Settings(allowed_emails="me@x.com, Friend@Y.com")
    assert s.email_allowed("me@x.com") is True
    assert s.email_allowed("friend@y.com") is True  # case-insensitive
    assert s.email_allowed("stranger@z.com") is False
    assert s.email_allowed(None) is False
