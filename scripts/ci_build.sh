#!/usr/bin/env bash
# Build and test one stage of recipes in CI. .github/workflows/release.yml calls this once per
# job; publishing stays in the workflow so the upload is visible where the credentials are.
#
#     ci_build.sh build foundation|ros [RECIPE ...]   # no recipes: the whole directory
#     ci_build.sh test
#
# Environment:
#   PLATFORM  linux-64 or linux-aarch64
#   DISTRO    a ROS distro with a variants-<distro>.yaml; selects isaac-forge/<distro> and
#             robostack-<distro>
#   STRICT    true: failures fail the job (after publishing what passed). false: they are
#             reported as warnings, for a distro or platform that is still being brought up.
#
# Packages that failed their tests are moved to failed-packages/, never published.
set -euo pipefail

: "${PLATFORM:?}" "${DISTRO:?}" "${STRICT:?}"
CHANNELS=(-c ./output -c "https://prefix.dev/isaac-forge/${DISTRO}"
          -c "https://prefix.dev/robostack-${DISTRO}" -c conda-forge)
mkdir -p output failed-packages

fail() {  # kind message
  if [ "${STRICT}" = true ]; then
    echo "::error::$2"
    touch "failed-packages/$1-failed"
  else
    echo "::warning::$2"
  fi
}

build() {
  local stage="$1"; shift
  local args=(--output-dir output --target-platform "${PLATFORM}" -m variants.yaml
              --skip-existing all --test skip "${CHANNELS[@]}")
  if [ "${stage}" = ros ]; then
    args+=(-m "variants-${DISTRO}.yaml")
  fi

  if [ "$#" -eq 0 ]; then
    echo "Building all of recipes/${stage} for ${DISTRO} ${PLATFORM}."
    # Keep independent packages when one recipe fails: the ones that pass are published,
    # so the channel is the cache for the next run and --skip-existing avoids rebuilding.
    pixi run rattler-build build --recipe-dir "recipes/${stage}" --continue-on-failure \
      "${args[@]}" || fail build "Some recipes in recipes/${stage} failed to build."
    return
  fi

  # In the caller's order, so a small dependency chain bootstraps in one run (libv4l
  # before nvv4l2).
  echo "Building $# recipe(s) from recipes/${stage}: $*"
  for name in "$@"; do
    if [[ ! "${name}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || [ ! -f "recipes/${stage}/${name}/recipe.yaml" ]; then
      echo "::error::Recipe does not exist: recipes/${stage}/${name}"
      exit 2
    fi
    pixi run rattler-build build --recipe "recipes/${stage}/${name}/recipe.yaml" "${args[@]}" ||
      fail build "recipes/${stage}/${name} failed to build."
  done
}

# Every package's tests run after the whole stage is built, not inline: a test environment
# needs the package's full run closure, and the build order only follows build dependencies.
# isaac_ros_manipulation_orchestration, for one, needs isaac_ros_test only at test time.
test_all() {
  shopt -s nullglob
  local pkgs=(output/*/*.conda) p
  echo "testing ${#pkgs[@]} package(s)"
  local failed=() passed attempt
  for p in "${pkgs[@]}"; do
    passed=false
    for attempt in 1 2 3; do
      if pixi run rattler-build test --package-file "${p}" "${CHANNELS[@]}"; then
        passed=true
        break
      fi
      echo "::warning::Test attempt ${attempt}/3 failed for $(basename "${p}")"
      [ "${attempt}" -lt 3 ] && sleep $((attempt * 10))
    done
    if [ "${passed}" != true ]; then
      failed+=("$(basename "${p}")")
      # Never publish a package that did not pass. Outside output/, because the publish
      # glob takes every conda subdir.
      mv "${p}" failed-packages/
    fi
  done
  if [ "${#failed[@]}" -gt 0 ]; then
    printf '%s\n' "${failed[@]}" >> failed-packages/packages.txt
    fail test "${#failed[@]} package(s) failed their tests: ${failed[*]}"
  else
    echo "all ${#pkgs[@]} packages passed their tests"
  fi
}

case "${1:-}" in
  build) shift; build "$@" ;;
  test) test_all ;;
  *) echo "usage: $0 build foundation|ros [RECIPE ...] | test" >&2; exit 2 ;;
esac
