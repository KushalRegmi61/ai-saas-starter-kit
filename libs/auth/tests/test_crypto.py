"""Password hashing contract: opaque hash, safe verify, explicit limits."""

import pytest

from auth.crypto import hash_password, verify_password


def test_hash_is_opaque_and_verifies():
    hashed = hash_password("correct horse")
    assert isinstance(hashed, str)
    assert hashed != "correct horse"
    assert verify_password("correct horse", hashed) is True


def test_wrong_password_does_not_verify():
    hashed = hash_password("correct horse")
    assert verify_password("wrong battery", hashed) is False


def test_malformed_hash_does_not_verify():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        hash_password("")


def test_overlong_password_rejected():
    # bcrypt truncates past 72 bytes; fail loudly instead of silently weakening.
    with pytest.raises(ValueError):
        hash_password("x" * 73)


def test_hashes_differ_per_call():
    assert hash_password("same") != hash_password("same")
