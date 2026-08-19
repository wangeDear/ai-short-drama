#!/usr/bin/env python3
"""Submit SAM2 mask previews and MoCha character-replacement demos to ComfyUI."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path


BASE = "http://127.0.0.1:8188"
OUT_DIR = Path("/workspace/ComfyUI/output")
STATUS = Path("/root/story_test/role_replace_20260818/status.json")

CLIPS = {
    "selfie": {
        "video": "role_replace/selfie_0000_0337.mp4",
        "positive": [{"x": 250, "y": 160}, {"x": 235, "y": 465}],
        "negative": [{"x": 20, "y": 20}, {"x": 465, "y": 760}],
        "bbox": [35, 85, 410, 832],
        "seed": 8201801,
    },
    "selfie_face": {
        "video": "role_replace/selfie_0000_0337.mp4",
        "generated_video": "role_replace/selfie_face_v2_generated.mp4",
        "positive": [{"x": 250, "y": 160}],
        "negative": [{"x": 20, "y": 20}, {"x": 240, "y": 350}],
        "bbox": [165, 70, 330, 280],
        "seed": 8201811,
        "prompt": (
            "Photorealistic head identity replacement of a Chinese female desert field "
            "engineer, early thirties, natural asymmetrical face, sun-reddened cheeks, "
            "dark practical hair, raw smartphone survival-vlog realism. Preserve every "
            "source pixel outside the head region, especially the exact original torso, "
            "arms, black glove, phone, phone screen, chest camera, background, camera "
            "motion, lighting and shadows. The phone must follow its original continuous "
            "trajectory into frame and must never be newly generated. Replace only the head."
        ),
    },
    "assembly": {
        "video": "role_replace/assembly_2540_2877.mp4",
        "positive": [{"x": 245, "y": 190}, {"x": 250, "y": 440}],
        "negative": [{"x": 20, "y": 20}, {"x": 460, "y": 760}],
        "bbox": [160, 0, 479, 805],
        "seed": 8201802,
    },
    "wash": {
        "video": "role_replace/wash_4000_4337.mp4",
        "positive": [{"x": 385, "y": 470}, {"x": 345, "y": 665}],
        "negative": [{"x": 30, "y": 30}, {"x": 180, "y": 400}],
        "bbox": [245, 305, 480, 832],
        "seed": 8201803,
    },
}

POSITIVE = (
    "Photorealistic Chinese female desert field engineer, early thirties, lean athletic "
    "build, natural asymmetrical face, sun-reddened cheeks, dark hair in a practical low "
    "ponytail, dusty faded khaki field shirt, sand neck gaiter, worn black work gloves, "
    "small action camera on the chest harness. Preserve the source video's exact camera "
    "motion, body motion, hand-object contacts, phone, tools, solar panels, wiring, sand, "
    "lighting, shadows and background. Raw smartphone survival-vlog realism, natural skin "
    "texture, harsh desert sunlight, no beauty filter. Replace only the person."
)

NEGATIVE = (
    "extra hands, extra fingers, fused fingers, missing fingers, duplicated limbs, malformed "
    "hands, altered tools, duplicated equipment, floating objects, broken contact, changed "
    "background, changed solar panel, changed phone, object morphing, CGI, 3D render, plastic "
    "skin, beauty retouching, blur, subtitles, watermark"
)


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(request, timeout=300).read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {path}: {detail}") from exc


def run(workflow: dict, label: str, timeout: int = 3600) -> list[str]:
    prompt_id = post("/prompt", {"prompt": workflow})["prompt_id"]
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(
        json.dumps({"label": label, "prompt_id": prompt_id, "state": "running"}, indent=2),
        encoding="utf-8",
    )
    print(f"[{label}] submitted {prompt_id}", flush=True)
    started = time.time()
    while time.time() - started < timeout:
        time.sleep(5)
        history = json.loads(
            urllib.request.urlopen(BASE + f"/history/{prompt_id}", timeout=300).read()
        )
        if prompt_id not in history:
            continue
        item = history[prompt_id]
        for message in item.get("status", {}).get("messages", []):
            if message[0] == "execution_error":
                error = message[1]
                raise RuntimeError(
                    f"{error.get('node_type')}: {error.get('exception_message', '')}"
                )
        files: list[str] = []
        for output in item.get("outputs", {}).values():
            for info in output.get("images", []) + output.get("videos", []) + output.get("gifs", []):
                files.append(
                    str(OUT_DIR / info.get("subfolder", "") / info["filename"])
                )
        expected_files = [path for path in files if path.endswith(".mp4")] if label.startswith("mocha-") else files
        if expected_files:
            result = {
                "label": label,
                "prompt_id": prompt_id,
                "state": "succeeded",
                "seconds": round(time.time() - started),
                "files": files,
            }
            STATUS.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result), flush=True)
            return files
    raise TimeoutError(f"{label} exceeded {timeout}s")


def shared_nodes(clip: dict, clip_name: str) -> dict:
    x1, y1, x2, y2 = clip["bbox"]
    return {
        "video": {
            "class_type": "VHS_LoadVideo",
            "inputs": {
                "video": clip["video"],
                "force_rate": 24,
                "custom_width": 480,
                "custom_height": 832,
                "frame_load_cap": 81,
                "skip_first_frames": 0,
                "select_every_nth": 1,
                "format": "AnimateDiff",
            },
        },
        "first": {
            "class_type": "ImageFromBatch",
            "inputs": {"image": ["video", 0], "batch_index": 0, "length": 1},
        },
        "sam2_model": {
            "class_type": "DownloadAndLoadSAM2Model",
            "inputs": {
                "model": "sam2.1_hiera_base_plus.safetensors",
                "segmentor": "single_image",
                "device": "cuda",
                "precision": "fp16",
            },
        },
        "points": {
            "class_type": "PointsEditor",
            "inputs": {
                "points_store": json.dumps({"positive": clip["positive"], "negative": clip["negative"]}),
                "coordinates": json.dumps(clip["positive"]),
                "neg_coordinates": json.dumps(clip["negative"]),
                "bbox_store": "[]",
                "bboxes": json.dumps([{"startX": x1, "startY": y1, "endX": x2, "endY": y2}]),
                "bbox_format": "xyxy",
                "width": 480,
                "height": 832,
                "normalize": False,
                "bg_image": ["first", 0],
            },
        },
        "sam2": {
            "class_type": "Sam2Segmentation",
            "inputs": {
                "sam2_model": ["sam2_model", 0],
                "image": ["first", 0],
                "keep_model_loaded": False,
                "bboxes": ["points", 2],
                "individual_objects": False,
            },
        },
        "grow": {
            "class_type": "GrowMaskWithBlur",
            "inputs": {
                "mask": ["sam2", 0],
                "expand": 5,
                "incremental_expandrate": 0.0,
                "tapered_corners": True,
                "flip_input": False,
                "blur_radius": 0.0,
                "lerp_alpha": 1.0,
                "decay_factor": 1.0,
                "fill_holes": True,
            },
        },
        "mask_image": {
            "class_type": "MaskToImage",
            "inputs": {"mask": ["grow", 0]},
        },
        "save_mask": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["mask_image", 0],
                "filename_prefix": f"role_replace/masks/{clip_name}",
            },
        },
    }


def mask_workflow(clip_name: str) -> dict:
    return shared_nodes(CLIPS[clip_name], clip_name)


def mocha_workflow(clip_name: str) -> dict:
    clip = CLIPS[clip_name]
    nodes = shared_nodes(clip, clip_name)
    nodes.update(
        {
            "ref1_load": {
                "class_type": "LoadImage",
                "inputs": {"image": "role_replace/hero_front.png"},
            },
            "ref1_resize": {
                "class_type": "ImageResizeKJv2",
                "inputs": {
                    "image": ["ref1_load", 0],
                    "width": 480,
                    "height": 832,
                    "upscale_method": "lanczos",
                    "keep_proportion": "crop",
                    "pad_color": "0, 0, 0",
                    "crop_position": "center",
                    "divisible_by": 16,
                    "device": "cpu",
                },
            },
            "ref2_load": {
                "class_type": "LoadImage",
                "inputs": {"image": "role_replace/hero_face.png"},
            },
            "ref2_resize": {
                "class_type": "ImageResizeKJv2",
                "inputs": {
                    "image": ["ref2_load", 0],
                    "width": 480,
                    "height": 832,
                    "upscale_method": "lanczos",
                    "keep_proportion": "crop",
                    "pad_color": "0, 0, 0",
                    "crop_position": "center",
                    "divisible_by": 16,
                    "device": "cpu",
                },
            },
            "vae": {
                "class_type": "WanVideoVAELoader",
                "inputs": {
                    "model_name": "wanvideo/Wan2_1_VAE_bf16.safetensors",
                    "precision": "bf16",
                    "use_cpu_cache": False,
                    "verbose": False,
                },
            },
            "embeds": {
                "class_type": "MochaEmbeds",
                "inputs": {
                    "vae": ["vae", 0],
                    "force_offload": True,
                    "input_video": ["video", 0],
                    "mask": ["grow", 0],
                    "ref1": ["ref1_resize", 0],
                    "ref2": ["ref2_resize", 0],
                    "tiled_vae": False,
                },
            },
            "loras": {
                "class_type": "WanVideoLoraSelectMulti",
                "inputs": {
                    "lora_0": "WanVideo/Lightx2v/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank64_bf16.safetensors",
                    "strength_0": 1.0,
                    "lora_1": "none",
                    "strength_1": 1.0,
                    "lora_2": "none",
                    "strength_2": 1.0,
                    "lora_3": "none",
                    "strength_3": 1.0,
                    "lora_4": "none",
                    "strength_4": 1.0,
                    "low_mem_load": True,
                    "merge_loras": True,
                },
            },
            "block_swap": {
                "class_type": "WanVideoBlockSwap",
                "inputs": {
                    "blocks_to_swap": 40,
                    "offload_img_emb": False,
                    "offload_txt_emb": False,
                    "use_non_blocking": False,
                    "vace_blocks_to_swap": 0,
                    "prefetch_blocks": 0,
                    "block_swap_debug": False,
                },
            },
            "model": {
                "class_type": "WanVideoModelLoader",
                "inputs": {
                    "model": "WanVideo/mocha/MoCha/Wan2_1_mocha-14B-preview_fp8_e4m3fn_scaled_KJ.safetensors",
                    "base_precision": "fp16_fast",
                    "quantization": "disabled",
                    "load_device": "offload_device",
                    "attention_mode": "sdpa",
                    "block_swap_args": ["block_swap", 0],
                    "lora": ["loras", 0],
                    "rms_norm_function": "default",
                },
            },
            "text": {
                "class_type": "WanVideoTextEncodeCached",
                "inputs": {
                    "model_name": "umt5-xxl-enc-bf16.safetensors",
                    "precision": "bf16",
                    "positive_prompt": clip.get("prompt", POSITIVE),
                    "negative_prompt": NEGATIVE,
                    "quantization": "disabled",
                    "use_disk_cache": True,
                    "device": "gpu",
                },
            },
            "sampler": {
                "class_type": "WanVideoSampler",
                "inputs": {
                    "model": ["model", 0],
                    "image_embeds": ["embeds", 0],
                    "text_embeds": ["text", 0],
                    "steps": 6,
                    "cfg": 1.0,
                    "shift": 5.0,
                    "seed": clip["seed"],
                    "force_offload": True,
                    "scheduler": "dpm++_sde",
                    "riflex_freq_index": 0,
                    "batched_cfg": False,
                    "rope_function": "comfy",
                },
            },
            "decode": {
                "class_type": "WanVideoDecode",
                "inputs": {
                    "vae": ["vae", 0],
                    "samples": ["sampler", 0],
                    "enable_vae_tiling": False,
                    "tile_x": 272,
                    "tile_y": 272,
                    "tile_stride_x": 144,
                    "tile_stride_y": 128,
                    "normalization": "default",
                },
            },
            "save_video": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["decode", 0],
                    "frame_rate": 24,
                    "loop_count": 0,
                    "filename_prefix": f"role_replace/mocha/{clip_name}",
                    "format": "video/h264-mp4",
                    "pix_fmt": "yuv420p",
                    "crf": 18,
                    "save_metadata": True,
                    "trim_to_audio": False,
                    "pingpong": False,
                    "save_output": True,
                },
            },
        }
    )
    return nodes


def composite_workflow(clip_name: str) -> dict:
    """Hard composite: generated identity inside a tracked head mask, source pixels elsewhere."""
    clip = CLIPS[clip_name]
    return {
        "source_video": {
            "class_type": "VHS_LoadVideo",
            "inputs": {
                "video": clip["video"],
                "force_rate": 24,
                "custom_width": 480,
                "custom_height": 832,
                "frame_load_cap": 81,
                "skip_first_frames": 0,
                "select_every_nth": 1,
                "format": "AnimateDiff",
            },
        },
        "generated_video": {
            "class_type": "VHS_LoadVideo",
            "inputs": {
                "video": clip["generated_video"],
                "force_rate": 24,
                "custom_width": 480,
                "custom_height": 832,
                "frame_load_cap": 81,
                "skip_first_frames": 0,
                "select_every_nth": 1,
                "format": "AnimateDiff",
            },
        },
        "first": {
            "class_type": "ImageFromBatch",
            "inputs": {"image": ["source_video", 0], "batch_index": 0, "length": 1},
        },
        "sam2_model": {
            "class_type": "DownloadAndLoadSAM2Model",
            "inputs": {
                "model": "sam2.1_hiera_base_plus.safetensors",
                "segmentor": "single_image",
                "device": "cuda",
                "precision": "fp16",
            },
        },
        "points": {
            "class_type": "PointsEditor",
            "inputs": {
                "points_store": json.dumps(
                    {
                        "positive": [{"x": 245, "y": 155}, {"x": 245, "y": 105}],
                        "negative": [{"x": 20, "y": 20}, {"x": 245, "y": 350}],
                    }
                ),
                "coordinates": json.dumps([{"x": 245, "y": 155}, {"x": 245, "y": 105}]),
                "neg_coordinates": json.dumps([{"x": 20, "y": 20}, {"x": 245, "y": 350}]),
                "bbox_store": "[]",
                "bboxes": "[]",
                "bbox_format": "xyxy",
                "width": 480,
                "height": 832,
                "normalize": False,
                "bg_image": ["first", 0],
            },
        },
        "track_head": {
            "class_type": "Sam2Segmentation",
            "inputs": {
                "sam2_model": ["sam2_model", 0],
                "image": ["source_video", 0],
                "coordinates_positive": ["points", 0],
                "coordinates_negative": ["points", 1],
                "keep_model_loaded": False,
                "individual_objects": False,
            },
        },
        "invert_person": {
            "class_type": "GrowMaskWithBlur",
            "inputs": {
                "mask": ["track_head", 0],
                "expand": 0,
                "incremental_expandrate": 0.0,
                "tapered_corners": True,
                "flip_input": True,
                "blur_radius": 0.0,
                "lerp_alpha": 1.0,
                "decay_factor": 1.0,
                "fill_holes": True,
            },
        },
        "head_zone": {
            "class_type": "CreateShapeMask",
            "inputs": {
                "shape": "circle",
                "frames": 81,
                "location_x": 285,
                "location_y": 165,
                "grow": 0,
                "frame_width": 480,
                "frame_height": 832,
                "shape_width": 430,
                "shape_height": 300,
            },
        },
        "head_only": {
            "class_type": "MaskComposite",
            "inputs": {
                "destination": ["invert_person", 0],
                "source": ["head_zone", 0],
                "x": 0,
                "y": 0,
                "operation": "multiply",
            },
        },
        "feather": {
            "class_type": "GrowMaskWithBlur",
            "inputs": {
                "mask": ["head_only", 0],
                "expand": 8,
                "incremental_expandrate": 0.0,
                "tapered_corners": True,
                "flip_input": False,
                "blur_radius": 6.0,
                "lerp_alpha": 1.0,
                "decay_factor": 1.0,
                "fill_holes": True,
            },
        },
        "mask_image": {
            "class_type": "MaskToImage",
            "inputs": {"mask": ["feather", 0]},
        },
        "save_mask_video": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["mask_image", 0],
                "frame_rate": 24,
                "loop_count": 0,
                "filename_prefix": f"role_replace/composite/{clip_name}_mask",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 10,
                "save_metadata": True,
                "trim_to_audio": False,
                "pingpong": False,
                "save_output": True,
            },
        },
        "composite": {
            "class_type": "ImageCompositeMasked",
            "inputs": {
                "destination": ["source_video", 0],
                "source": ["generated_video", 0],
                "x": 0,
                "y": 0,
                "resize_source": False,
                "mask": ["feather", 0],
            },
        },
        "save_video": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["composite", 0],
                "frame_rate": 24,
                "loop_count": 0,
                "filename_prefix": f"role_replace/composite/{clip_name}",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 18,
                "save_metadata": True,
                "trim_to_audio": False,
                "pingpong": False,
                "save_output": True,
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["mask", "mocha", "composite"])
    parser.add_argument("clip", choices=sorted(CLIPS))
    args = parser.parse_args()
    if args.mode == "mask":
        workflow = mask_workflow(args.clip)
    elif args.mode == "mocha":
        workflow = mocha_workflow(args.clip)
    else:
        workflow = composite_workflow(args.clip)
    run(workflow, f"{args.mode}-{args.clip}")


if __name__ == "__main__":
    main()
