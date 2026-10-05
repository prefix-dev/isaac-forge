#!/usr/bin/env python3
"""Copy every package in prefix.dev/isaac-forge to prefix.dev/isaac-forge/jazzy.

Packages are published per ROS distro now (isaac-forge/jazzy, isaac-forge/lyrical). The
Jazzy builds made so far live in the flat isaac-forge channel; this copies all of them --
every variant of every package, on every platform -- into isaac-forge/jazzy so Jazzy users
can switch channels without losing anything.

The copy runs on prefix.dev itself (`pixi-pfx package copy-from-channel`), so nothing is
downloaded or re-uploaded. This script only collects the package names from the source
channel's repodata and starts the job. Run it once, locally, with credentials that can
write to isaac-forge/jazzy:

    export PREFIX_DEV_API_TOKEN=<token>          # or pass --token; `pixi-pfx auth status`
    python scripts/mirror_to_jazzy.py --dry-run  # list the files it would copy
    python scripts/mirror_to_jazzy.py            # start the copy and wait for it

Needs pixi-pfx on PATH (`pixi global install pixi-pfx`). If the wait times out, the job
keeps running on the server; `pixi-pfx package active-copy isaac-forge/jazzy` shows it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request

SOURCE = "isaac-forge"
TARGET = "isaac-forge/jazzy"
SUBDIRS = ("noarch", "linux-64", "linux-aarch64")


def package_names() -> list[str]:
    """Every package name in the source channel, across all subdirs."""
    names: set[str] = set()
    for subdir in SUBDIRS:
        # prefix.dev refuses urllib's default User-Agent.
        request = urllib.request.Request(
            f"https://prefix.dev/{SOURCE}/{subdir}/repodata.json",
            headers={"User-Agent": "isaac-forge-mirror"})
        with urllib.request.urlopen(request) as r:
            repodata = json.load(r)
        records = {**repodata.get("packages", {}), **repodata.get("packages.conda", {})}
        names |= {record["name"] for record in records.values()}
    return sorted(names)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve and list the files without starting the copy")
    ap.add_argument("--timeout", type=int, default=3600,
                    help="seconds to wait for the copy job (default: %(default)s)")
    args = ap.parse_args()

    if shutil.which("pixi-pfx") is None:
        sys.exit("pixi-pfx not found on PATH; `pixi global install pixi-pfx`")

    names = package_names()
    print(f"{len(names)} packages in {SOURCE} to copy to {TARGET}", flush=True)
    command = ["pixi-pfx", "package", "copy-from-channel", TARGET, SOURCE, *names]
    if args.dry_run:
        command.append("--dry-run")
    else:
        command += ["--wait", "--timeout", str(args.timeout)]
    return subprocess.run(command).returncode


if __name__ == "__main__":
    sys.exit(main())
