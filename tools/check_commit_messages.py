from __future__ import annotations

import argparse
import re
import subprocess
import sys

CONVENTIONAL_SUBJECT = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|test)"
    r"(?:\([a-z0-9][a-z0-9._/-]*\))?!?: [^\s].+$"
)
ZERO_SHA = "0" * 40


def commit_subjects(base: str | None, head: str) -> list[tuple[str, str]]:
    revision = head if not base or base == ZERO_SHA else f"{base}..{head}"
    output = subprocess.run(
        ["git", "log", "--format=%H%x00%s", "--reverse", revision],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    commits: list[tuple[str, str]] = []
    for line in output.splitlines():
        commit, subject = line.split("\0", 1)
        commits.append((commit, subject))
    return commits


def validate_subject(subject: str) -> str | None:
    if len(subject) > 100:
        return "title exceeds 100 characters"
    if subject.endswith((".", "。")):
        return "title must not end with a period"
    if not CONVENTIONAL_SUBJECT.fullmatch(subject):
        return "title does not follow Conventional Commits"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Git commit titles.")
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    failures = []
    for commit, subject in commit_subjects(args.base, args.head):
        if error := validate_subject(subject):
            failures.append(f"{commit[:12]} {subject!r}: {error}")

    if failures:
        print("Invalid commit titles:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("All commit titles follow the project convention.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
