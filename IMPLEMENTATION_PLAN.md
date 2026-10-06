# Examples

A set of runnable examples under `examples/<name>/`, each its own Pixi workspace. Every
example must work on ROS 2 Lyrical (Isaac ROS 5.0, `isaac-forge/lyrical`, the default
environment) and should also work on Jazzy (Isaac ROS 4.6, `isaac-forge/jazzy`,
`pixi run -e jazzy ...`) where 4.6 has the packages.

## Decisions

| Topic | Decision |
|---|---|
| Layout | `examples/<name>/` with its own `pixi.toml`, `pixi.lock`, README and scripts, so one can be copied out on its own. |
| Distros | Inline environments `[environments.default]` (Lyrical) and `[environments.jazzy]` carry the channel (`isaac-forge/<distro>`, which also serves its RoboStack), Python and `ros-<distro>-*` deps. Shared Python deps sit in `[dependencies]`. |
| Hardware | An NVIDIA GPU only. Inputs are sample images, sample rosbags, or an optional webcam; no RealSense, ZED or robot. |
| Data | Downloaded on first use into `.cache/`, pinned by URL and SHA-256. |
| Visualization | Rerun, with `--no-viewer` writing a `.rrd` for headless machines. |
| Checks | Each example has a `check` task that needs no GPU: packages resolve and the nodes are registered. |
| Blocked on Lyrical | cuVSLAM, nvblox, cuMotion examples, deploy and teleop are skipped on Lyrical (`SKIP` in `scripts/gen_source.py`); their examples wait. |

## Stage 1: yolov8 on Lyrical and Jazzy
**Goal**: Move `yolo/` to `examples/yolov8/` with a default (Lyrical) and a `jazzy` environment.
**Success Criteria**: `pixi lock` solves both environments on linux-64 and linux-aarch64; `pixi run check` and `pixi run demo` detect objects in `bus.jpg` on a GPU machine for both environments.
**Tests**: `check` + `demo --no-viewer` on Brev `isaac-ros-builder` (L40S).
**Status**: Complete (both environments pass on Brev against the published channels)

## Stage 1b: find-anything
**Goal**: `examples/find-anything/`: open-vocabulary detection with Grounding DINO on a sample photo or a live stream, with prompts typed while it runs.
**Success Criteria**: finds the cats, remote controls and couch in the COCO sample on both environments from a cold start (engine build included); a typed prompt change takes effect on a stream.
**Tests**: on Brev: Lyrical (with packages from prefix-dev/isaac-forge#9) and Jazzy photo demos from a cold start; Lyrical traffic video switching from "person" to "bicycle, car".
**Status**: Complete (both environments pass on Brev against the published channels)

## Stage 3: benchmark
**Goal**: `examples/benchmark/`: `pixi run benchmark` runs ros2_benchmark on an r2b sample rosbag and prints throughput and latency, for comparing x86 and Jetson.
**Success Criteria**: a results table for at least the image-proc and YOLOv8 graphs.
**Tests**: as Stage 1.
**Status**: Not Started

## Stage 4: CI for the examples
**Goal**: A workflow job that locks each example (`pixi lock --check` against the committed lock) and runs `pixi run check` for both environments on linux-64 and linux-aarch64 runners (no GPU).
**Success Criteria**: an example whose packages disappear from a channel fails CI.
**Status**: Not Started

## Stage 5: stereo depth and your own node
**Goal**: `examples/stereo-depth/` (ESS from a sample stereo rosbag to a point cloud in Rerun) and `examples/custom-node/` (a C++ package built with `pixi-build-ros` that consumes Isaac ROS output).
**Status**: Not Started

Later: SAM2 masks for find-anything; once the Lyrical skips are fixed, cuVSLAM + nvblox mapping and cuMotion with MoveIt.

## Follow-ups (outside this plan)
- Undeclared runtime dependencies in ~15 packages, found by auditing their Python and launch files against their run closure (isaac_ros_examples for every `*_core.launch.py`, onnx for the ESS model install, cv_bridge for semantic_label_conversion, ...). Add them via EXTRA_RUN and make the audit part of `pixi run render`.
- Make `isaac-forge/<distro>`'s CEP-42 relation `overrides: robostack-<distro>` instead of `base`, so our builds win where names overlap (Jazzy's negotiated and topic_based_ros2_control) and an explicit conda-forge after the channel no longer warns.
- Report to NVIDIA: TensorRTNode's 64 MiB default workspace is too small for Grounding DINO's engine build, and the Grounding DINO preprocessor's one-shot default-prompt handoff races the decoder on a first run.
- Lyrical skips still to fix: realtime_tools API (isaac-ros-cumotion-controllers, isaac-ros-deploy-ros2-control), the missing cuvslam submodule, nvblox-ros with nvcc 13.4, libdcgm on aarch64 (no tclap), isaac-teleop-core (waits for conda-forge to index dex-retargeting 0.5.0 build 1).
- Open a PR on RoboStack/ros-lyrical adding `realsense2-camera-msgs` and `moveit2-tutorials`.
- Open the IsaacCapture PRs from `ruben-arts/IsaacCapture`.
- Comment on prefix-dev/isaac-forge#3 linking prefix-dev/isaac-forge#4.
- Propose the ament_target_dependencies() patches upstream (NVIDIA repos, see upstream/README.md).
- TensorRT Python bindings for CPython 3.14 in conda-forge/tensorrt-feedstock.
- `scripts/gen_repack.py` still writes `ros-jazzy-*` repack recipes into the flat `recipes/`.
