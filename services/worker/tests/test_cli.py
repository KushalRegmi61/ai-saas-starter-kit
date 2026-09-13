"""Tests for the worker CLI."""

import json

from worker.main import main


def test_validate_key_accepts_clean_key(capsys):
    assert main(["validate-key", "uploads/user-1/report.pdf"]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_key_rejects_traversal(capsys):
    assert main(["validate-key", "uploads/../secret"]) == 1
    assert "REJECTED" in capsys.readouterr().out


def test_health_reports_ok(capsys):
    assert main(["health"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
