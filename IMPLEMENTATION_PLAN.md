# Jazzy + Lyrical from one recipe set

Build every Isaac ROS 5 package for both ROS 2 Jazzy and ROS 2 Lyrical from a single set
of recipes, and publish to `prefix.dev/isaac-forge/jazzy` and `prefix.dev/isaac-forge/lyrical`.
Supersedes wolfv/isaac-forge#3 (`lyrical-build-preview`).

## Decisions

| Topic | Decision |
|---|---|
| Recipes | One distro-neutral recipe per package. `ros_distro` is a variant key; names and deps use `ros-${{ ros_distro }}-...`. Distro differences are `if: ros_distro == ...` selectors. `gen_lyrical.py` is not carried over. |
| Variant files | `variants.yaml` keeps shared pins (CUDA, Boost, protobuf, `tensorrt_flavor`) and **drops `python`**. New `variants-jazzy.yaml` (`ros_distro: jazzy`, `python: 3.12.* *_cpython`) and `variants-lyrical.yaml` (`ros_distro: lyrical`, `python: 3.14.*`). **No `channel_sources`**: channels are passed with `-c`, so distro-neutral packages keep one hash. |
| Layout | `recipes/foundation/` = libdcgm, libv4l, nvv4l2, tensorrt, tensorrt-conda-forge, triton-server, vpi (built once). `recipes/ros/` = every ROS package (directory names without `ros-jazzy-`), plus `tensorrt-python` (it depends on the Python version, so it's built per distro). |
| Foundations | Built once per platform with `-m variants.yaml` only. The same `.conda` goes to both distro channels. |
| CI | `release.yml`, two stages. `foundations` (per platform) → `ros` (platform × distro matrix, `needs: foundations`). Channel order for `ros`: `./output` → `isaac-forge/<distro>` → `robostack-<distro>` → `conda-forge`. |
| Old channel | Stop publishing to the flat `isaac-forge` channel and leave it readable. Fill `isaac-forge/jazzy` with a rebuild (new hashes), not a copy. README points users to the new channels. |
| Lyrical failures | Publish packages that pass, quarantine failures, and report them as **warnings** while Lyrical catches up. A per-distro `strict` flag in the matrix: Jazzy `true`, Lyrical `false`. |
| PR CI | On `pull_request`, build and test only the recipes the PR changed (plus everything if any foundation changed), for both distros and both platforms. No upload and no `id-token` on PRs. Replaces `lyrical-pr.yml`. |
| Missing Lyrical deps | `realsense2-camera-msgs`, `moveit2-tutorials`: upstream PR to RoboStack/ros-lyrical. Until it merges, `skip: ros_distro == "lyrical"` with a link to that PR on the 3 recipes that use them. `tl-expected` → `rcpputils` selector in isaac-deploy-core. |
| flexiv-msgs | In neither RoboStack distro. Removed from isaac-ros-deploy-reference-applications with a `DROP_DEPS` entry in `gen_source.py` (done). Only the Flexiv hardware scripts need it. |
| tensorrt-python | Unchanged deb repack (Jetson, py312). `skip` when python is not 3.12, so Lyrical doesn't build it. Python bindings upstream are a separate follow-up (see below). |
| Publishing auth | `isaac-forge/jazzy` and `isaac-forge/lyrical` already have the `release.yml` trusted publisher configured. |

## Stage 1: Distro-neutral recipes
**Goal**: `gen_source.py` emits `recipes/ros/<name>/` with `ros_distro`; the foundations move to `recipes/foundation/`; the variant files are split as described above.

Dependencies that differ per distro must come out of the generator, not be patched in by hand afterwards:
- Evaluate `package.xml` conditions on `$ROS_DISTRO` (REP 149) for each distro. Where the results differ, emit `if: ros_distro == "..."` selectors. Today `gen_source.py` drops every conditional dependency (`"condition" in attrs: continue`), and isaac_deploy_core's `tl_expected` is put back by hand in `EXTRA_DEPS`. Delete that workaround. Keep ignoring `$ISAAC_ROS_PLATFORM` conditions, which are handled separately.
- Key `EXTRA_DEPS`, `DROP_DEPS` and patch lists by the package name without the distro prefix, with optional per-distro entries.
- Check that `ROS_DISTRO` in the build environment matches the distro being built, so a CMake `$ENV{ROS_DISTRO}` branch takes the right path.
**Success Criteria**:
- `grep -r jazzy recipes/` finds only comments and `if: ros_distro == "jazzy"` selectors.
- Every recipe renders (`--render-only`) for {jazzy, lyrical} × {linux-64, linux-aarch64}, apart from the intended skips.
- For Jazzy, the rendered package names and dependency lists match the pre-refactor recipes exactly. Only the build hash may differ.
**Tests** (`scripts/test_variants.py`, replacing `scripts/test_lyrical.py`):
- Foundation recipes render to the same hash under `variants-jazzy.yaml` and `variants-lyrical.yaml`.
- `recipes/ros/isaac-ros-common` renders as `ros-jazzy-isaac-ros-common` / `ros-lyrical-isaac-ros-common` with no references to the other distro.
- isaac-deploy-core depends on `tl-expected` on Jazzy and `rcpputils` on Lyrical, and that comes from its `package.xml` conditions, not from `EXTRA_DEPS`.
- Generator unit test on a sample `package.xml`: `$ROS_DISTRO` conditions become selectors, and `$ISAAC_ROS_PLATFORM` conditions are dropped.
- A Lyrical build environment has `ROS_DISTRO=lyrical` (check in one recipe's build script or test).
- The Jazzy dependency snapshot matches the old recipes (taken once, before the move).
**Status**: Complete

## Stage 2: Local tooling
**Goal**: `scripts/build_all.sh` and `scripts/test_all.sh` take `--distro jazzy|lyrical` (default jazzy). They pick the matching variant file and channels, and build `recipes/foundation` before `recipes/ros`. Update the pixi tasks and README build docs.
**Success Criteria**: `pixi run build --distro lyrical --recipe vpi` and `--recipe isaac-ros-common` build and test locally on linux-64.
**Tests**: `test_variants.py` is run by a pixi task; build `isaac-ros-common` locally for both distros.
**Status**: In Progress (scripts done and dry-run checked; real linux-64 build pending a Linux machine)

## Stage 3: Two-stage release.yml
**Goal**: The CI layout described above, with PR mode, per-distro `strict`, upload of foundations to both channels and ROS packages to `isaac-forge/<distro>`. Delete `lyrical-pr.yml`. `id-token: write` only on jobs that upload.
**Success Criteria**:
- A PR touching one ROS recipe builds and tests only that recipe in 4 jobs and uploads nothing.
- `workflow_dispatch` with `recipes: vpi,isaac-ros-common` publishes vpi to both channels and `ros-<distro>-isaac-ros-common` to its own channel.
- A deliberate Lyrical test failure produces a warning and the run stays green. The same failure on Jazzy turns it red.
**Tests**: The scenarios above, run on a fork or branch before merging.
**Status**: Not Started

## Stage 4: Upstream and rollout
**Goal**: Publish both distros for real.
- Open a PR on RoboStack/ros-lyrical adding `realsense2-camera-msgs` and `moveit2-tutorials`. Link it from the skips.
- First full `release.yml` run on main fills `isaac-forge/jazzy` and `isaac-forge/lyrical`.
- README: switch the install instructions to `isaac-forge/<distro>` and note that `isaac-forge` is frozen.
- Comment on wolfv/isaac-forge#3 linking the new PR.
**Success Criteria**: Jazzy reaches parity with the old `isaac-forge` channel (same package set). Lyrical failures are listed in the run summary.
**Status**: Not Started

Before landing: invoke the `adversarial-review` skill and follow it.

## Follow-ups (outside this plan)
- TensorRT Python bindings. conda-forge's tensorrt-feedstock ships only the C++ libraries. PyPI has `tensorrt-cu13-bindings` cp314 wheels from 11.1.0.106 onward, which matches x86's conda-forge TRT. Propose adding bindings upstream in conda-forge/tensorrt-feedstock (x86 and SBSA, all Python versions), plus a Jetson source build for Thor 10.13 and Orin 10.16.
- Remove the Lyrical skips once RoboStack ships the missing packages, and turn on `strict` for Lyrical once it reaches parity.
