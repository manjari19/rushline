import time

from app import tokens

SECRET = "s3cret"


def test_valid_token_roundtrip():
    t = tokens.issue(SECRET, "alice", 1, 60)
    assert tokens.verify(SECRET, t, "alice", 1)


def test_rejects_wrong_buyer_sale_secret_and_garbage():
    t = tokens.issue(SECRET, "alice", 1, 60)
    assert not tokens.verify(SECRET, t, "bob", 1)
    assert not tokens.verify(SECRET, t, "alice", 2)
    assert not tokens.verify("other-secret", t, "alice", 1)
    assert not tokens.verify(SECRET, "garbage", "alice", 1)
    assert not tokens.verify(SECRET, "a.b", "alice", 1)


def test_rejects_expired_token():
    t = tokens.issue(SECRET, "alice", 1, -1)
    assert not tokens.verify(SECRET, t, "alice", 1)
