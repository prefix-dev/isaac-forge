#!/usr/bin/env bash
# Rebuild every recipe into ./output, which is the local channel everything resolves against.
#
# This existed only inside .github/workflows/release.yml, and that cost a day: when output/
# was lost between sessions there was no command in the repo that would rebuild it, and the
# `layer0` pixi task -- the obvious candidate -- passes no channels, so it cannot resolve
# ros-jazzy-isaac-ros-common and fails on the second recipe it reaches.
#
#     ./scripts/build_all.sh                         # Lyrical, native platform, resumable
#     ./scripts/build_all.sh --distro <distro>       # another variants-<distro>.yaml
#     ./scripts/build_all.sh --target linux-aarch64  # explicit ARM64 target
#     ./scripts/build_all.sh --recipe vpi             # build one recipe
#     ./scripts/build_all.sh --fresh                   # discard output first
#
# recipes/foundation is built first, with variants.yaml alone: those packages do not depend
# on the ROS distro. recipes/ros follows with variants-<distro>.yaml on top. Several
# distros can share output/: every ROS package name carries its distro.
#
# Three flags carry the design, and each was learned the hard way:
#
#   --test skip           Tests are skipped *during* the build and run afterwards by
#                         scripts/test_all.sh. A package's tests resolve its own run
#                         dependencies, and early in a from-scratch build those siblings do
#                         not exist yet -- so testing inline makes build order matter for
#                         reasons unrelated to compiling. Deferring removes the question.
#   --skip-existing local Makes the whole thing resumable. Nothing is rebuilt if its .conda
#                         is already in output/, so an interrupted run continues where it
#                         stopped and a second pass picks up newly added recipes.
#   --continue-on-failure One bad recipe does not stop the other 200. Without it a single
#                         failure ends the run, and with ~200 recipes that turns one problem
#                         into one problem per invocation.
#
# Build trees are pruned as packages land. rattler-build keeps output/bld/<pkg>_<stamp>/ for
# every build, and across the full set that is roughly 55 GB against ~6 GB of actual
# packages. Pruning as we go keeps the peak near the latter.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

case "$(uname -m)" in
  x86_64) NATIVE_PLATFORM=linux-64 ;;
  aarch64|arm64) NATIVE_PLATFORM=linux-aarch64 ;;
  *) echo "unsupported build architecture: $(uname -m)" >&2; exit 2 ;;
esac

TARGET_PLATFORM="${ISAAC_FORGE_TARGET_PLATFORM:-${NATIVE_PLATFORM}}"
DISTRO="${ISAAC_FORGE_DISTRO:-lyrical}"
FRESH=false
STAGES=(foundation ros)
RECIPE=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fresh) FRESH=true; shift ;;
    --target)
      [ "$#" -ge 2 ] || { echo "--target requires linux-64 or linux-aarch64" >&2; exit 2; }
      TARGET_PLATFORM="$2"; shift 2 ;;
    --distro)
      [ "$#" -ge 2 ] || { echo "--distro requires a name with a variants-<distro>.yaml" >&2; exit 2; }
      DISTRO="$2"; shift 2 ;;
    --recipe)
      [ "$#" -ge 2 ] || { echo "--recipe requires a recipe directory name" >&2; exit 2; }
      [[ "$2" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || { echo "invalid recipe name: $2" >&2; exit 2; }
      if [ -f "recipes/foundation/$2/recipe.yaml" ]; then STAGES=(foundation)
      elif [ -f "recipes/ros/$2/recipe.yaml" ]; then STAGES=(ros)
      else echo "recipe not found: recipes/{foundation,ros}/$2/recipe.yaml" >&2; exit 2
      fi
      RECIPE="$2"; shift 2 ;;
    -h|--help)
      echo "usage: $0 [--fresh] [--distro lyrical] [--target linux-64|linux-aarch64] [--recipe NAME]"
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "${TARGET_PLATFORM}" in
  linux-64|linux-aarch64) ;;
  *) echo "unsupported target platform: ${TARGET_PLATFORM}" >&2; exit 2 ;;
esac
[ -f "variants-${DISTRO}.yaml" ] || { echo "unknown distro: ${DISTRO}" >&2; exit 2; }

if [ "${FRESH}" = true ]; then
  echo "removing output/ and starting over"
  rm -rf output
fi
mkdir -p output

echo "building ${DISTRO} for ${TARGET_PLATFORM} on ${NATIVE_PLATFORM}"
if [ "${TARGET_PLATFORM}" != "${NATIVE_PLATFORM}" ]; then
  echo "warning: CUDA recipes are intended for native builds; cross-builds are useful for rendering/auditing only" >&2
fi

# robostack-<distro> and conda-forge come in through the channel's CEP-42 relations; see
# scripts/ci_build.sh.
CHANNELS=(-c ./output -c "https://prefix.dev/isaac-forge/${DISTRO}")

# The recipes and variant files one stage builds with.
stage_args() {
  local stage="$1"
  if [ -n "${RECIPE}" ]; then
    printf '%s ' --recipe "recipes/${stage}/${RECIPE}/recipe.yaml"
  else
    printf '%s ' --recipe-dir "recipes/${stage}"
  fi
  printf '%s ' -m variants.yaml
  if [ "${stage}" = ros ]; then
    printf '%s ' -m "variants-${DISTRO}.yaml"
  fi
}

prune_finished() {
  local freed=0
  for d in output/bld/rattler-build_*; do
    [ -d "${d}" ] || continue
    # output/bld/rattler-build_<pkg-name>_<10-digit-stamp>
    local pkg
    pkg="$(basename "${d}" | sed 's/^rattler-build_//; s/_[0-9]\{10\}$//')"
    if compgen -G "output/${TARGET_PLATFORM}/${pkg}-[0-9]*.conda" >/dev/null ||
       compgen -G "output/noarch/${pkg}-[0-9]*.conda" >/dev/null; then
      rm -rf "${d}" && freed=$((freed + 1))
    fi
  done
  [ "${freed}" -gt 0 ] && echo "  pruned ${freed} finished build trees"
  return 0
}

# Several passes, because a recipe added while an earlier pass was already running is not in
# that pass's plan. Each pass is cheap once the work is done -- --skip-existing local turns
# it into a directory listing -- and the loop stops as soon as a pass adds nothing.
total_before=0
for pass in 1 2 3 4; do
  before=$(find "output/${TARGET_PLATFORM}" output/noarch -maxdepth 1 -name '*.conda' -type f 2>/dev/null | wc -l)
  echo "=== pass ${pass} (${before} packages present) ==="
  : > "output/build-pass${pass}.log"
  for stage in "${STAGES[@]}"; do
    read -r -a args <<< "$(stage_args "${stage}")"
    rattler-build build \
      "${args[@]}" \
      --output-dir output \
      --target-platform "${TARGET_PLATFORM}" \
      --skip-existing local \
      --test skip \
      --continue-on-failure \
      "${CHANNELS[@]}" 2>&1 | tee -a "output/build-pass${pass}.log"
    prune_finished
  done
  after=$(find "output/${TARGET_PLATFORM}" output/noarch -maxdepth 1 -name '*.conda' -type f 2>/dev/null | wc -l)
  echo "=== pass ${pass} finished: ${before} -> ${after} packages ==="
  if [ "${after}" = "${before}" ]; then
    echo "no progress in pass ${pass}; stopping"
    break
  fi
  total_before=${after}
done

echo
built_count=$(find "output/${TARGET_PLATFORM}" output/noarch -maxdepth 1 -name '*.conda' -type f 2>/dev/null | wc -l)
echo "built ${built_count} package artifact(s) for ${TARGET_PLATFORM}"
# One line per recipe that failed, so the summary is readable without opening the logs.
failed=$(cat output/build-pass*.log 2>/dev/null |
  awk '/Running build for recipe:/{r=$NF} /error   Work directory/{print r}' | sort -u)
if [ -n "${failed}" ]; then
  echo "failed:"
  printf '  %s\n' ${failed}
fi
echo "run ./scripts/test_all.sh --distro ${DISTRO} next -- this script skipped every package test"
