"""Merge a Dependabot PR only after trusted, exact-revision checks pass."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_ROOT = "https://api.github.com"
TITLE_PATTERN = re.compile(r"^(?:build|ci)\(deps(?:-dev)?\): [^\r\n]+$")


def api(method: str, path: str, data: dict[str, Any] | None = None) -> Any:
    token = os.environ["GITHUB_TOKEN"]
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "chinaz-top-domains-dependabot-automerge",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed: {exc.code} {detail}") from exc
    return json.loads(payload) if payload else None


def resolve_pull_request(repository: str, head_sha: str) -> dict[str, Any] | None:
    number = os.environ.get("WORKFLOW_RUN_PR_NUMBER", "").strip()
    if number:
        return api("GET", f"/repos/{repository}/pulls/{int(number)}")

    candidates = api("GET", f"/repos/{repository}/commits/{head_sha}/pulls")
    matches = [
        pull
        for pull in candidates
        if pull["state"] == "open"
        and pull["base"]["ref"] == "master"
        and pull["head"]["sha"] == head_sha
    ]
    if len(matches) != 1:
        print(f"Expected one open PR for {head_sha}, found {len(matches)}; nothing to do.")
        return None
    return matches[0]


def validate_pull_request(pull: dict[str, Any], repository: str, head_sha: str) -> None:
    checks = {
        "state": pull["state"] == "open",
        "base": pull["base"]["ref"] == "master",
        "actor": pull["user"]["login"] == "dependabot[bot]",
        "same repository": pull["head"]["repo"]["full_name"] == repository,
        "not draft": not pull["draft"],
        "exact head SHA": pull["head"]["sha"] == head_sha,
        "automerge label": "automerge" in {label["name"] for label in pull["labels"]},
        "conventional title": TITLE_PATTERN.fullmatch(pull["title"]) is not None,
    }
    rejected = [name for name, passed in checks.items() if not passed]
    if rejected:
        raise RuntimeError("Dependabot PR validation failed: " + ", ".join(rejected))


def required_workflows_succeeded(repository: str, head_sha: str) -> bool:
    query = urllib.parse.urlencode({"head_sha": head_sha, "event": "pull_request", "per_page": 100})
    runs = api("GET", f"/repos/{repository}/actions/runs?{query}")["workflow_runs"]
    required = [name.strip() for name in os.environ["REQUIRED_WORKFLOWS"].split(",")]

    for name in required:
        candidates = [run for run in runs if run["name"] == name]
        if not candidates:
            print(f"Waiting for required workflow: {name}")
            return False
        latest = max(candidates, key=lambda run: (run["run_attempt"], run["id"]))
        if latest["status"] != "completed" or latest["conclusion"] != "success":
            print(
                f"Waiting for {name}: status={latest['status']} conclusion={latest['conclusion']}"
            )
            return False
    return True


def dispatch_master_checks(repository: str) -> None:
    for workflow in ("ci.yml", "codeql.yml"):
        api(
            "POST",
            f"/repos/{repository}/actions/workflows/{workflow}/dispatches",
            {"ref": "master"},
        )


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    head_sha = os.environ["WORKFLOW_RUN_HEAD_SHA"]
    pull = resolve_pull_request(repository, head_sha)
    if pull is None:
        return 0

    validate_pull_request(pull, repository, head_sha)
    if not required_workflows_succeeded(repository, head_sha):
        return 0

    # Re-read immediately before merging to close the synchronize race window.
    pull = api("GET", f"/repos/{repository}/pulls/{pull['number']}")
    validate_pull_request(pull, repository, head_sha)
    result = api(
        "PUT",
        f"/repos/{repository}/pulls/{pull['number']}/merge",
        {
            "sha": head_sha,
            "merge_method": "squash",
            "commit_title": pull["title"],
            "commit_message": "Automated Dependabot update.",
        },
    )
    if not result.get("merged"):
        raise RuntimeError(f"GitHub did not merge PR #{pull['number']}: {result}")

    print(f"Merged Dependabot PR #{pull['number']} at {head_sha}.")
    dispatch_master_checks(repository)
    print("Dispatched post-merge CI and CodeQL checks on master.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
