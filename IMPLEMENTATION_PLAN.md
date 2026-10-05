# Isaac ROS for Jazzy and Lyrical

Publish Isaac ROS to `prefix.dev/isaac-forge/jazzy` and `prefix.dev/isaac-forge/lyrical`,
each on its own RoboStack. Supersedes wolfv/isaac-forge#3 (`lyrical-build-preview`).

**Change of direction (after Stage 3).** Isaac ROS 5.0's GPU image and tensor pipeline
(`cuda_buffer`, `cvcuda_conversions`, image_proc, tensor_proc and ~45 packages above them)
needs the ROS 2 buffer API: `rosidl_generator_cpp` from Lyrical emits every `uint8[]` field as
`rosidl::Buffer<uint8_t>`. Jazzy's messages do not, and backporting it would fork Jazzy's
message ABI. NVIDIA ships 5.0 for Lyrical only (255 `ros-lyrical-*` debs, no `ros-jazzy-*`).
So **Jazzy stays on Isaac ROS 4.6**, NVIDIA's last Jazzy release, as a frozen copy of the
tested builds in the old `isaac-forge` channel, and **main builds Lyrical 5.0**.

## Decisions

| Topic | Decision |
|---|---|
| Recipes | One distro-neutral recipe per package. `ros_distro` is a variant key; names and deps use `ros-${{ ros_distro }}-...`; `$ROS_DISTRO` conditions in `package.xml` become `if: ros_distro == ...` selectors. Only Lyrical is built today; another distro is a variant file and a matrix entry. |
| Variant files | `variants.yaml` keeps shared pins and **no `python`**. `variants-lyrical.yaml`: `ros_distro: lyrical`, `python: 3.14.*`. No `channel_sources`; channels are passed with `-c`. |
| Layout | `recipes/foundation/` = NVIDIA packages (libdcgm, libv4l, nvv4l2, tensorrt, tensorrt-conda-forge, triton-server, vpi), built with `variants.yaml` alone. `recipes/ros/` = ROS packages, built with the distro file too. |
| Jazzy | Frozen at Isaac ROS 4.6. A manually triggered `release.yml` job copies the 4.6 `ros-jazzy-*` packages and their dependency closure from `isaac-forge` into `isaac-forge/jazzy`, choosing builds with a solver so the result installs. If a 4.6 fix is ever needed, branch from `df4b8e0`. |
| Removed | Jazzy-only pieces that existed to build 5.0 on Jazzy: `variants-jazzy.yaml`, the urdf `model.h` patch, the `rosidl-buffer*` recipes (robostack-lyrical has them), `tensorrt-python` (Jetson CPython 3.12 binding; its 4.6-era builds are in the Jazzy snapshot). |
| CI | `release.yml`: `plan` → `render` + `build` (platform × distro, distro = lyrical). Each build job builds foundations then ROS, tests, and publishes to `isaac-forge/<distro>`. Channels: `./output` → `isaac-forge/<distro>` → `robostack-<distro>` → `conda-forge`. |
| Old channel | Stop publishing to the flat `isaac-forge` channel and leave it readable. README points users to the per-distro channels. |
| Lyrical failures | Publish what passes, quarantine failures, report them as **warnings** (`strict: false` in the matrix) until Lyrical reaches parity. |
| PR CI | On `pull_request`, build and test only the recipes the PR changed; the render job covers everything else. Uploads never run on PRs. |
| Missing Lyrical deps | `realsense2-camera-msgs`, `moveit2-tutorials`: upstream PR to RoboStack/ros-lyrical. Until it merges, the 3 recipes that use them skip Lyrical. |
| flexiv-msgs | In neither RoboStack distro. Dropped from isaac-ros-deploy-reference-applications via `DROP_DEPS` (done). |
| Publishing auth | `isaac-forge/jazzy` and `isaac-forge/lyrical` already have the `release.yml` trusted publisher configured. |

## Stage 1: Distro-neutral recipes
**Goal**: `gen_source.py` emits `recipes/ros/<name>/` with `ros_distro`; foundations move to `recipes/foundation/`; `$ROS_DISTRO` conditions become selectors; build scripts export `ROS_DISTRO` (isaac_deploy_core's CMake branches on it).
**Tests**: `scripts/test_variants.py`.
**Status**: Complete (built for both distros first; Stage 5 removes the Jazzy side)

## Stage 2: Local tooling
**Goal**: `scripts/build_all.sh` / `scripts/test_all.sh` take `--distro` and build `recipes/foundation` before `recipes/ros`; `pixi run render` runs the render test.
**Success Criteria**: a full Lyrical build on linux-64 (Brev `isaac-ros-builder`).
**Status**: In Progress (full Lyrical build running on the builder)

## Stage 3: release.yml
**Goal**: The CI layout above.
**Success Criteria**: a PR touching one ROS recipe builds and tests only that recipe and uploads nothing; a deliberate Lyrical test failure is a warning and the run stays green.
**Tests**: The scenarios above, run on a fork or branch before merging.
**Status**: In Progress (two-stage version written and linted; Stage 5 simplifies it)

## Stage 5: Lyrical-only main, frozen Jazzy 4.6
**Goal**: Remove the Jazzy build path from main, simplify CI to one build job per platform × distro, and add the Jazzy 4.6 snapshot job.
**Success Criteria**:
- `pixi run render` passes for Lyrical on both platforms; `grep -rn jazzy recipes/` finds nothing.
- The snapshot script, run locally in dry-run mode, selects an installable 4.6 set for linux-64 and linux-aarch64 (both TensorRT flavors) and lists anything it had to leave out.
**Tests**: `scripts/test_variants.py`; `scripts/snapshot_jazzy.py --dry-run`.
**Status**: In Progress

## Stage 4: Upstream and rollout
**Goal**: Publish both channels for real.
- Run the Jazzy snapshot job once; check `isaac-forge/jazzy` against the old channel's 4.6 set.
- First full `release.yml` run on main fills `isaac-forge/lyrical`.
- Open a PR on RoboStack/ros-lyrical adding `realsense2-camera-msgs` and `moveit2-tutorials`. Link it from the skips.
- Re-lock `yolo/` against the new channels.
- Comment on wolfv/isaac-forge#3 linking the new PR.
**Status**: Not Started

Before landing: invoke the `adversarial-review` skill and follow it.

## Follow-ups (outside this plan)
- Jazzy 5.0 failures found on the way, relevant only if Jazzy ever moves past 4.6: `message_filters::Subscriber` API break (topic-tools, realsense-splitter, multi-realsense-emitter-synchronizer), IsaacTeleop tarball sha256 drift (isaac-teleop-core).
- TensorRT Python bindings for Lyrical (CPython 3.14). conda-forge's tensorrt-feedstock ships only the C++ libraries; PyPI has cp314 `tensorrt-cu13-bindings` from 11.1.0.106 onward, matching x86's conda-forge TRT. Propose bindings upstream in conda-forge/tensorrt-feedstock, plus a Jetson source build.
- Remove the Lyrical skips once RoboStack ships the missing packages; turn on `strict` for Lyrical at parity.
- `scripts/gen_repack.py` still writes `ros-jazzy-*` repack recipes into the flat `recipes/`; no ROS recipe uses it any more.
