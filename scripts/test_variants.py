#!/usr/bin/env python3
"""Check that the recipes produce the intended packages for every ROS distro.

Renders only, so it needs rattler-build but no network solve and no build:

    python scripts/test_variants.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_source import DISTROS, SKIP, deps_of, distros_of, recipe_dir  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def render(recipe_dir_: str, platform: str, *variant_files: str) -> list[dict]:
    args = ["rattler-build", "build", "--recipe-dir", recipe_dir_, "--render-only",
            "--target-platform", platform, "-c", "conda-forge"]
    for v in ("variants.yaml", *variant_files):
        args += ["-m", v]
    out = subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def by_name(outputs: list[dict]) -> dict[str, dict]:
    return {o["recipe"]["package"]["name"]: o["recipe"] for o in outputs}


def test_conditions() -> None:
    assert distros_of("") == DISTROS
    assert distros_of(' condition="$ROS_DISTRO == \'lyrical\'"') == ("lyrical",)
    assert distros_of(' condition="$ROS_DISTRO != \'lyrical\'"') == ()
    assert distros_of(' condition="$ROS_DISTRO == jazzy"') == ()
    # Platform conditions are handled elsewhere and stay dropped.
    assert distros_of(' condition="$ISAAC_ROS_PLATFORM == amd64"') == ()

    pkgxml = """
      <depend>rclcpp</depend>
      <depend condition="$ROS_DISTRO != 'lyrical'">tl_expected</depend>
      <depend condition="$ROS_DISTRO == 'lyrical'">rcpputils</depend>
      <build_depend condition="$ISAAC_ROS_PLATFORM == arm64-fastos">cuda-toolkit-13-0</build_depend>
    """
    deps = deps_of(pkgxml, "ros-${{ ros_distro }}-probe")
    assert deps == ["ros-${{ ros_distro }}-rclcpp", "ros-${{ ros_distro }}-rcpputils"], deps


def test_foundation() -> None:
    # Built with variants.yaml alone, so a foundation recipe must not depend on anything
    # a distro file sets.
    for platform in ("linux-64", "linux-aarch64"):
        for o in render("recipes/foundation", platform):
            name = o["recipe"]["package"]["name"]
            variant = o["build_configuration"]["variant"]
            assert not name.startswith("ros-"), name
            assert "ros_distro" not in variant and "python" not in variant, (name, variant)


def test_ros(platform: str) -> None:
    for distro in DISTROS:
        recipes = by_name(render("recipes/ros", platform, f"variants-{distro}.yaml"))
        for name, recipe in recipes.items():
            assert name.startswith(f"ros-{distro}-"), name
            reqs = json.dumps(recipe["requirements"])
            assert "ros-${{" not in reqs and "ros-jazzy-" not in reqs, (distro, name)

        # Skipped recipes are absent from the render.
        for name, reasons in SKIP.items():
            rendered = f"ros-{distro}-{recipe_dir(name)}"
            assert (rendered in recipes) == (distro not in reasons), (distro, rendered)

        # From isaac_deploy_core's package.xml conditions, not a hand-written entry.
        core = recipes[f"ros-{distro}-isaac-deploy-core"]
        assert f"ros-{distro}-rcpputils" in core["requirements"]["host"], core["requirements"]
        assert 'export ROS_DISTRO="${{ ros_distro }}"' in core["build"]["script"]


def main() -> None:
    test_conditions()
    test_foundation()
    for platform in ("linux-64", "linux-aarch64"):
        test_ros(platform)
    print("recipes render correctly for", ", ".join(DISTROS))


if __name__ == "__main__":
    main()
