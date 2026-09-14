"""Calculate affected workspace projects for CI.

The dependency graph comes from project manifests. Lockfiles and CI metadata
are treated as ecosystem-wide inputs because their internal formats are not a
stable graph API.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ZERO_SHA = "0" * 40
NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


@dataclass
class Project:
    path: str
    name: str
    ecosystem: str
    dependencies: set[str] = field(default_factory=set)


TASKS: dict[str, dict[str, Any]] = json.loads(
    Path(__file__).with_name("projects.json").read_text(encoding="utf-8")
)


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_name(value: str) -> str | None:
    match = NAME_RE.match(value)
    return normalize_name(match.group(1)) if match else None


def load_toml_dependencies(path: Path) -> set[str]:
    import tomllib

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    values = list(project.get("dependencies", []))
    for optional in project.get("optional-dependencies", {}).values():
        values.extend(optional)
    return {name for value in values if (name := dependency_name(value))}


def run_uv_metadata(repo_root: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["uv", "workspace", "metadata"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"uv workspace metadata failed: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("members"), list):
        raise TypeError("uv workspace metadata has no valid members list")
    return data


def discover_python_projects(repo_root: Path, metadata: dict[str, Any] | None = None) -> list[Project]:
    metadata = metadata or run_uv_metadata(repo_root)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("members"), list):
        raise TypeError("uv workspace metadata has no valid members list")
    projects: list[Project] = []
    for member in metadata["members"]:
        if not isinstance(member, dict) or not isinstance(member.get("path"), str):
            raise TypeError("uv workspace metadata contains an invalid member")
        member_path = Path(member["path"])
        if not member_path.is_absolute():
            member_path = repo_root / member_path
        try:
            relative = member_path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"workspace member is outside repository: {member_path}") from exc
        manifest = repo_root / relative / "pyproject.toml"
        if not manifest.is_file():
            raise RuntimeError(f"workspace member has no pyproject.toml: {relative}")
        projects.append(
            Project(
                path=relative,
                name=normalize_name(str(member.get("name", ""))),
                ecosystem="python",
                dependencies=load_toml_dependencies(manifest),
            )
        )
    return projects


def workspace_globs(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    patterns: list[str] = []
    in_packages = False
    for line in lines:
        if line.strip() == "packages:":
            in_packages = True
            continue
        if in_packages and line and not line[0].isspace():
            break
        if in_packages:
            match = re.match(r"\s*-\s*[\"']?([^\"']+?)[\"']?\s*$", line)
            if match:
                patterns.append(match.group(1).strip())
    if not patterns:
        raise RuntimeError("pnpm-workspace.yaml has no packages list")
    return patterns


def discover_node_projects(repo_root: Path) -> list[Project]:
    manifests: set[Path] = set()
    for pattern in workspace_globs(repo_root / "pnpm-workspace.yaml"):
        for candidate in repo_root.glob(pattern):
            manifest = candidate / "package.json"
            if manifest.is_file():
                manifests.add(manifest)
    projects: list[Project] = []
    for manifest in sorted(manifests):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        relative = manifest.parent.relative_to(repo_root).as_posix()
        dependencies: set[str] = set()
        for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            dependencies.update(normalize_name(name) for name in data.get(section, {}))
        projects.append(
            Project(
                path=relative,
                name=normalize_name(str(data.get("name", ""))),
                ecosystem="node",
                dependencies=dependencies,
            )
        )
    return projects


def changed_files(repo_root: Path, base: str, head: str) -> list[str]:
    if base == ZERO_SHA:
        return [line for line in subprocess.check_output(["git", "ls-files"], cwd=repo_root, text=True).splitlines()]
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base, head],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def is_documentation_file(file_path: str) -> bool:
    """Return whether a changed path is documentation-only CI input."""
    path = Path(file_path)
    return file_path.startswith("docs/") or path.suffix.lower() in {".md", ".mdx"}


def reverse_dependents(projects: list[Project]) -> dict[str, set[str]]:
    by_name = {project.name: project.path for project in projects if project.name}
    reverse = {project.path: set() for project in projects}
    for project in projects:
        for dependency in project.dependencies:
            if dependency in by_name and by_name[dependency] != project.path:
                reverse[by_name[dependency]].add(project.path)
    return reverse


def closure(seeds: set[str], reverse: dict[str, set[str]]) -> set[str]:
    affected = set(seeds)
    pending = list(seeds)
    while pending:
        current = pending.pop()
        for dependent in reverse.get(current, set()):
            if dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)
    return affected


def project_record(project: Project) -> dict[str, Any] | None:
    task = TASKS.get(project.path)
    if task is None or not task["tasks"]:
        return None
    return {
        "id": project.path.replace("/", "-"),
        "path": project.path,
        "ecosystem": task["ecosystem"],
        "package_name": task["package_name"],
        "tasks": task["tasks"],
        "run": "\n".join(task["tasks"]),
        "docker": bool(task.get("docker", False)),
    }


def detect(repo_root: Path, base: str, head: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    python_projects = discover_python_projects(repo_root, metadata)
    node_projects = discover_node_projects(repo_root)
    all_projects = python_projects + node_projects
    by_path = {project.path: project for project in all_projects}
    reverse = reverse_dependents(all_projects)
    files = changed_files(repo_root, base, head)
    affected: set[str] = set()
    all_python = False
    all_node = False
    run_all = base == ZERO_SHA
    reasons: list[str] = ["initial history"] if run_all else []

    for file_path in files:
        if file_path.startswith((".github/", "scripts/ci/")):
            all_python = all_node = True
            reasons.append(f"{file_path} affects all projects")
            continue
        if is_documentation_file(file_path):
            continue
        if file_path in {"pyproject.toml", "uv.lock"}:
            all_python = True
            reasons.append(f"{file_path} affects all Python projects")
            continue
        if file_path in {"package.json", "pnpm-workspace.yaml", "pnpm-lock.yaml", "tsconfig.json"}:
            all_node = True
            reasons.append(f"{file_path} affects all Node projects")
            continue
        if file_path == ".dockerignore":
            affected.add("services/agentic-assistant")
            reasons.append(".dockerignore affects the agent image")
            continue
        owners = [path for path in by_path if file_path == path or file_path.startswith(f"{path}/")]
        if owners:
            owner = max(owners, key=len)
            affected.add(owner)
            reasons.append(f"{file_path} changed")
        elif file_path and "/" not in file_path:
            all_python = all_node = True
            reasons.append(f"unknown root file {file_path} affects all projects")
        else:
            all_python = all_node = True
            reasons.append(f"unmapped file {file_path} affects all projects")

    if run_all:
        all_python = all_node = True
    if all_python:
        affected.update(project.path for project in python_projects)
    if all_node:
        affected.update(project.path for project in node_projects)
    affected = closure(affected, reverse)

    unknown = [path for path in affected if path not in TASKS]
    if unknown:
        ecosystems = {by_path[path].ecosystem for path in unknown}
        all_python |= "python" in ecosystems
        all_node |= "node" in ecosystems
        reasons.append(f"missing task metadata for {', '.join(sorted(unknown))}; expanded checks")
        if all_python:
            affected.update(project.path for project in python_projects)
        if all_node:
            affected.update(project.path for project in node_projects)

    records = [project_record(by_path[path]) for path in sorted(affected) if path in by_path]
    records = [record for record in records if record is not None]
    python_records = [record for record in records if record["ecosystem"] == "python"]
    node_records = [record for record in records if record["ecosystem"] == "node"]
    docker_records = [record["id"] for record in python_records if record["docker"]]
    return {
        "run_all": run_all,
        "reasons": sorted(set(reasons)),
        "projects": records,
        "python_projects": python_records,
        "node_projects": node_records,
        "docker_projects": docker_records,
        "has_python": bool(python_records),
        "has_node": bool(node_records),
        "has_docker": bool(docker_records),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Git base commit")
    parser.add_argument("--head", required=True, help="Git head commit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = detect(Path.cwd(), args.base, args.head)
    except (RuntimeError, TypeError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
