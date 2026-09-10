"""Tests for shared key-validation primitives."""

from shared.keys import has_path_traversal


def test_rejects_parent_traversal():
    assert has_path_traversal("../secret") is True


def test_rejects_embedded_traversal():
    assert has_path_traversal("uploads/../secret") is True


def test_rejects_backslash():
    assert has_path_traversal("uploads\\secret") is True


def test_rejects_encoded_traversal():
    assert has_path_traversal("uploads/%2e%2e/secret") is True


def test_rejects_null_byte():
    assert has_path_traversal("uploads/\x00secret") is True
    assert has_path_traversal("uploads/%00secret") is True


def test_case_insensitive():
    assert has_path_traversal("uploads/%2E%2E/secret") is True


def test_accepts_plain_keys():
    assert has_path_traversal("uploads/user-1/report.pdf") is False
    assert has_path_traversal("generated/u1/runs/a.png") is False
