#!/usr/bin/env python3
"""Copy the Isaac ROS 4.6 Jazzy release from the old isaac-forge channel to isaac-forge/jazzy.

Isaac ROS 5.0 needs the ROS 2 buffer API that Jazzy's messages lack, and NVIDIA ships 5.0
for Lyrical only, so Jazzy stays on 4.6, NVIDIA's last Jazzy release. Those packages were
built and tested by this repository before the 5.0 upgrade (recipes at df4b8e0) and sit in
https://prefix.dev/isaac-forge next to 4.5 and some 5.0 builds. This picks the 4.6 set and
copies it, rather than rebuilding from old recipes against today's robostack-jazzy.

The set is chosen by solving, the way a user's environment would be: each 4.6 ros-jazzy-*
package against isaac-forge, robostack-jazzy and conda-forge (strict priority), with every
ros-jazzy-* package from isaac-forge held below 5. Whatever the solutions take from
isaac-forge -- the 4.6 packages, their 4.6-era NVIDIA packages and other dependencies --
is copied. linux-aarch64 is solved for Orin (SM 8.7) and Thor (SM 11.0), since TensorRT
has a build for each. A package that no longer solves is reported and left out.

    python scripts/snapshot_jazzy.py --dry-run       # list what would be copied
    python scripts/snapshot_jazzy.py --download DIR  # download it, for upload to isaac-forge/jazzy
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request

from rattler import (
    Channel,
    Gateway,
    GenericVirtualPackage,
    MatchSpec,
    PackageName,
    Version,
    solve,
)

OLD = "https://prefix.dev/isaac-forge"
CHANNELS = [OLD, "https://prefix.dev/robostack-jazzy", "conda-forge"]
VERSION = "4.6.0"


def virtual(subdir: str, cuda_arch: str | None) -> list[GenericVirtualPackage]:
    """A typical target machine: Ubuntu 24.04, CUDA 13, and on x86 an x86-64-v3 CPU (some
    conda-forge builds, e.g. libblasfeo under pinocchio, need v3)."""
    pkgs = [("__unix", "0", "0"), ("__linux", "6.8", "0"), ("__glibc", "2.38", "0"),
            ("__cuda", "13.0", "0")]
    pkgs.append(("__archspec", "1", "x86_64_v3" if subdir == "linux-64" else "aarch64"))
    if cuda_arch:
        pkgs.append(("__cuda_arch", cuda_arch, "0"))
    return [GenericVirtualPackage(PackageName(n), Version(v), b) for n, v, b in pkgs]


# (subdir, label, __cuda_arch)
TARGETS = [("linux-64", "linux-64", None),
           ("linux-aarch64", "linux-aarch64 Orin", "8.7"),
           ("linux-aarch64", "linux-aarch64 Thor", "11.0")]


def fetch(url: str):
    # prefix.dev refuses urllib's default User-Agent.
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "isaac-forge"}))


def old_records(subdir: str) -> list[dict]:
    with fetch(f"{OLD}/{subdir}/repodata.json") as r:
        repodata = json.load(r)
    return list({**repodata.get("packages", {}), **repodata.get("packages.conda", {})}.values())


async def select(subdir: str, cuda_arch: str | None, records: list[dict],
                 gateway: Gateway) -> tuple[list[str], dict[str, str], list[str]]:
    """The release's names, {filename: url} taken from the old channel, and the names
    that did not solve."""
    names = sorted({m["name"] for m in records
                    if m["name"].startswith("ros-jazzy-") and m["version"] == VERSION})
    # Every ros-jazzy-* package the old channel has, held to the 4.x line.
    constraints = [f"{n} <5" for n in sorted({m["name"] for m in records
                                              if m["name"].startswith("ros-jazzy-")})]
    kwargs = dict(sources=[Channel(c) for c in CHANNELS], gateway=gateway,
                  platforms=[subdir, "noarch"], virtual_packages=virtual(subdir, cuda_arch),
                  constraints=constraints)

    async def solve_specs(specs: list[str]):
        return await solve(specs=[MatchSpec(s) for s in specs], **kwargs)

    picked: dict[str, str] = {}
    failed: list[str] = []

    def take(records) -> None:
        for rec in records:
            if str(rec.channel).rstrip("/").endswith("isaac-forge"):
                picked[rec.file_name] = str(rec.url)

    # One solve for the whole release when it is consistent; otherwise one per package,
    # so a single broken package costs only itself.
    try:
        take(await solve_specs([f"{n} =={VERSION}" for n in names]))
        return names, picked, failed
    except Exception:  # noqa: BLE001 -- any solver error means "solve individually"
        pass
    for n in names:
        try:
            take(await solve_specs([f"{n} =={VERSION}"]))
        except Exception as e:  # noqa: BLE001
            failed.append(n)
            print(f"  cannot solve {n}: {str(e).splitlines()[0][:160]}", file=sys.stderr)
    return names, picked, failed


async def main_async(args: argparse.Namespace) -> int:
    gateway = Gateway()
    files: dict[str, str] = {}
    records = {subdir: old_records(subdir) for subdir in {t[0] for t in TARGETS}}
    for subdir, label, arch in TARGETS:
        names, picked, failed = await select(subdir, arch, records[subdir], gateway)
        ros = sum(f.startswith("ros-jazzy-") for f in picked)
        print(f"{label}: {len(names)} {VERSION} packages, {len(names) - len(failed)} solve; "
              f"copying {len(picked)} files ({ros} ros-jazzy-*, {len(picked) - ros} other)")
        for n in failed:
            print(f"  left out: {n}")
        for fn, url in picked.items():
            files[f"{url.rsplit('/', 2)[-2]}/{fn}"] = url

    print(f"\n{len(files)} files in total")
    if args.dry_run:
        for path in sorted(files):
            print(f"  {path}")
        return 0

    for path, url in sorted(files.items()):
        dest = os.path.join(args.download, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not os.path.exists(dest):
            with fetch(url) as r, open(dest, "wb") as fh:
                fh.write(r.read())
    print(f"downloaded to {args.download}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="only list what would be copied")
    mode.add_argument("--download", metavar="DIR", help="download the selected packages here")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
