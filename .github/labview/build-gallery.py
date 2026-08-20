#!/usr/bin/env python3
"""
build-gallery.py — Build a per-commit manifest.json and update commits.json for
the content-addressed VI Browser gallery.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _group_for(vi_rel: str) -> str:
    """Group a VI by its top-level folder."""
    parts = vi_rel.replace("\\", "/").split("/")
    if len(parts) > 1 and parts[0]:
        return parts[0]
    return "Project"


def read_vimap(vimap_path: Path) -> list[tuple[str, str]]:
    """Read a TSV worklist of "<blob_sha>\t<vi_rel_path>" lines."""
    entries: list[tuple[str, str]] = []
    if not vimap_path.exists():
        return entries
    for raw in vimap_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            print(f"  WARNING: skipping malformed vimap line: {raw!r}", file=sys.stderr)
            continue
        blob, vi_rel = parts[0].strip(), parts[1].strip().replace("\\", "/")
        if not blob or not vi_rel:
            continue
        entries.append((blob, vi_rel))
    entries.sort(key=lambda e: e[1].lower())
    return entries


def build_manifest(
    vimap: list[tuple[str, str]],
    commit_sha: str,
    by_blob_prefix: str,
) -> list[dict]:
    entries: list[dict] = []
    for blob, vi_rel in vimap:
        html = f"{by_blob_prefix}/{blob[:2]}/{blob}.html"
        entries.append(
            {
                "html": html,
                "vi_name": Path(vi_rel).stem,
                "group": _group_for(vi_rel),
                "vi_rel": vi_rel,
                "blob": blob,
                "commit_sha": commit_sha,
            }
        )
    return entries


def update_commits_json(
    commits_file: Path,
    commit_sha: str,
    commit_msg: str,
    author: str,
    date: str,
    vi_count: int,
) -> list[dict]:
    existing: list[dict] = []
    if commits_file.exists():
        try:
            existing = json.loads(commits_file.read_text(encoding="utf-8-sig"))
        except Exception:
            existing = []

    existing = [c for c in existing if c.get("sha") != commit_sha]

    new_entry = {
        "sha": commit_sha,
        "short": commit_sha[:7],
        "message": (commit_msg or "").splitlines()[0][:120] if commit_msg else "",
        "author": author or "",
        "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vi_count": vi_count,
    }
    existing.insert(0, new_entry)

    existing.sort(key=lambda c: c.get("date", ""), reverse=True)
    return existing[:200]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build VI Browser gallery manifest (content-addressed).")
    parser.add_argument("--vimap", required=True, help='TSV file: "<blob_sha>\t<vi_rel_path>" per line')
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--commit-msg", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--date", default="", help="ISO-8601 commit date (default: now)")
    parser.add_argument("--output-dir", required=True, help="Dir to write this commit's manifest.json")
    parser.add_argument("--commits-file", required=True, help="Path to rolling commits.json")
    parser.add_argument("--by-blob-prefix", default="by-blob", help="Path prefix for snapshot HTML")
    args = parser.parse_args()

    vimap = read_vimap(Path(args.vimap))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building manifest for commit {args.commit_sha[:7]} ({len(vimap)} VIs)...")
    manifest = build_manifest(vimap, args.commit_sha, args.by_blob_prefix.strip("/"))

    manifest_file = output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  manifest.json -> {manifest_file}")

    commits_file = Path(args.commits_file)
    commits = update_commits_json(
        commits_file,
        args.commit_sha,
        args.commit_msg,
        args.author,
        args.date,
        len(manifest),
    )
    commits_file.parent.mkdir(parents=True, exist_ok=True)
    commits_file.write_text(json.dumps(commits, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  commits.json  -> {commits_file} ({len(commits)} entries)")


if __name__ == "__main__":
    main()
