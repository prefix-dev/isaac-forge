#!/usr/bin/env python3
"""Fail when a changed recipe would produce a package file the channel already has.

The release builds with `--skip-existing all`, which compares file names. A package's
build hash covers only the variant keys it uses, so a recipe change that touches anything
else -- a new run dependency, a patch, a script fix -- keeps the old file name, and the
release silently skips it. Run on a pull request for the recipes it changes; a hit means
the recipe needs a new build number (BUILD_NUMBERS in scripts/gen_source.py).

    check_new_builds.py --platform linux-64 --distro lyrical --stage ros RECIPE_DIR...
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request


def channel_files(distro: str, subdir: str) -> set[str]:
    url = f"https://prefix.dev/isaac-forge/{distro}/{subdir}/repodata.json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "isaac-forge-ci"})) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise
    removed = set(d.get("removed", []))
    return {f for f in (*d.get("packages", {}), *d.get("packages.conda", {})) if f not in removed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True)
    ap.add_argument("--distro", required=True)
    ap.add_argument("--stage", choices=("foundation", "ros"), required=True)
    ap.add_argument("recipes", nargs="+")
    args = ap.parse_args()

    cmd = ["rattler-build", "build", "--render-only", "--target-platform", args.platform,
           "-m", "variants.yaml", "-c", "conda-forge"]
    if args.stage == "ros":
        cmd += ["-m", f"variants-{args.distro}.yaml"]
    for recipe in args.recipes:
        cmd += ["--recipe", recipe]
    outputs = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)

    existing: dict[str, set[str]] = {}
    stale = []
    for o in outputs:
        recipe = o["recipe"]
        if recipe["build"].get("skip"):
            continue
        subdir = "noarch" if recipe["build"].get("noarch") else args.platform
        if subdir not in existing:
            existing[subdir] = channel_files(args.distro, subdir)
        package = recipe["package"]
        filename = f"{package['name']}-{package['version']}-{recipe['build']['string']}.conda"
        if filename in existing[subdir]:
            stale.append(f"{subdir}/{filename}")

    if stale:
        print(f"::error::These packages already exist in isaac-forge/{args.distro}, so the "
              "release would skip them and never publish this change. Bump their build "
              "number (BUILD_NUMBERS in scripts/gen_source.py, or build.number for a "
              "foundation recipe):")
        for f in stale:
            print(f"  {f}")
        return 1
    print(f"all {len(outputs)} output(s) of the changed recipes are new to isaac-forge/{args.distro}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
