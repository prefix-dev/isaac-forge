#!/usr/bin/env python3
"""Find anything you can describe: open-vocabulary detection with Isaac ROS Grounding DINO."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
import rerun as rr
from sensor_msgs.msg import CameraInfo, Image
from vision_msgs.msg import Detection2DArray

from isaac_ros_grounding_dino_interfaces.srv import SetPrompt, SyncDataWithDecoder

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
MODEL = CACHE / "grounding_dino_swin_tiny.onnx"
ENGINE = CACHE / "grounding_dino_swin_tiny.plan"
SAMPLE = CACHE / "cats.jpg"
RESULT_IMAGE = CACHE / "find_anything_result.png"
RECORDING = CACHE / "find_anything.rrd"

# NVIDIA TAO Grounding DINO, Swin-Tiny, commercial deployable v1.0 (NVIDIA Open Model License;
# see https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/grounding_dino).
MODEL_URL = (
    "https://api.ngc.nvidia.com/v2/models/nvidia/tao/grounding_dino/versions/"
    "grounding_dino_swin_tiny_commercial_deployable_v1.0/files/"
    "grounding_dino_swin_tiny_commercial_deployable.onnx"
)
MODEL_SHA256 = "6895acdc6b588e923f753e37b3bd18869e064256e5ecc1b2b9853e8c51125f94"
# COCO val2017 #39769: two cats on a couch with two remote controls (CC BY 4.0).
SAMPLE_URL = "http://images.cocodataset.org/val2017/000000039769.jpg"
SAMPLE_SHA256 = "dea9e7ef97386345f7cff32f9055da4982da5471c48d575146c796ab4563b04e"
SAMPLE_PROMPT = "cat, remote control, couch"

# The network input; see find_anything.launch.py.
NETWORK_WIDTH, NETWORK_HEIGHT = 960, 544


def download(url: str, path: Path, expected_sha256: str) -> None:
    """Download an asset once and reject incomplete or changed content."""
    if path.exists() and sha256(path) == expected_sha256:
        return
    temporary = path.with_suffix(path.suffix + ".download")
    print(f"Downloading {url}\n       -> {path}")
    try:
        with urllib.request.urlopen(url) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        digest = sha256(temporary)
        if digest != expected_sha256:
            raise RuntimeError(
                f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, got {digest}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def to_prompt(text: str) -> str:
    """'cat, remote control' -> 'cat.remote control.', the phrase format Grounding DINO expects."""
    phrases = [p.strip() for p in text.replace(".", ",").split(",") if p.strip()]
    return "".join(f"{p}." for p in phrases)


class Finder(Node):
    def __init__(self) -> None:
        super().__init__("isaac_forge_find_anything")
        self.latest: Detection2DArray | None = None
        self.image_pub = self.create_publisher(Image, "/image_rect", 10)
        self.info_pub = self.create_publisher(CameraInfo, "/camera_info_rect", 10)
        self.create_subscription(Detection2DArray, "/detections_output", self._detected, 10)
        self.set_prompt_client = self.create_client(SetPrompt, "/set_prompt")
        # Only used to see when the decoder is up; see wait_and_set_prompt().
        self.decoder_client = self.create_client(SyncDataWithDecoder, "/sync_data_with_decoder")

    def _detected(self, message: Detection2DArray) -> None:
        self.latest = message

    def publish(self, rgb: np.ndarray) -> None:
        height, width = rgb.shape[:2]
        image = Image()
        image.header.stamp = self.get_clock().now().to_msg()
        image.header.frame_id = "camera"
        image.height, image.width = height, width
        image.encoding = "rgb8"
        image.step = width * 3
        image.data = rgb.tobytes()

        info = CameraInfo()
        info.header = image.header
        info.height, info.width = height, width
        info.distortion_model = "plumb_bob"
        focal, cx, cy = float(width), width / 2.0, height / 2.0
        info.k = [focal, 0.0, cx, 0.0, focal, cy, 0.0, 0.0, 1.0]
        info.p = [focal, 0.0, cx, 0.0, 0.0, focal, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
        self.image_pub.publish(image)
        self.info_pub.publish(info)

    def set_prompt(self, prompt: str) -> None:
        if not self.set_prompt_client.wait_for_service(timeout_sec=5.0):
            print("warning: /set_prompt is not available yet", file=sys.stderr)
            return
        future = self.set_prompt_client.call_async(SetPrompt.Request(prompt=prompt))
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        if future.result() is None or not future.result().success:
            print(f"warning: the pipeline rejected the prompt {prompt!r}", file=sys.stderr)


def boxes(result: Detection2DArray, width: int, height: int):
    """Detections in source-image pixels, as (centers, sizes, labels).

    The graph scales the source to fit 960x544 keeping its aspect ratio and pads the
    bottom right, so dividing by that scale maps network pixels back to the source.
    """
    scale = min(NETWORK_WIDTH / width, NETWORK_HEIGHT / height)
    centers, sizes, labels = [], [], []
    for detection in result.detections:
        if not detection.results:
            continue
        hypothesis = detection.results[0].hypothesis
        center = detection.bbox.center.position
        centers.append([center.x / scale, center.y / scale])
        sizes.append([detection.bbox.size_x / scale, detection.bbox.size_y / scale])
        labels.append(f"{hypothesis.class_id} {hypothesis.score:.2f}")
    return centers, sizes, labels


def annotate(rgb: np.ndarray, centers, sizes, labels) -> np.ndarray:
    out = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    for (cx, cy), (w, h), label in zip(centers, sizes, labels):
        x0, y0, x1, y1 = int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
        cv2.rectangle(out, (x0, y0), (x1, y1), (60, 60, 255), 2)
        cv2.putText(out, label, (x0 + 3, max(12, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (60, 60, 255), 1, cv2.LINE_AA)
    return out


def open_source(source: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video source {source!r}")
    return capture


def read_prompts(prompts: queue.Queue[str]) -> None:
    for line in sys.stdin:
        if line.strip():
            prompts.put(line)


def launch(width: int, height: int, prompt: str, threshold: float) -> subprocess.Popen[bytes]:
    command = [
        "ros2", "launch", str(HERE / "find_anything.launch.py"),
        f"image_width:={width}", f"image_height:={height}",
        f"model_file_path:={MODEL}", f"engine_file_path:={ENGINE}",
        f"default_prompt:={prompt}", f"confidence_threshold:={threshold}",
    ]
    return subprocess.Popen(command, start_new_session=True)


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def wait_and_set_prompt(node: Finder, process, prompt: str) -> bool:
    """Set the prompt once the decoder is up.

    The preprocessor hands its default prompt to the decoder once, at startup, with a short
    timeout. On a first run the decoder loads only after TensorRT has built its engine, so
    that handoff fails and nothing is ever detected. Setting the prompt again once both
    services exist avoids the race.
    """
    print("Waiting for the pipeline. The first run builds a TensorRT engine, "
          "which takes a few minutes...")
    while process.poll() is None:
        if node.decoder_client.service_is_ready() and node.set_prompt_client.service_is_ready():
            node.set_prompt(prompt)
            return True
        rclpy.spin_once(node, timeout_sec=0.5)
    print(f"error: ROS launch exited with {process.returncode}", file=sys.stderr)
    return False


def run_image(node: Finder, process, rgb: np.ndarray, show_viewer: bool) -> int:
    """Publish one image until the first detections arrive; TensorRT builds its engine first."""
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and not (node.latest and node.latest.detections):
        if process.poll() is not None:
            print(f"error: ROS launch exited with {process.returncode}", file=sys.stderr)
            return 1
        node.publish(rgb)
        rclpy.spin_once(node, timeout_sec=0.5)
    if not (node.latest and node.latest.detections):
        print("error: timed out waiting for detections", file=sys.stderr)
        return 1

    height, width = rgb.shape[:2]
    centers, sizes, labels = boxes(node.latest, width, height)
    print(f"\nFound {len(labels)} object(s):")
    for label in labels:
        print(f"  {label}")
    cv2.imwrite(str(RESULT_IMAGE), annotate(rgb, centers, sizes, labels))
    print(f"Annotated image: {RESULT_IMAGE}")
    rr.init("isaac_forge_find_anything", spawn=show_viewer)
    if not show_viewer:
        rr.save(str(RECORDING))
        print(f"Rerun recording: {RECORDING} (open with `rerun {RECORDING}`)")
    rr.log("camera/image", rr.Image(rgb))
    rr.log("camera/image/detections", rr.Boxes2D(centers=centers, sizes=sizes, labels=labels))
    return 0


def run_stream(node: Finder, process, capture, first: np.ndarray, is_file: bool,
               show_viewer: bool, max_frames: int | None) -> int:
    """Stream frames; every line typed on stdin becomes the new prompt."""
    rr.init("isaac_forge_find_anything", spawn=show_viewer)
    if not show_viewer:
        rr.save(str(RECORDING))
        print(f"Recording to {RECORDING}")
    # Hold the first frame until the graph answers, so a video file does not start playing
    # before the first inference.
    while process.poll() is None and node.latest is None:
        node.publish(first)
        rclpy.spin_once(node, timeout_sec=0.5)
    print("Ready. Type something to look for and press Enter, for example: cup, keys, a red shoe")
    prompts: queue.Queue[str] = queue.Queue()
    threading.Thread(target=read_prompts, args=(prompts,), daemon=True).start()

    # Play files at their own rate; a camera paces itself.
    fps = capture.get(cv2.CAP_PROP_FPS) if is_file else 0.0
    period = 1.0 / fps if fps > 0 else 0.0
    rgb, frame, next_frame = first, 0, time.monotonic()
    while process.poll() is None:
        while not prompts.empty():
            prompt = to_prompt(prompts.get())
            if prompt:
                print(f"Looking for: {prompt}")
                node.set_prompt(prompt)
        node.publish(rgb)
        rclpy.spin_once(node, timeout_sec=0.03)

        height, width = rgb.shape[:2]
        rr.set_time("frame", sequence=frame)
        rr.log("camera/image", rr.Image(rgb).compress(jpeg_quality=85))
        if node.latest is not None:
            centers, sizes, labels = boxes(node.latest, width, height)
            rr.log("camera/image/detections",
                   rr.Boxes2D(centers=centers, sizes=sizes, labels=labels))
            if frame % 50 == 0:
                print(f"frame {frame}: {', '.join(labels) or 'nothing'}")

        frame += 1
        if max_frames is not None and frame >= max_frames:
            return 0
        next_frame += period
        time.sleep(max(0.0, next_frame - time.monotonic()))
        ok, bgr = capture.read()
        if not ok:
            return 0
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    print(f"error: ROS launch exited with {process.returncode}", file=sys.stderr)
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", help="webcam index, video file or stream URL; default: a sample photo")
    parser.add_argument(
        "--prompt", help=f"what to look for, comma separated (default: {SAMPLE_PROMPT!r} "
                         "for the photo, 'person' for a stream)")
    parser.add_argument("--threshold", type=float, default=0.35, help="confidence threshold")
    parser.add_argument("--max-frames", type=int, help="stop a stream after this many frames")
    parser.add_argument("--no-viewer", action="store_true",
                        help="write a .rrd recording instead of spawning the Rerun viewer")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if shutil.which("nvidia-smi") is None:
        print("error: this demo requires an NVIDIA GPU and driver", file=sys.stderr)
        return 2

    CACHE.mkdir(exist_ok=True)
    try:
        download(MODEL_URL, MODEL, MODEL_SHA256)
        capture = None
        if args.source is None:
            download(SAMPLE_URL, SAMPLE, SAMPLE_SHA256)
            first = cv2.cvtColor(cv2.imread(str(SAMPLE)), cv2.COLOR_BGR2RGB)
        else:
            capture = open_source(args.source)
            ok, bgr = capture.read()
            if not ok:
                raise RuntimeError(f"no frames from {args.source!r}")
            first = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except (OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    prompt = to_prompt(args.prompt or (SAMPLE_PROMPT if args.source is None else "person"))
    height, width = first.shape[:2]
    print(f"Starting Isaac ROS Grounding DINO for {width}x{height} images, looking for: {prompt}")
    process = launch(width, height, prompt, args.threshold)

    rclpy.init()
    node = Finder()
    try:
        if not wait_and_set_prompt(node, process, prompt):
            return 1
        if capture is None:
            return run_image(node, process, first, show_viewer=not args.no_viewer)
        return run_stream(node, process, capture, first, not args.source.isdigit(),
                          not args.no_viewer, args.max_frames)
    except KeyboardInterrupt:
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()
        stop(process)


if __name__ == "__main__":
    raise SystemExit(main())
