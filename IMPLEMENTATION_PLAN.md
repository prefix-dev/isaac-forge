# Examples

A set of runnable examples under `examples/<name>/`, each its own Pixi workspace. Every
example must work on ROS 2 Lyrical (Isaac ROS 5.0, `isaac-forge/lyrical`, the default
environment) and should also work on Jazzy (Isaac ROS 4.6, the flat `isaac-forge` channel,
`pixi run -e jazzy ...`) where 4.6 has the packages.

## Decisions

| Topic | Decision |
|---|---|
| Layout | `examples/<name>/` with its own `pixi.toml`, `pixi.lock`, README and scripts, so one can be copied out on its own. |
| Distros | Features `lyrical` and `jazzy` carry the channels, Python and `ros-<distro>-*` deps; `default = ["lyrical"]`, `jazzy = ["jazzy"]`. Shared Python deps sit in `[dependencies]`. |
| Hardware | An NVIDIA GPU only. Inputs are sample images, sample rosbags, or an optional webcam; no RealSense, ZED or robot. |
| Data | Downloaded on first use into `.cache/`, pinned by URL and SHA-256. |
| Visualization | Rerun, with `--no-viewer` writing a `.rrd` for headless machines. |
| Checks | Each example has a `check` task that needs no GPU: packages resolve and the nodes are registered. |
| Blocked on Lyrical | cuVSLAM, nvblox, cuMotion examples, deploy and teleop are skipped on Lyrical (`SKIP` in `scripts/gen_source.py`); their examples wait. |

## Stage 1: yolov8 on Lyrical and Jazzy
**Goal**: Move `yolo/` to `examples/yolov8/` with `lyrical` (default) and `jazzy` environments.
**Success Criteria**: `pixi lock` solves both environments on linux-64 and linux-aarch64; `pixi run check` and `pixi run demo` detect objects in `bus.jpg` on a GPU machine for both environments.
**Tests**: `check` + `demo --no-viewer` on Brev `isaac-ros-builder` (L40S).
**Status**: In Progress (Jazzy solves on both platforms; Lyrical waits for the first release to fill `isaac-forge/lyrical`)

## Stage 2: apriltag
**Goal**: `examples/apriltag/`: a sample image or webcam through cuAprilTags, tag poses in Rerun. No model download.
**Success Criteria**: the demo prints the poses of the tags in the sample image on both environments.
**Tests**: as Stage 1.
**Status**: Not Started

## Stage 3: benchmark
**Goal**: `examples/benchmark/`: `pixi run benchmark` runs ros2_benchmark on an r2b sample rosbag and prints throughput and latency, for comparing x86 and Jetson.
**Success Criteria**: a results table for at least the image-proc and apriltag graphs.
**Tests**: as Stage 1.
**Status**: Not Started

## Stage 4: CI for the examples
**Goal**: A workflow job that locks each example (`pixi lock --check` against the committed lock) and runs `pixi run check` for both environments on linux-64 and linux-aarch64 runners (no GPU).
**Success Criteria**: an example whose packages disappear from a channel fails CI.
**Status**: Not Started

## Stage 5: stereo depth and your own node
**Goal**: `examples/stereo-depth/` (ESS from a sample stereo rosbag to a point cloud in Rerun) and `examples/custom-node/` (a C++ package built with `pixi-build-ros` that consumes Isaac ROS output).
**Status**: Not Started

Later, once the Lyrical skips are fixed: cuVSLAM + nvblox mapping, cuMotion with MoveIt, open-vocabulary detection (Grounding DINO + SAM2).

## Follow-ups (outside this plan)
- First full `release.yml` run on main fills `isaac-forge/lyrical`; check the aarch64 job.
- Lyrical skips still to fix: realtime_tools API (isaac-ros-cumotion-controllers, isaac-ros-deploy-ros2-control), the missing cuvslam submodule, nvblox-ros with nvcc 13.4, libdcgm on aarch64 (no tclap), isaac-teleop-core (waits for conda-forge to index dex-retargeting 0.5.0 build 1).
- Open a PR on RoboStack/ros-lyrical adding `realsense2-camera-msgs` and `moveit2-tutorials`.
- Open the IsaacCapture PRs from `ruben-arts/IsaacCapture`.
- Comment on wolfv/isaac-forge#3 linking wolfv/isaac-forge#4.
- Propose the ament_target_dependencies() patches upstream (NVIDIA repos, see upstream/README.md).
- TensorRT Python bindings for CPython 3.14 in conda-forge/tensorrt-feedstock.
- `scripts/gen_repack.py` still writes `ros-jazzy-*` repack recipes into the flat `recipes/`.
