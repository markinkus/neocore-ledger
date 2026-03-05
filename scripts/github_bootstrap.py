"""Bootstrap GitHub labels, seed issues, and a release for NeoCore."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API_BASE: Final[str] = "https://api.github.com"


@dataclass(frozen=True, slots=True)
class LabelSpec:
    """GitHub label definition."""

    name: str
    color: str
    description: str


@dataclass(frozen=True, slots=True)
class IssueSpec:
    """GitHub issue definition."""

    title: str
    body: str
    labels: tuple[str, ...]


LABELS: Final[tuple[LabelSpec, ...]] = (
    LabelSpec("good first issue", "7057ff", "Small and self-contained starter task."),
    LabelSpec("help wanted", "008672", "Maintainers are looking for contributions."),
    LabelSpec("design", "5319e7", "Architecture and API design topics."),
    LabelSpec("docs", "1d76db", "Documentation improvements."),
)


ISSUES: Final[tuple[IssueSpec, ...]] = (
    IssueSpec(
        title="Add AUD currency to CURRENCY_REGISTRY with tests",
        body="Extend `CURRENCY_REGISTRY` with AUD and add unit tests for quantization behavior.",
        labels=("good first issue", "help wanted"),
    ),
    IssueSpec(
        title="Add CAD currency to CURRENCY_REGISTRY with tests",
        body="Extend `CURRENCY_REGISTRY` with CAD and add unit tests for quantization behavior.",
        labels=("good first issue", "help wanted"),
    ),
    IssueSpec(
        title="Improve InsufficientFundsError message with overdraft policy context",
        body=(
            "Include policy mode (`STRICT`/`OVERDRAFT_LIMIT`) in the exception message and"
            " add tests for the new message format."
        ),
        labels=("good first issue",),
    ),
    IssueSpec(
        title="Add overdraft_limit edge-case tests at exact threshold",
        body=(
            "Add tests where available + limit equals required amount to ensure no false"
            " negatives."
        ),
        labels=("good first issue",),
    ),
    IssueSpec(
        title="Document multi-currency rejection path with minimal example",
        body="Add a docs section showing currency mismatch behavior and expected exception.",
        labels=("docs",),
    ),
    IssueSpec(
        title="Add get_statement usage example to README",
        body="Show a minimal running-balance statement example in README.",
        labels=("docs",),
    ),
    IssueSpec(
        title="Add benchmark script for MemoryStore vs SQLiteStore posting throughput",
        body="Provide a simple benchmark script and usage notes under `examples/` or `scripts/`.",
        labels=("design", "help wanted"),
    ),
    IssueSpec(
        title="Prototype PostgresStore mapping against LedgerStore protocol",
        body="Create a design spike for a PostgreSQL-backed store implementation.",
        labels=("design",),
    ),
    IssueSpec(
        title="Add reversible capture template with explicit original transaction linkage",
        body="Design a template extension that references original capture transaction metadata.",
        labels=("design",),
    ),
    IssueSpec(
        title="Extend payment rail scenario with partial settle and residual fee handling",
        body="Add one scenario + tests for partial settlement and fee allocation edge cases.",
        labels=("help wanted",),
    ),
    IssueSpec(
        title="Define JSON schema for external template definitions",
        body="Propose and document a JSON schema for loading posting templates declaratively.",
        labels=("design",),
    ),
    IssueSpec(
        title="Add troubleshooting guide for idempotency collisions and retries",
        body="Create docs troubleshooting section focused on webhook retry and dedupe behavior.",
        labels=("docs", "good first issue"),
    ),
)


def github_request(
    *,
    token: str,
    method: str,
    path: str,
    payload: object | None = None,
) -> tuple[int, object | None]:
    """Perform an authenticated GitHub API request."""

    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return response.status, None
            return response.status, json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        if raw:
            return exc.code, json.loads(raw)
        return exc.code, None


def detect_repo_slug() -> str:
    """Detect owner/repo from git remote origin."""

    remote = subprocess.check_output(
        ["git", "remote", "get-url", "origin"],
        text=True,
    ).strip()
    if remote.startswith("git@github.com:"):
        slug = remote.removeprefix("git@github.com:")
    elif remote.startswith("https://github.com/"):
        slug = remote.removeprefix("https://github.com/")
    else:
        raise ValueError(f"unsupported remote URL: {remote}")
    if slug.endswith(".git"):
        slug = slug[:-4]
    if "/" not in slug:
        raise ValueError(f"cannot parse owner/repo from remote URL: {remote}")
    return slug


def read_release_body(tag: str) -> str:
    """Extract release notes section from CHANGELOG."""

    version = tag.removeprefix("v")
    changelog = Path("CHANGELOG.md")
    if not changelog.exists():
        return f"Release {tag}"

    content = changelog.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\].*?\n(?P<body>.*?)(?=^## |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if match is None:
        return f"Release {tag}"
    return match.group("body").strip() or f"Release {tag}"


def ensure_labels(*, token: str, repo: str, dry_run: bool) -> None:
    """Create missing labels."""

    status, payload = github_request(
        token=token,
        method="GET",
        path=f"/repos/{repo}/labels?per_page=100",
    )
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"failed to list labels (status={status}): {payload}")

    existing_names = {
        item["name"]
        for item in payload
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    for label in LABELS:
        if label.name in existing_names:
            print(f"[labels] exists: {label.name}")
            continue
        print(f"[labels] create: {label.name}")
        if dry_run:
            continue
        status, payload = github_request(
            token=token,
            method="POST",
            path=f"/repos/{repo}/labels",
            payload={
                "name": label.name,
                "color": label.color,
                "description": label.description,
            },
        )
        if status not in {201, 422}:
            raise RuntimeError(f"failed to create label {label.name} (status={status}): {payload}")


def ensure_issues(*, token: str, repo: str, dry_run: bool) -> None:
    """Create missing seed issues."""

    status, payload = github_request(
        token=token,
        method="GET",
        path=f"/repos/{repo}/issues?state=all&per_page=100",
    )
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"failed to list issues (status={status}): {payload}")

    existing_titles = {
        item["title"]
        for item in payload
        if isinstance(item, dict)
        and isinstance(item.get("title"), str)
        and "pull_request" not in item
    }

    for issue in ISSUES:
        if issue.title in existing_titles:
            print(f"[issues] exists: {issue.title}")
            continue
        print(f"[issues] create: {issue.title}")
        if dry_run:
            continue
        status, payload = github_request(
            token=token,
            method="POST",
            path=f"/repos/{repo}/issues",
            payload={
                "title": issue.title,
                "body": issue.body,
                "labels": list(issue.labels),
            },
        )
        if status != 201:
            raise RuntimeError(f"failed to create issue {issue.title} (status={status}): {payload}")


def ensure_release(
    *,
    token: str,
    repo: str,
    tag: str,
    target_commitish: str,
    dry_run: bool,
) -> None:
    """Create GitHub release if missing."""

    status, payload = github_request(
        token=token,
        method="GET",
        path=f"/repos/{repo}/releases/tags/{tag}",
    )
    if status == 200:
        print(f"[release] exists: {tag}")
        return
    if status != 404:
        raise RuntimeError(f"failed to inspect release {tag} (status={status}): {payload}")

    print(f"[release] create: {tag}")
    if dry_run:
        return

    status, payload = github_request(
        token=token,
        method="POST",
        path=f"/repos/{repo}/releases",
        payload={
            "tag_name": tag,
            "target_commitish": target_commitish,
            "name": tag,
            "body": read_release_body(tag),
            "draft": False,
            "prerelease": False,
        },
    )
    if status != 201:
        raise RuntimeError(f"failed to create release {tag} (status={status}): {payload}")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="GitHub repo slug (owner/repo).")
    parser.add_argument("--tag", default="v0.1.1", help="Release tag to create if missing.")
    parser.add_argument(
        "--target-commitish",
        default="main",
        help="Target branch/commit for tag creation during release.",
    )
    parser.add_argument("--skip-labels", action="store_true", help="Skip label creation.")
    parser.add_argument("--skip-issues", action="store_true", help="Skip seed issue creation.")
    parser.add_argument("--skip-release", action="store_true", help="Skip release creation.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without API writes.")
    return parser.parse_args()


def main() -> int:
    """Bootstrap repository metadata on GitHub."""

    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token is None:
        raise RuntimeError("missing GITHUB_TOKEN (or GH_TOKEN) environment variable")

    repo = args.repo or detect_repo_slug()
    print(f"[info] repo={repo} tag={args.tag} dry_run={args.dry_run}")

    if not args.skip_labels:
        ensure_labels(token=token, repo=repo, dry_run=args.dry_run)
    if not args.skip_issues:
        ensure_issues(token=token, repo=repo, dry_run=args.dry_run)
    if not args.skip_release:
        ensure_release(
            token=token,
            repo=repo,
            tag=args.tag,
            target_commitish=args.target_commitish,
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
