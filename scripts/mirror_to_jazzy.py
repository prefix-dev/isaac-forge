#!/usr/bin/env python3
"""Copy every package in prefix.dev/isaac-forge to prefix.dev/isaac-forge/jazzy.

Packages are published per ROS distro now (isaac-forge/jazzy, isaac-forge/lyrical). The
Jazzy builds made so far live in the flat isaac-forge channel; this mirrors that channel,
file for file, into isaac-forge/jazzy so Jazzy users can switch channels without losing
anything.

Run it once, locally, with your own prefix.dev credentials:

    pixi auth login prefix.dev --token <token>   # an API key with upload rights
    python scripts/mirror_to_jazzy.py --dry-run  # what would be copied
    python scripts/mirror_to_jazzy.py --limit 5  # try a few first
    python scripts/mirror_to_jazzy.py            # download, verify, upload the rest

Files already in isaac-forge/jazzy are skipped, so an interrupted run can be repeated.
Each file is checked against the sha256 in the source repodata before it is uploaded,
and deleted again once its batch is up, so the run never holds the whole channel
(~20 GB) on disk. Needs rattler-build on PATH (`pixi global install rattler-build`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

SERVER = "https://prefix.dev"
SOURCE = "isaac-forge"
TARGET = "isaac-forge/jazzy"
SUBDIRS = ("noarch", "linux-64", "linux-aarch64")


def fetch(url: str):
    # prefix.dev refuses urllib's default User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "isaac-forge-mirror"})
    return urllib.request.urlopen(request)


def records(channel: str, subdir: str) -> dict[str, dict]:
    """{filename: record} for one subdir of a channel; empty if it has none."""
    try:
        with fetch(f"{SERVER}/{channel}/{subdir}/repodata.json") as r:
            repodata = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    return {**repodata.get("packages", {}), **repodata.get("packages.conda", {})}


def download(subdir: str, filename: str, record: dict, dest: str) -> None:
    """Download one package and check its sha256 against the source repodata."""
    digest = hashlib.sha256()
    tmp = dest + ".part"
    with fetch(f"{SERVER}/{SOURCE}/{subdir}/{filename}") as r, open(tmp, "wb") as fh:
        while chunk := r.read(1 << 20):
            digest.update(chunk)
            fh.write(chunk)
    if digest.hexdigest() != record["sha256"]:
        os.remove(tmp)
        raise RuntimeError(f"sha256 mismatch for {subdir}/{filename}")
    os.replace(tmp, dest)


def upload(paths: list[str]) -> None:
    subprocess.run(["rattler-build", "upload", "prefix", "--skip-existing",
                    "-c", TARGET, *paths], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="only list what would be copied")
    ap.add_argument("--no-upload", action="store_true",
                    help="download and verify, but do not upload (keeps the files)")
    ap.add_argument("--work-dir", default="output/mirror-jazzy",
                    help="where downloads are kept until uploaded (default: %(default)s)")
    ap.add_argument("--batch", type=int, default=20, help="files per upload call")
    ap.add_argument("--limit", type=int, help="copy at most this many files (to try it out)")
    args = ap.parse_args()

    if not args.dry_run and not args.no_upload and shutil.which("rattler-build") is None:
        sys.exit("rattler-build not found on PATH; `pixi global install rattler-build`")

    todo: list[tuple[str, str, dict]] = []
    for subdir in SUBDIRS:
        source, target = records(SOURCE, subdir), records(TARGET, subdir)
        missing = sorted(set(source) - set(target))
        size = sum(source[f].get("size", 0) for f in missing)
        print(f"{subdir:14s} {len(source):5d} in {SOURCE}, {len(target):5d} in {TARGET}, "
              f"{len(missing):5d} to copy ({size / 1e9:.1f} GB)")
        todo += [(subdir, f, source[f]) for f in missing]

    if args.limit is not None:
        todo = todo[:args.limit]

    if args.dry_run or not todo:
        if args.dry_run:
            for subdir, filename, _ in todo:
                print(f"  {subdir}/{filename}")
        return 0

    for start in range(0, len(todo), args.batch):
        batch = todo[start:start + args.batch]
        paths = []
        for subdir, filename, record in batch:
            dest = os.path.join(args.work_dir, subdir, filename)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not os.path.exists(dest):
                download(subdir, filename, record, dest)
            paths.append(dest)
        done = start + len(batch)
        if args.no_upload:
            print(f"verified {done}/{len(todo)}")
            continue
        upload(paths)
        for path in paths:
            os.remove(path)
        print(f"uploaded {done}/{len(todo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
