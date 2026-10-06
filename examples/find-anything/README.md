# Find anything

Type what you are looking for, and Isaac ROS finds it. This example runs NVIDIA's
Grounding DINO, an open-vocabulary detector, through the Isaac ROS GPU pipeline:

```text
image -> GPU resize/pad -> tensor -> Grounding DINO (TensorRT) -> vision_msgs/Detection2DArray -> Rerun
                                          ^
                          "cat, remote control" -> BERT tokenizer
```

Unlike YOLO's fixed 80 classes, the prompt can be anything you can describe: "cup",
"a red shoe", "person wearing a hat".

```bash
cd examples/find-anything
pixi run -e lyrical check
pixi run -e lyrical demo
```

`demo` looks for the cats, remote controls and couch in a COCO sample photo, prints what it
found, opens Rerun with the boxes, and writes `.cache/find_anything_result.png`. Choose your
own prompt with `--prompt`:

```bash
pixi run -e lyrical demo --prompt "cat ears, cat tail"
```

The `jazzy` environment runs the same example on ROS 2 Jazzy with Isaac ROS 4.6:

```bash
pixi run -e jazzy demo
```

## Live webcam

```bash
pixi run -e lyrical webcam
```

While it runs, type a new prompt in the terminal and press Enter; the boxes in Rerun follow
it. `--source` also takes a video file or stream URL:

```bash
pixi run -e lyrical python find_anything.py --source /path/to/video.mp4 --prompt "dog, ball"
```

For a machine without a desktop session, add `--no-viewer` to write
`.cache/find_anything.rrd` instead, and `--max-frames 300` to bound a stream.

## First run

The first run downloads NVIDIA's Grounding DINO Swin-Tiny model (722 MB, checksum-pinned)
and the BERT tokenizer from Hugging Face, then TensorRT builds a GPU-specific engine in
`.cache/`. That takes a few minutes; later runs start in seconds.

An NVIDIA GPU and working driver are required. The model is much larger than YOLOv8n, so
on a Jetson close other GPU-heavy applications first. The model is NVIDIA's TAO
[`grounding_dino_swin_tiny_commercial_deployable_v1.0`](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tao/models/grounding_dino),
under the [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/),
which you accept by downloading it;
the sample photo is COCO val2017 #39769 (CC BY 4.0).
