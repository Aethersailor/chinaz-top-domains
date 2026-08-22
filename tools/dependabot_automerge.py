"""Merge a Dependabot PR only after trusted, exact-revision checks pass."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
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


def enable_auto_merge(pull: dict[str, Any]) -> None:
    response = api(
        "POST",
        "/graphql",
        {
            "query": """
                mutation EnableAutoMerge(
                  $pullRequestId: ID!
                  $headline: String!
                  $body: String!
                ) {
                  enablePullRequestAutoMerge(input: {
                    pullRequestId: $pullRequestId
                    mergeMethod: SQUASH
                    commitHeadline: $headline
                    commitBody: $body
                  }) {
                    pullRequest {
                      number
                      autoMergeRequest { enabledAt }
                    }
                  }
                }
            """,
            "variables": {
                "pullRequestId": pull["node_id"],
                "headline": pull["title"],
                "body": "Automated Dependabot update.",
            },
        },
    )
    if errors := response.get("errors"):
        raise RuntimeError(f"GitHub did not enable auto-merge: {errors}")


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    head_sha = os.environ["WORKFLOW_RUN_HEAD_SHA"]
    pull = resolve_pull_request(repository, head_sha)
    if pull is None:
        return 0
    if pull["user"]["login"] != "dependabot[bot]":
        print(f"PR #{pull['number']} is not authored by Dependabot; nothing to do.")
        return 0

    validate_pull_request(pull, repository, head_sha)
    # Branch rules remain authoritative for every required CI and security check.
    # Re-read immediately before enabling auto-merge to close the synchronize race window.
    pull = api("GET", f"/repos/{repository}/pulls/{pull['number']}")
    validate_pull_request(pull, repository, head_sha)
    if pull.get("auto_merge") is not None:
        print(f"Auto-merge is already enabled for Dependabot PR #{pull['number']}.")
        return 0

    enable_auto_merge(pull)
    print(f"Enabled squash auto-merge for Dependabot PR #{pull['number']} at {head_sha}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
