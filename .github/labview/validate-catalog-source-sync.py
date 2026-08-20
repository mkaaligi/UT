#!/usr/bin/env python3
"""Validate that the installer catalog matches the source-owned files."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / ".github" / "labview-ci" / "catalog.json"

# Files that exist ONLY in the tooling source repository -- the release and
# publishing machinery. A consumer install never has them, so the configurator
# (integrate.html), which is a CLIENT installer, classifies them as "old tooling
# files" and deletes them. Running the configurator against this repo (or a fork
# of it) therefore strips the repo's ability to publish at all. That is exactly
# what happened in e9cd54b on 2026-07-30, which also downgraded catalog.json from
# 4.12.4 to 4.11.10 and left 4.11.11-4.12.4 unpublished for two weeks.
#
# This list is the repo-side backstop for that class of mistake: it cannot be
# bypassed by a stale browser tab or a hand-edited PR the way a UI check can.
SOURCE_ONLY_FILES = [
    ".github/labview-ci/source.json",
    ".github/labview/promote-release.py",
    ".github/labview/validate-catalog-source-sync.py",
    ".github/labview/vipm/build-tooling-vipc.py",
    ".github/pages/configure.html",
    ".github/pages/integrate.html",
    ".github/pages/whats-new.html",
    ".github/workflows/build-labview-image.yml",
    ".github/workflows/build-labview-linux-image.yml",
    ".github/workflows/catalog-source-sync.yml",
    ".github/workflows/copy-labview-image.yml",
    ".github/workflows/copy-labview-linux-image.yml",
    ".github/workflows/discover-clients.yml",
    ".github/workflows/integrate-deploy.yml",
    ".github/workflows/labview-ci.reusable.yml",
    ".github/workflows/promote-release.yml",
    ".github/workflows/release.yml",
]

REQUIRED_CUSTOM_IMAGE_WINDOWS = [
    ".github/workflows/build-labview-image.yml",
    ".github/workflows/copy-labview-image.yml",
    ".github/docker/labview-ci-base.Dockerfile",
    ".github/docker/labview-ci.Dockerfile",
    ".github/labview/vipm/",
]

OBSOLETE_WINDOWS_WORKER_FILES = {
    ".github/docker/labview-vipm-base.Dockerfile",
    ".github/docker/labview-vipc-layer.Dockerfile",
}


def err(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def path_exists(relpath: str) -> bool:
    return (ROOT / relpath).exists()


SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (text or "").strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def published_tag_names() -> set[str]:
    """Every published version as a bare string ("4.12.4"), empty if tags are unavailable."""
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*.*.*"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    names = set()
    for line in out.stdout.splitlines():
        tag = line.strip()
        if SEMVER_TAG.match(tag):
            names.add(tag[1:])
    return names


def highest_published_version() -> tuple[tuple[int, int, int], str] | None:
    """Highest v<MAJOR>.<MINOR>.<PATCH> tag in this clone, or None if unknown.

    Returns None when git is unavailable or no version tags are present (a
    shallow CI checkout, or a clone fetched without tags). Callers must treat
    None as "could not check" rather than "nothing published" -- see main().
    """
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v*.*.*"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None

    best: tuple[tuple[int, int, int], str] | None = None
    for line in out.stdout.splitlines():
        match = SEMVER_TAG.match(line.strip())
        if not match:
            continue
        parsed = (int(match[1]), int(match[2]), int(match[3]))
        if best is None or parsed > best[0]:
            best = (parsed, line.strip())
    return best


def main() -> int:
    failures: list[str] = []

    # Run FIRST: everything below reads source-owned files directly, so a repo
    # that has had its publishing machinery deleted should fail with this clear
    # message rather than a FileNotFoundError traceback further down.
    missing_source_files = [p for p in SOURCE_ONLY_FILES if not path_exists(p)]
    if missing_source_files:
        err(
            "This repository is the LabVIEW CI tooling SOURCE, but files that only "
            "the source repo carries have been deleted:"
        )
        for relpath in missing_source_files:
            err(f"  - {relpath}")
        err(
            "This is the signature of running the LabVIEW CI configurator (the client "
            "installer) against the source repo or a fork of it: it removes source-only "
            "files as 'old tooling' and overwrites catalog.json with an older payload. "
            "Restore these files from the last release tag instead of merging this change."
        )
        return 1

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    releases = (catalog.get("history") or {}).get("releases") or []
    if not releases:
        failures.append("catalog history.releases is empty")
    elif catalog.get("version") != releases[0].get("version"):
        failures.append(
            "catalog version must equal history.releases[0].version "
            f"({catalog.get('version')!r} != {releases[0].get('version')!r})"
        )

    # The catalog version is the version of record: release.yml reads it to cut
    # the tag and move the v<major> alias every client pins to. It must never go
    # backwards. It regressed once (4.12.4 -> 4.11.10) and the failure was silent
    # -- the file stayed internally consistent, so the check above still passed,
    # while release.yml quietly stopped publishing because v4.11.10 already
    # existed. Comparing against the tags is what makes that visible.
    current = parse_version(catalog.get("version") or "")
    if current is None:
        failures.append(
            f"catalog version {catalog.get('version')!r} is not MAJOR.MINOR.PATCH"
        )
    else:
        published = highest_published_version()
        if published is None:
            message = (
                "could not read version tags, so the catalog version was NOT checked "
                "against the published releases (fetch tags: actions/checkout with "
                "fetch-depth: 0)"
            )
            # Lenient for local runs on a shallow/tagless clone; strict in CI,
            # where a silently skipped guard is how this got missed the first time.
            if os.environ.get("GITHUB_ACTIONS") == "true":
                failures.append(message)
            else:
                print(f"WARNING: {message}", file=sys.stderr)
        elif current < published[0]:
            failures.append(
                f"catalog version {catalog['version']} is LOWER than the highest "
                f"published release {published[1]}. The version of record must never "
                "go backwards: release.yml would find the tag already present, publish "
                "nothing, and leave the v<major> alias stranded on the newer release. "
                f"Set version to something above {published[1].lstrip('v')} (and add a "
                "matching history.releases[0] entry)."
            )

    # Channel pointers must name a version that was actually PUBLISHED, not merely
    # written into the catalog. promote-release.yml used to bump the catalog and
    # rely on release.yml to tag it, but GITHUB_TOKEN pushes do not trigger
    # workflows -- so 4.10.2, 4.10.3 and 4.11.11 were announced and never tagged,
    # and the `beta` tag sat on v4.11.8 for three weeks while betaVersion said
    # 4.11.10. Pointing a channel at an untagged version strands every client on
    # that channel, so it is worth failing over.
    tagged = published_tag_names()
    for tier in ("stableVersion", "betaVersion"):
        pointer = (catalog.get(tier) or "").strip()
        if not pointer:
            continue
        if parse_version(pointer) is None:
            failures.append(f"{tier} {pointer!r} is not MAJOR.MINOR.PATCH")
        elif tagged and pointer not in tagged:
            failures.append(
                f"{tier} points at {pointer}, which has no v{pointer} tag. A channel "
                "must name a published release; clients on that channel would resolve "
                "to a version that does not exist."
            )

    capabilities = catalog.get("capabilities") or []
    custom_image = next((cap for cap in capabilities if cap.get("id") == "custom-image"), None)
    if custom_image is None:
        failures.append("catalog is missing the custom-image capability")
    else:
        windows_files = custom_image.get("files", {}).get("windows") or []
        if windows_files != REQUIRED_CUSTOM_IMAGE_WINDOWS:
            failures.append(
                "custom-image windows files must exactly match the source-owned "
                f"Windows worker file set: {windows_files!r}"
            )
        obsolete = sorted(set(windows_files) & OBSOLETE_WINDOWS_WORKER_FILES)
        if obsolete:
            failures.append(f"custom-image still vendors obsolete worker files: {obsolete!r}")

    for capability in capabilities:
        capability_id = capability.get("id", "<unknown>")
        files = capability.get("files") or {}
        for os_name, relpaths in files.items():
            for relpath in relpaths or []:
                if not path_exists(relpath):
                    failures.append(
                        f"capability {capability_id!r} lists missing {os_name} file: {relpath}"
                    )

    workflow = ROOT / ".github" / "workflows" / "build-labview-image.yml"
    workflow_text = workflow.read_text(encoding="utf-8")
    docker_final = ROOT / ".github" / "docker" / "labview-ci.Dockerfile"
    docker_final_text = docker_final.read_text(encoding="utf-8")

    for relpath in REQUIRED_CUSTOM_IMAGE_WINDOWS:
        if not path_exists(relpath):
            failures.append(f"required custom-image source file is missing: {relpath}")

    for obsolete in OBSOLETE_WINDOWS_WORKER_FILES:
        if path_exists(obsolete):
            failures.append(f"obsolete Windows worker Dockerfile still exists: {obsolete}")
        if obsolete in workflow_text:
            failures.append(f"build-labview-image.yml still references obsolete file: {obsolete}")

    if ".github/docker/labview-ci-base.Dockerfile" not in workflow_text:
        failures.append("build-labview-image.yml does not reference labview-ci-base.Dockerfile")
    if "LCWC_BASE_IMAGE" not in workflow_text:
        failures.append("build-labview-image.yml does not define/use LCWC_BASE_IMAGE")
    if "FROM ${LCWC_BASE_IMAGE}" not in docker_final_text:
        failures.append("labview-ci.Dockerfile must start from LCWC_BASE_IMAGE")

    if failures:
        for failure in failures:
            err(failure)
        return 1

    print("Catalog/source sync validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())