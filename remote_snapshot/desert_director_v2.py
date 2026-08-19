#!/usr/bin/env python3
"""《沙漠生存·离网电力篇》导演重制版。

目标：写实纪录片，而不是设备广告或独立自拍镜头合集。
用法：python3 desert_director_v2.py assets|demo|full
demo：S01 人物自拍、S04 设备操作、S12 日落收束。
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request


BASE = "http://127.0.0.1:8188"
IN_DIR = "/workspace/ComfyUI/input"
OUT_DIR = "/workspace/ComfyUI/output"
V_DIR = f"{OUT_DIR}/video/desert_director_v2"
STATUS = "/root/story_test/status_desert_director_v2.json"
W, H = 544, 960

HERO = (
    "a Chinese female field engineer in her early thirties, lean athletic build, "
    "slightly asymmetrical natural face, sun-reddened cheeks, visible pores, sweat and "
    "fine desert dust, dark hair tied in a low practical ponytail, faded khaki field "
    "shirt over a charcoal base layer, sand neck gaiter, worn black work gloves, one "
    "small action camera on the center chest strap, and a weathered olive expedition backpack"
)

REALISM = (
    "Unedited observational field-documentary footage recorded on a modern smartphone, "
    "vertical 9:16. Natural skin texture, imperfect exposure, subtle rolling shutter, "
    "occasional autofocus breathing, restrained colors, physically correct hard sunlight, "
    "real sand and wind behavior. No beauty filter, no commercial polish, no artificial "
    "cinematic lens flare, no slow motion. One continuous take. "
)

NOTEXT = (
    "No subtitles, captions, logos, labels, watermark or readable fake text. "
    "No duplicated equipment, no object morphing, no sudden object appearance, no cuts. "
)

NEG = (
    "cartoon, illustration, 3D render, CGI, game asset, beauty retouching, fashion photo, "
    "advertising photo, plastic skin, symmetrical perfect face, extra fingers, extra limbs, "
    "duplicated objects, floating cables, impossible wiring, fake text, logo, watermark, city"
)


def h3_len(seconds):
    frames = max(5, round(seconds * 24))
    remainder = frames % 17
    if remainder != 5:
        frames += (5 - remainder) % 17
    return frames


def status(**updates):
    current = json.load(open(STATUS, encoding="utf-8")) if os.path.exists(STATUS) else {}
    current.update(updates, timestamp=time.strftime("%F %T"))
    with open(STATUS, "w", encoding="utf-8") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)


def post(path, payload=None):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload if payload is not None else {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(request, timeout=300).read())


def run(workflow, tag):
    prompt_id = post("/prompt", workflow)["prompt_id"]
    started = time.time()
    status(stage=tag, prompt_id=prompt_id, done=False, error="")
    print(f"[{tag}] submitted {prompt_id}", flush=True)
    while True:
        time.sleep(8)
        history = json.loads(
            urllib.request.urlopen(BASE + f"/history/{prompt_id}", timeout=300).read()
        )
        if prompt_id not in history:
            continue
        item = history[prompt_id]
        files = []
        for output in item.get("outputs", {}).values():
            for file_info in output.get("images", []) + output.get("videos", []):
                files.append(
                    os.path.join(
                        OUT_DIR,
                        file_info.get("subfolder", ""),
                        file_info["filename"],
                    )
                )
        if files:
            elapsed = round(time.time() - started)
            status(stage=tag, done=True, seconds=elapsed)
            print(f"[{tag}] DONE {elapsed}s", flush=True)
            return files
        for message in item.get("status", {}).get("messages", []):
            if message[0] == "execution_error":
                detail = message[1]
                error = f"{detail.get('node_type')}: {detail.get('exception_message', '')[:300]}"
                status(stage=tag, done=True, error=error)
                raise RuntimeError(error)
        if time.time() - started > 1800:
            raise RuntimeError(f"{tag} timed out")


def qwen_workflow(prompt, prefix, reference_images=(), seed=920001):
    nodes = {
        "unet": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "qwen_image_edit_2511_fp8mixed.safetensors",
                "weight_dtype": "default",
            },
        },
        "shift": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["unet", 0], "shift": 3.1},
        },
        "cfgn": {
            "class_type": "CFGNorm",
            "inputs": {"model": ["shift", 0], "strength": 1.0},
        },
        "lora": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["cfgn", 0],
                "lora_name": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
                "strength_model": 1.0,
            },
        },
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "type": "qwen_image",
                "device": "default",
            },
        },
        "vae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "qwen_image_vae.safetensors"},
        },
        "empty": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": W, "height": H, "batch_size": 1},
        },
    }
    positive_inputs = {"clip": ["clip", 0], "vae": ["vae", 0], "prompt": prompt}
    negative_inputs = {"clip": ["clip", 0], "vae": ["vae", 0], "prompt": NEG}
    for index, image_name in enumerate(reference_images, 1):
        key = f"load{index}"
        nodes[key] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        positive_inputs[f"image{index}"] = [key, 0]
        negative_inputs[f"image{index}"] = [key, 0]
    nodes["pos"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": positive_inputs}
    nodes["neg"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": negative_inputs}
    nodes["sampler"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["lora", 0],
            "positive": ["pos", 0],
            "negative": ["neg", 0],
            "latent_image": ["empty", 0],
            "seed": seed,
            "steps": 4,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0,
        },
    }
    nodes["decode"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]},
    }
    nodes["save"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["decode", 0], "filename_prefix": prefix},
    }
    return {"prompt": nodes}


ASSETS = [
    (
        "dd2_hero",
        "A candid full-body documentary reference photograph of " + HERO + ". She stands "
        "beside a low desert camp tarp, tired but alert, not posing like a model. Her clothing "
        "is sun-faded, creased and dusty; the backpack straps and single chest camera are "
        "physically plausible. Harsh late-morning desert light, neutral smartphone color, "
        "vertical composition, 35mm-equivalent perspective, realistic pores and flyaway hair. "
        "No product logos, no second camera, no glamour lighting, no stylization.",
        (),
        920101,
    ),
    (
        "dd2_kit",
        "Overhead documentary photograph of one compact off-grid emergency power kit laid "
        "neatly on a dusty olive canvas groundsheet: one unbranded four-section folding solar "
        "panel, one compact rugged portable power station, one folding aluminum triangle stand, "
        "two sand stakes with guy lines, one coiled heavy black cable, one USB power meter, one "
        "phone cable, and one soft panel-cleaning brush. Every item has believable scale and "
        "construction. No duplicate parts, no generator, no water pump, no loose circuit boards, "
        "no readable labels or logos. Real midday desert sunlight, vertical field photo.",
        (),
        920102,
    ),
    (
        "dd2_site_midday",
        "A realistic remote desert emergency camp photographed vertically with a phone: one "
        "four-section folding solar panel mounted low on a compact aluminum triangle stand, "
        "secured by exactly two guy lines to two buried sand stakes. A single black cable runs "
        "from the panel to one compact portable power station kept under a small beige shade "
        "cloth beside one weathered olive backpack and a soft brush. Sparse, practical setup, "
        "nothing duplicated, no people, no vehicle, no buildings, no generator, no water pump, "
        "no labels. Hard late-morning sun and wind-rippled dunes; observational documentary photo.",
        (),
        920103,
    ),
    (
        "dd2_site_sunset",
        "Edit the provided camp photograph. Preserve the exact same solar panel, stand, two "
        "guy lines, two sand stakes, cable route, shaded portable power station, backpack and "
        "brush in exactly the same positions and scale. Change only the time and light to a "
        "natural desert golden hour with a low sun, longer shadows and slightly cooler distant "
        "dunes. Do not add or remove any equipment or people. Keep it an unedited phone photo.",
        ("dd2_site_midday.png",),
        920104,
    ),
    (
        "dd2_hero_v2",
        "Edit the provided character photograph. Preserve the same woman's exact natural face, "
        "skin texture, sun-reddened cheeks, low ponytail, dusty faded khaki clothes, gloves and "
        "weathered olive backpack. Remove the hanging compact camera completely. Add exactly one "
        "small black action camera centered on the backpack sternum strap at mid chest, attached "
        "with a believable mount. Replace the large tent background with plain wind-rippled desert "
        "dunes and a small low beige shade cloth far behind her. Keep candid documentary phone-photo "
        "lighting and an unposed tired expression. No logos, no second camera, no beauty retouching.",
        ("dd2_hero.png",),
        920111,
    ),
    (
        "dd2_site_midday_v2",
        "Edit the provided desert camp photograph while preserving the exact four-section solar "
        "panel, its aluminum stand, guy-line geometry, cable route, shade cloth, power station and "
        "backpack. Remove only the unidentified furry round object beside the backpack. Put one "
        "plain black soft cleaning brush in that spot instead. Make the power station sit fully in "
        "shade. Do not add, remove, duplicate or redesign anything else. Keep the same late-morning "
        "light, dune shapes, camera position and unedited phone-documentary appearance.",
        ("dd2_site_midday.png",),
        920112,
    ),
    (
        "dd2_kit_v2",
        "Using the provided corrected camp photograph as the strict equipment source, create a "
        "straight overhead documentary inventory photograph on one dusty olive canvas groundsheet. "
        "Show exactly these separate items with their same construction and scale: one four-section "
        "folding solar panel with four equal dark-blue photovoltaic sections, one compact black power "
        "station, one folding aluminum triangle stand, exactly two broad sand stakes with two guy "
        "lines, one coiled heavy black cable, one small USB power meter, one phone cable, and one "
        "plain black soft brush. No fifth panel section, no brown cells, no duplicates, no generator, "
        "no water pump, no readable labels or logos. Hard desert daylight, realistic phone photo.",
        ("dd2_site_midday_v2.png",),
        920113,
    ),
    (
        "dd2_site_sunset_v2",
        "Edit the provided corrected midday camp photograph. Preserve every object's identity, "
        "count, position, scale and cable route exactly: the four-section panel, stand, guy lines, "
        "stakes, shade cloth, power station, backpack and black brush. Change only the lighting to "
        "natural desert golden hour with a low sun and long shadows. Do not add any person, animal, "
        "equipment or text. Keep the same phone camera position and restrained documentary color.",
        ("dd2_site_midday_v2.png",),
        920114,
    ),
]


def build_prompt(picture_definitions, retention, description, soundscape, dialogue=None):
    speaker = ""
    if dialogue:
        speaker = (
            " She looks into the lens, keeps her head naturally still, and says in clear "
            f"Mandarin with restrained field-report delivery: <Subject1> (S1) says, [Chinese] `{dialogue}` "
            "Her lip movement follows the words without exaggeration. She closes her mouth and "
            "breathes out naturally when finished."
        )
    return f"""subject_definitions:
{picture_definitions}

summary: [reference generation] A realistic vertical field-documentary clip about building a compact emergency solar charging system in a remote desert.

retention_analysis:
{retention}

detailed_description:
{REALISM}{description}{speaker} {NOTEXT}

overall_soundscape: {soundscape}. No narration, no music, no artificial cinematic impacts.

non_diegetic_music: none.
"""


def shots():
    hero_def = f"<Subject1> is {HERO}. Visual identity comes from <Picture 1>."
    site_mid = (
        "<Picture 2> is the continuity master for the exact midday camp equipment and layout. "
        "<Picture 3> is the exact emergency kit and component reference."
    )
    site_sun = (
        "<Picture 2> is the continuity master for the exact sunset camp equipment and layout. "
        "<Picture 3> is the exact emergency kit and component reference."
    )
    hero_retain = "<Picture 1>: preserve identity, natural face, dusty clothing and single chest camera; allow pose and expression to change."
    mid_retain = (
        "<Picture 2>: preserve the single-panel camp layout and equipment count exactly.\n"
        "<Picture 3>: preserve product shapes, scale and cable types; do not duplicate components."
    )
    sun_retain = mid_retain.replace("<Picture 2>", "<Picture 2>")
    result = []

    def add(sid, duration, refs, prompt):
        result.append({"id": sid, "dur": duration, "refs": list(refs), "prompt": prompt})

    add(1, 8, ("dd2_hero_v2.png", "dd2_site_midday_v2.png", "dd2_kit_v2.png"), build_prompt(
        hero_def + "\n" + site_mid,
        hero_retain + "\n" + mid_retain,
        "[Shot 1] Handheld front-camera selfie at arm's length. The tired engineer crouches beside "
        "her backpack; sweat has darkened the collar and fine dust sticks to her cheek. She briefly "
        "holds a scuffed phone close enough to reveal only a simple red nearly-empty battery icon, "
        "then lowers it. The solar kit remains packed behind her.",
        "steady dry wind, faint sand hiss, fabric movement and natural breathing",
        "手机快没电了，导航撑不了多久。我得先把应急供电搭起来。",
    ))
    add(2, 5, ("dd2_hero_v2.png", "dd2_site_midday_v2.png"), build_prompt(
        hero_def + "\n<Picture 2> shows the exact camp location before deployment.",
        hero_retain + "\n<Picture 2>: preserve the dune shape, groundsheet, backpack and hard daylight.",
        "[Shot 1] Rear-phone wide shot from waist height, camera resting on the groundsheet rather "
        "than floating. The engineer enters frame carrying the same backpack, kneels once, lowers it "
        "onto the canvas and unclips the top buckle. One clean action; the wind pushes loose fabric.",
        "wind across the microphone, one backpack thud, buckle click, sand under boots",
    ))
    add(3, 6, ("dd2_kit_v2.png", "dd2_site_midday_v2.png"), build_prompt(
        "<Picture 1> defines the exact kit. <Picture 2> defines the exact camp groundsheet and surroundings.",
        "<Picture 1>: fully preserve the component count, shapes and scale.\n<Picture 2>: preserve the groundsheet and midday light.",
        "[Shot 1] Locked overhead phone shot. Two worn black-gloved hands remove the same folded "
        "four-section panel from the open backpack, place it on the canvas, and unfold exactly one "
        "hinged section in a clear mechanically plausible motion. No face is visible.",
        "zipper, canvas rustle, fabric hinge and a dull panel tap",
    ))
    add(4, 6, ("dd2_kit_v2.png", "dd2_site_midday_v2.png"), build_prompt(
        "<Picture 1> defines the exact kit. <Picture 2> defines the exact camp and daylight.",
        "<Picture 1>: preserve the one folding panel, one USB meter and one phone cable.\n<Picture 2>: preserve real sand and hard daylight.",
        "[Shot 1] Tight over-shoulder documentary shot. The panel lies flat and already connected. "
        "One gloved hand shades the small unbranded USB meter while the other tilts it toward camera. "
        "The simple indicator fluctuates weakly without readable numbers. Heat shimmer and grains of "
        "sand collect along the panel edge. One action only; no talking face.",
        "wind, faint electronic chirp, cable rubbing canvas and sand tapping the panel",
    ))
    add(5, 5, ("dd2_hero_v2.png", "dd2_kit_v2.png", "dd2_site_midday_v2.png"), build_prompt(
        hero_def + "\n<Picture 2> defines the exact kit. <Picture 3> defines the camp layout.",
        hero_retain + "\n<Picture 2>: preserve the folding stand and panel.\n<Picture 3>: preserve the groundsheet and one power station.",
        "[Shot 1] Static medium side shot. Kneeling, the engineer lifts the near edge of the same "
        "four-section panel and opens the compact aluminum triangle stand underneath until its brace "
        "locks. She keeps both hands on the hardware; the panel does not change shape.",
        "aluminum hinge click, panel fabric creak, wind and sand under knees",
    ))
    add(6, 7, ("dd2_hero_v2.png", "dd2_site_midday_v2.png", "dd2_kit_v2.png"), build_prompt(
        hero_def + "\n" + site_mid,
        hero_retain + "\n" + mid_retain,
        "[Shot 1] Rear-camera medium close shot, not selfie-wide. The engineer kneels beside the now "
        "tilted single panel and gestures once toward its raised back and the blowing sand. She keeps "
        "one hand bracing the stand while reporting to the camera.",
        "dry crosswind, guy line vibration, quiet panel fabric rustle",
        "板子平铺又热又积沙。支起来对准太阳，再把底座固定住。",
    ))
    add(7, 6, ("dd2_hero_v2.png", "dd2_kit_v2.png", "dd2_site_midday_v2.png"), build_prompt(
        hero_def + "\n<Picture 2> defines the exact two stakes and guy lines. <Picture 3> defines the exact layout.",
        hero_retain + "\n<Picture 2>: preserve exactly two stakes and two lines.\n<Picture 3>: preserve the single panel and stand.",
        "[Shot 1] Low close shot beside the stand. The engineer presses one broad sand stake deep at "
        "an angle with both gloved hands, then pulls the attached guy line once to tension it. The "
        "stand stops rattling. The second stake is already visible on the opposite side; nothing duplicates.",
        "stake grinding into sand, one cord pull, metal rattle settling and wind",
    ))
    add(8, 5, ("dd2_hero_v2.png", "dd2_kit_v2.png", "dd2_site_midday_v2.png"), build_prompt(
        hero_def + "\n<Picture 2> defines the exact soft brush and panel. <Picture 3> defines the camp.",
        hero_retain + "\n<Picture 2>: preserve one brush and the four-section panel.\n<Picture 3>: preserve the layout.",
        "[Shot 1] Macro phone shot at panel height. A single soft brush makes one long deliberate "
        "stroke across the dusty blue panel; loose sand rolls off the lower edge in a thin sheet. "
        "Only her glove and sleeve enter frame. No water is used.",
        "soft bristles across glass, dry sand trickling and steady wind",
    ))
    add(9, 6, ("dd2_hero_v2.png", "dd2_site_midday_v2.png", "dd2_kit_v2.png"), build_prompt(
        hero_def + "\n" + site_mid,
        hero_retain + "\n" + mid_retain,
        "[Shot 1] Ground-level three-quarter shot. The engineer places the one compact power station "
        "fully under the beige shade cloth, routes the existing black cable through a cloth loop and "
        "pushes the connector firmly into the matching socket once. The cable remains on the canvas, "
        "never buried in hot sand.",
        "connector click, canvas flap, cable scrape and muted wind under the shade",
    ))
    add(10, 5, ("dd2_kit_v2.png", "dd2_site_midday_v2.png"), build_prompt(
        "<Picture 1> defines the exact power station, cable and phone. <Picture 2> defines the exact completed camp.",
        "<Picture 1>: preserve the device shapes and single cable path.\n<Picture 2>: preserve the completed one-panel system.",
        "[Shot 1] Tight insert shot under the shade. The power station's small status light turns from "
        "amber to green as a phone is connected. The phone shows only a recognizable charging battery "
        "symbol, no readable percentage. A gloved thumb gently taps the screen once; all cables stay fixed.",
        "one soft electronic chime, low inverter fan, fabric shade rustle",
    ))
    add(11, 6, ("dd2_hero_v2.png", "dd2_site_midday_v2.png", "dd2_kit_v2.png"), build_prompt(
        hero_def + "\n" + site_mid,
        hero_retain + "\n" + mid_retain,
        "[Shot 1] Slow, human-operated rear-camera reveal from the anchored single panel along the "
        "one black cable to the shaded power station and charging phone, ending on the engineer "
        "checking the tension of one guy line. The movement is restrained and imperfect, not a drone "
        "orbit. Equipment count and placement never change.",
        "lower afternoon wind, faint fan hum, guy line vibration and distant sand hiss",
    ))
    add(12, 8, ("dd2_hero_v2.png", "dd2_site_sunset_v2.png", "dd2_kit_v2.png"), build_prompt(
        hero_def + "\n" + site_sun,
        hero_retain + "\n" + sun_retain,
        "[Shot 1] Natural golden-hour rear-camera medium shot. The exact same completed one-panel system "
        "fills the lower background, with the portable power station still in shade. The engineer sits "
        "on the groundsheet, raises the charging phone briefly, then looks into the lens. Her fatigue "
        "reads as relief rather than triumph; wind has loosened a few strands of hair.",
        "gentler evening wind, low power-station fan, fabric rustle and one distant bird",
        "电量在回升，导航也保住了。沙漠里，先解决通信，再谈舒服。",
    ))
    return result


DEMO_IDS = {1, 4, 12}


def h3_workflow(shot):
    nodes = {
        "unet": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                "weight_dtype": "default",
            },
        },
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "type": "minimax",
                "device": "default",
            },
        },
        "vvae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
        },
        "avae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"},
        },
        "noise": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": 920000 + shot["id"] * 137, "control_after_generate": "fixed"},
        },
        "guider": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["unet", 0], "conditioning": ["i2v", 0]},
        },
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "sigmas": {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["unet", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0},
        },
        "vdecode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sample", 0], "vae": ["vvae", 0]},
        },
        "adecode": {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": ["sample", 0], "vae": ["avae", 0]},
        },
        "video": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["vdecode", 0], "fps": 24, "audio": ["adecode", 0]},
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["video", 0],
                "filename_prefix": f"video/desert_director_v2/dd2_S{shot['id']:02d}",
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    references = []
    for index, image_name in enumerate(shot["refs"], 1):
        key = f"ref{index}"
        nodes[key] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        references.append([key, 0])
    nodes["i2v"] = {
        "class_type": "MiniMaxH3ReferenceToVideo",
        "inputs": {
            "clip": ["clip", 0],
            "vae": ["vvae", 0],
            "audio_vae": ["avae", 0],
            "prompt": shot["prompt"],
            "width": W,
            "height": H,
            "length": h3_len(shot["dur"]),
            "ref_image_size": "match",
            "ref_images": references,
        },
    }
    nodes["sample"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["noise", 0],
            "guider": ["guider", 0],
            "sampler": ["sampler", 0],
            "sigmas": ["sigmas", 0],
            "latent_image": ["i2v", 1],
        },
    }
    return {"prompt": nodes}


def generate_assets():
    for name, prompt, refs, seed in ASSETS:
        destination = f"{IN_DIR}/{name}.png"
        if os.path.exists(destination):
            print(f"[{name}] exists, skip", flush=True)
            continue
        files = run(qwen_workflow(prompt, f"desert_director_v2/asset_{name}", refs, seed), name)
        shutil.copy(files[0], destination)
        print(f"[{name}] copied to input", flush=True)


def generate_shots(mode):
    selected = DEMO_IDS if mode == "demo" else None
    os.makedirs(V_DIR, exist_ok=True)
    for shot in shots():
        if selected and shot["id"] not in selected:
            continue
        existing = glob.glob(f"{V_DIR}/dd2_S{shot['id']:02d}*.mp4")
        if existing:
            print(f"[S{shot['id']:02d}] exists, skip", flush=True)
            continue
        status(phase="video", shot=shot["id"], total=12, mode=mode)
        run(h3_workflow(shot), f"S{shot['id']:02d}")


def concatenate():
    segments = []
    for shot in shots():
        files = glob.glob(f"{V_DIR}/dd2_S{shot['id']:02d}*.mp4")
        if not files:
            raise RuntimeError(f"S{shot['id']:02d} missing")
        segments.append(max(files, key=os.path.getmtime))
    list_path = "/root/story_test/dd2_concat.txt"
    with open(list_path, "w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(f"file '{segment}'\n")
    final_path = f"{V_DIR}/desert_director_v2_final.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "160k", final_path,
        ],
        check=True,
    )
    status(stage="complete", done=True, final=final_path)
    print(f"FINAL: {final_path}", flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if mode not in {"assets", "demo", "full"}:
        raise SystemExit("usage: desert_director_v2.py assets|demo|full")
    if mode == "assets":
        generate_assets()
        return
    missing_assets = [name for name, _, _, _ in ASSETS if not os.path.exists(f"{IN_DIR}/{name}.png")]
    if missing_assets:
        raise RuntimeError(f"missing assets: {missing_assets}; run assets first")
    generate_shots(mode)
    if mode == "full":
        concatenate()
    else:
        status(stage="demo_complete", done=True)
        print("DEMO COMPLETE", flush=True)


if __name__ == "__main__":
    main()
