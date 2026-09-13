from pathlib import Path

import pytest

from scripts.ci import detect_affected

REPO_ROOT = Path(__file__).parents[3]


def run_for(monkeypatch, paths, base="base", head="head"):
    monkeypatch.setattr(detect_affected, "changed_files", lambda *_args: paths)
    return detect_affected.detect(REPO_ROOT, base, head)


def project_paths(result):
    return {project["path"] for project in result["projects"]}


def test_python_shared_change_includes_all_consumers(monkeypatch):
    result = run_for(monkeypatch, ["services/shared/src/shared/types.py"])

    assert project_paths(result) >= {
        "services/shared",
        "services/api",
        "services/worker",
        "services/agentic-assistant",
    }
    assert result["has_docker"] is True


def test_auth_change_includes_api_and_agent(monkeypatch):
    result = run_for(monkeypatch, ["libs/auth/src/auth/tokens.py"])

    assert project_paths(result) >= {"libs/auth", "services/api", "services/agentic-assistant"}
    assert "services/worker" not in project_paths(result)


def test_rag_change_includes_agent(monkeypatch):
    result = run_for(monkeypatch, ["libs/rag/src/rag/retrieval/search.py"])

    assert project_paths(result) >= {"libs/rag", "services/agentic-assistant"}
    assert "services/api" not in project_paths(result)


def test_typescript_shared_change_includes_web(monkeypatch):
    result = run_for(monkeypatch, ["packages/shared/src/types.ts"])

    assert project_paths(result) == {"apps/web"}
    assert result["has_node"] is True
    assert result["has_python"] is False


def test_documentation_change_runs_no_project(monkeypatch):
    result = run_for(monkeypatch, ["docs/deployment.md"])

    assert result["projects"] == []
    assert result["has_python"] is False
    assert result["has_node"] is False


def test_lockfiles_expand_only_their_ecosystem(monkeypatch):
    python_result = run_for(monkeypatch, ["uv.lock"])
    node_result = run_for(monkeypatch, ["pnpm-lock.yaml"])

    assert python_result["has_python"] is True
    assert python_result["has_node"] is False
    assert node_result["has_node"] is True
    assert node_result["has_python"] is False


def test_unknown_root_file_expands_all_projects(monkeypatch):
    result = run_for(monkeypatch, ["Makefile"])

    assert result["run_all"] is False
    assert result["has_python"] is True
    assert result["has_node"] is True
    assert "unknown root file Makefile" in " ".join(result["reasons"])


def test_initial_history_expands_all_projects(monkeypatch):
    result = run_for(monkeypatch, [], base=detect_affected.ZERO_SHA)

    assert result["run_all"] is True
    assert result["has_python"] is True
    assert result["has_node"] is True


def test_dependency_name_normalizes_pep508_name():
    assert detect_affected.dependency_name("My_Package[extra]>=1.0") == "my-package"


def test_closure_handles_cycles():
    reverse = {"a": {"b"}, "b": {"a", "c"}, "c": set()}

    assert detect_affected.closure({"a"}, reverse) == {"a", "b", "c"}


def test_invalid_uv_metadata_is_rejected():
    with pytest.raises(TypeError, match="no valid members list"):
        detect_affected.discover_python_projects(REPO_ROOT, {"members": "invalid"})


def test_output_has_stable_matrix_fields(monkeypatch):
    result = run_for(monkeypatch, ["services/agentic-assistant/src/agent/types.py"])

    assert set(result) == {
        "run_all",
        "reasons",
        "projects",
        "python_projects",
        "node_projects",
        "docker_projects",
        "has_python",
        "has_node",
        "has_docker",
    }
    assert result["python_projects"][0]["package_name"] == "ai-saas-agentic-assistant"


def test_python_tasks_are_safe_to_run_from_repository_root(monkeypatch):
    result = run_for(monkeypatch, ["services/api/app/runtime/health.py"])

    api = next(project for project in result["python_projects"] if project["path"] == "services/api")
    assert "cd " not in api["run"]
    assert "pytest services/api" in api["run"]


def test_python_projects_declare_ci_tools():
    for path in (
        "services/worker",
        "services/shared",
        "libs/auth",
        "libs/rag",
    ):
        manifest = REPO_ROOT / path / "pyproject.toml"
        assert "dev" in manifest.read_text(encoding="utf-8")
