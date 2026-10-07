"""Isaac ROS Grounding DINO graph for an image stream of any size.

The same nodes as NVIDIA's isaac_ros_grounding_dino_core.launch.py, which works on Isaac ROS
4.6 (Jazzy) and 5.0 (Lyrical). It is defined here rather than through NVIDIA's launch
fragment because the fragment's signature changed between the two releases.

Input:  /image_rect, /camera_info_rect (rgb8, image_width x image_height)
Prompt: /set_prompt (isaac_ros_grounding_dino_interfaces/srv/SetPrompt)
Output: /detections_output (vision_msgs/Detection2DArray, in network image pixels)
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode
from launch_ros.parameter_descriptions import ParameterValue

# Grounding DINO Swin-Tiny's input size.
NETWORK_WIDTH = 960
NETWORK_HEIGHT = 544
CHANNELS = 3


def generate_launch_description():
    args = {
        "image_width": "640",
        "image_height": "480",
        "model_file_path": "",
        "engine_file_path": "",
        "confidence_threshold": "0.35",
        "default_prompt": "cat.",
    }
    config = {name: LaunchConfiguration(name) for name in args}

    nodes = [
        ComposableNode(
            name="resize_node", package="isaac_ros_image_proc",
            plugin="nvidia::isaac_ros::image_proc::ResizeNode",
            parameters=[{
                "input_width": ParameterValue(config["image_width"], value_type=int),
                "input_height": ParameterValue(config["image_height"], value_type=int),
                "output_width": NETWORK_WIDTH,
                "output_height": NETWORK_HEIGHT,
                "keep_aspect_ratio": True,
                "encoding_desired": "rgb8",
                "disable_padding": True,
            }],
            remappings=[("image", "image_rect"), ("camera_info", "camera_info_rect")]),
        ComposableNode(
            name="pad_node", package="isaac_ros_image_proc",
            plugin="nvidia::isaac_ros::image_proc::PadNode",
            parameters=[{
                "output_image_width": NETWORK_WIDTH,
                "output_image_height": NETWORK_HEIGHT,
                "padding_type": "BOTTOM_RIGHT",
            }],
            remappings=[("image", "resize/image")]),
        ComposableNode(
            name="image_to_tensor_node", package="isaac_ros_tensor_proc",
            plugin="nvidia::isaac_ros::dnn_inference::ImageToTensorNode",
            parameters=[{"scale": True, "tensor_name": "image"}],
            remappings=[("image", "padded_image"), ("tensor", "image_tensor")]),
        ComposableNode(
            name="normalize_node", package="isaac_ros_tensor_proc",
            plugin="nvidia::isaac_ros::dnn_inference::ImageTensorNormalizeNode",
            parameters=[{
                "mean": [0.485, 0.456, 0.406],
                "stddev": [0.229, 0.224, 0.225],
                "input_tensor_name": "image",
                "output_tensor_name": "image",
            }],
            remappings=[("tensor", "image_tensor")]),
        ComposableNode(
            name="interleaved_to_planar_node", package="isaac_ros_tensor_proc",
            plugin="nvidia::isaac_ros::dnn_inference::InterleavedToPlanarNode",
            parameters=[{"input_tensor_shape": [NETWORK_HEIGHT, NETWORK_WIDTH, CHANNELS]}],
            remappings=[("interleaved_tensor", "normalized_tensor")]),
        ComposableNode(
            name="reshape_node", package="isaac_ros_tensor_proc",
            plugin="nvidia::isaac_ros::dnn_inference::ReshapeNode",
            parameters=[{
                "output_tensor_name": "images",
                "input_tensor_shape": [CHANNELS, NETWORK_HEIGHT, NETWORK_WIDTH],
                "output_tensor_shape": [1, CHANNELS, NETWORK_HEIGHT, NETWORK_WIDTH],
            }],
            remappings=[("tensor", "planar_tensor")]),
        ComposableNode(
            name="grounding_dino_preprocessor", package="isaac_ros_grounding_dino",
            plugin="nvidia::isaac_ros::grounding_dino::GroundingDinoPreprocessorNode",
            parameters=[{
                "default_prompt": config["default_prompt"],
                "input_image_tensor_name": "images",
            }],
            remappings=[("image_tensor", "reshaped_tensor")]),
        ComposableNode(
            name="grounding_dino_inference", package="isaac_ros_tensor_rt",
            plugin="nvidia::isaac_ros::dnn_inference::TensorRTNode",
            parameters=[{
                "model_file_path": config["model_file_path"],
                "engine_file_path": config["engine_file_path"],
                "input_tensor_names": ["images", "input_ids", "attention_mask",
                                       "position_ids", "token_type_ids", "text_token_mask"],
                "input_binding_names": ["inputs", "input_ids", "attention_mask",
                                        "position_ids", "token_type_ids", "text_token_mask"],
                "output_tensor_names": ["scores", "boxes"],
                "output_binding_names": ["pred_logits", "pred_boxes"],
                "verbose": False,
                "force_engine_update": False,
                # The node's 64 MiB default is too small for the Swin transformer's attention
                # layers: TensorRT finds no implementation for them and the build fails.
                "max_workspace_size": 2 << 30,
            }]),
        ComposableNode(
            name="grounding_dino_decoder", package="isaac_ros_grounding_dino",
            plugin="nvidia::isaac_ros::grounding_dino::GroundingDinoDecoderNode",
            parameters=[{
                "confidence_threshold": ParameterValue(
                    config["confidence_threshold"], value_type=float),
                "image_width": NETWORK_WIDTH,
                "image_height": NETWORK_HEIGHT,
            }]),
    ]

    return LaunchDescription([
        *(DeclareLaunchArgument(name, default_value=value) for name, value in args.items()),
        ComposableNodeContainer(
            name="grounding_dino_container", namespace="", package="rclcpp_components",
            executable="component_container_mt", composable_node_descriptions=nodes,
            output="screen"),
        # Turns prompts into BERT tokens for the preprocessor (transformers + bert-base-uncased).
        Node(
            package="isaac_ros_grounding_dino",
            executable="isaac_ros_grounding_dino_text_tokenizer.py",
            name="grounding_dino_text_tokenizer", output="screen"),
    ])
