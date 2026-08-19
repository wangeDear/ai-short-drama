#!/usr/bin/env python3
"""沙漠离网电力导演版 v3：Qwen关键帧 + H3 FL2VA。

用法：
  python3 desert_keyframe_v3.py keyframes
  python3 desert_keyframe_v3.py demo
  python3 desert_keyframe_v3.py full
"""
import glob
import os
import subprocess
import sys

import desert_director_v2 as base


IN_DIR = base.IN_DIR
OUT_DIR = base.OUT_DIR
V_DIR = f"{OUT_DIR}/video/desert_keyframe_v3"
W, H = base.W, base.H


KEYFRAMES = [
    {
        "id": 1,
        "refs": ("dd2_hero_v2.png",),
        "prompt": (
            "Create the opening frame of a candid vertical phone selfie using the same woman from the "
            "reference photograph. It is before any equipment has been unpacked. She crouches alone on "
            "plain wind-rippled desert sand beside one completely closed weathered olive backpack. There "
            "is no groundsheet, no solar panel, no power station, no cable, no tent and no equipment visible "
            "anywhere in the background. She holds one scuffed smartphone near her chest with its screen "
            "facing toward herself and away from the camera; the camera sees only the worn dark phone case, "
            "so no UI or battery icon is visible. Tired, sun-reddened natural face, sweat and "
            "dust, one chest action camera, harsh late-morning light. No extra gear, no text or logos."
        ),
    },
    {
        "id": 2,
        "refs": ("dd2_hero_v2.png", "dd3_kf_S01.png"),
        "prompt": (
            "Create a rear-phone wide documentary frame immediately after image 2. Preserve the exact "
            "same woman's face, clothing, backpack and desert. The phone camera is resting at waist height "
            "on the beige groundsheet. She enters frame and begins lowering the same closed olive backpack "
            "onto the cloth, both hands on its straps. No solar equipment is deployed or visible yet. "
            "Natural imperfect composition, hard sun, real footprints and wind-blown fabric."
        ),
    },
    {
        "id": 3,
        "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"),
        "prompt": (
            "Using the exact four-section panel design from image 1, create a locked overhead documentary "
            "frame one moment earlier. The panel is folded accordion-style into a compact rectangular stack "
            "on a beige groundsheet beside one open olive backpack; all four equal dark-blue sections are "
            "present as four aligned layers with their fabric hinges visible at the side. Only the same "
            "woman's dusty khaki sleeves and two worn black-gloved hands hold the folded stack. One compact "
            "black power station and one coiled black cable remain beside the bag. No panel is deployed, "
            "no panel is attached to the backpack, no face, no duplicates, no wood and no fake text."
        ),
    },
    {
        "id": 4,
        "refs": ("dd2_site_midday_v2.png", "dd2_hero_v2.png"),
        "prompt": (
            "Create a tight over-shoulder documentary frame during the first test. The exact same one "
            "four-section dark-blue folding solar panel lies flat on the beige groundsheet, all four "
            "sections clearly connected by fabric hinges. A single black cable leads to one small "
            "unbranded USB power meter held in one worn black-gloved hand; the other hand shades the "
            "screen. The meter shows only a weak generic bar indicator, no readable numbers or fake text. "
            "Preserve the same khaki sleeve and harsh midday desert light."
        ),
    },
    {
        "id": 5,
        "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"),
        "prompt": (
            "Using the exact flat four-section panel from image 1, create a static medium side documentary "
            "frame. Preserve the same woman from image 2. She kneels on the beige groundsheet and lifts the "
            "near edge of the panel while opening two low integrated aluminum kickstand legs hinged directly "
            "to the back of the panel. The legs form a simple shallow A-frame only under the panel; there is "
            "no tent, no tall tripod, no fabric roof and no separate structure. One compact power station and "
            "backpack remain on the cloth. Four panel sections stay unchanged and physically connected."
        ),
    },
    {
        "id": 6,
        "refs": ("dd2_hero_v2.png", "dd2_site_midday_v2.png"),
        "prompt": (
            "Create a rear-camera medium close documentary frame of the same woman kneeling beside the "
            "same fully tilted four-section panel and aluminum stand. One gloved hand braces the stand; "
            "the other hand rests naturally on her knee, not scooping or throwing sand. A thin line of "
            "wind-blown sand is visible along the lower panel edge. The same power station and "
            "backpack remain under the low shade in the same relative position. She looks toward the phone "
            "camera, ready to explain. Natural tired face, no commercial pose, no loose tool in her hands."
        ),
    },
    {
        "id": 7,
        "refs": ("dd3b_kf_S06.png", "dd2_hero_v2.png"),
        "prompt": (
            "Create a tight low crop beside the exact same solar stand in image 1. Preserve the same woman's "
            "dusty khaki sleeves and worn black gloves. Both hands press exactly one broad dark metal sand "
            "stake into the dune at a backward angle. One white guy line is visibly tied from that stake to "
            "the nearest panel corner. The four-section panel is only partially visible at the top and stays "
            "unchanged. No loose aluminum poles in her hands, no extra stakes, no wood and no tool deformation."
        ),
    },
    {
        "id": 8,
        "refs": ("dd2_site_midday_v2.png", "dd2_hero_v2.png"),
        "prompt": (
            "Create a macro phone frame level with the same four-section solar panel. One worn black glove "
            "holds the same plain black soft brush at the upper edge, ready for a single downward stroke. "
            "Fine wind-blown sand visibly coats the dark-blue cells, with a clean narrow strip behind the "
            "brush. Only a dusty khaki sleeve enters frame. No water, no face, no extra tools or panels."
        ),
    },
    {
        "id": 9,
        "refs": ("dd2_hero_v2.png", "dd2_site_midday_v2.png"),
        "prompt": (
            "Create a ground-level three-quarter documentary frame of the same completed one-panel camp. "
            "The same woman kneels at the low beige shade and places exactly one compact black portable "
            "power station fully inside the shadow. One existing heavy black cable runs from the same "
            "four-section panel across the beige cloth; she holds its single connector aligned with the "
            "matching socket. Backpack and brush remain in place. No fake wiring or extra devices."
        ),
    },
    {
        "id": 10,
        "refs": ("dd2_site_midday_v2.png", "dd2_hero_v2.png"),
        "prompt": (
            "Create a tight insert frame under the same beige shade. Exactly one compact black power "
            "station sits in shadow, connected to the one black solar cable. One scuffed smartphone lies "
            "beside it, connected by one short phone cable. Its screen shows only a simple green charging "
            "battery symbol, no percentage or readable words. One gloved thumb is about to tap the screen. "
            "Natural low contrast shade, no duplicate cables, no fake text."
        ),
    },
    {
        "id": 11,
        "refs": ("dd2_hero_v2.png", "dd2_site_midday_v2.png"),
        "prompt": (
            "Create a slightly imperfect rear-phone wide documentary frame of the exact completed camp in "
            "image 2: one four-section panel, one aluminum stand, exactly two guy lines and stakes, one "
            "cable to one shaded power station, one backpack and one black brush. The same woman crouches "
            "at the far edge checking one guy line. Preserve every equipment count and placement. Lower "
            "afternoon hard light, no drone perspective, no commercial product composition."
        ),
    },
    {
        "id": 12,
        "refs": ("dd2_hero_v2.png", "dd2_site_sunset_v2.png"),
        "prompt": (
            "Create the final golden-hour rear-phone medium frame. Preserve the exact same woman's natural "
            "face, dusty clothes, backpack straps and single chest camera from image 1, and preserve the "
            "exact completed four-section solar system, stand, cables, shaded power station, backpack and "
            "brush from image 2. She sits on the beige groundsheet, holds one charging phone loosely near "
            "her chest and looks at the camera with exhausted relief, not triumph. Low sun, long shadows, "
            "wind-loosened hair, restrained color, no added objects or readable text."
        ),
    },
]


VIDEO = {
    1: (8, "Front-camera field vlog. She checks the phone with its screen kept facing herself and away from the lens, lowers it near her knee, then reports calmly. No phone UI is ever visible. <Subject1> (S1) says, [Chinese] `手机快没电了，导航撑不了多久。我得先把应急供电搭起来。` Natural restrained lip sync; she closes her mouth and exhales. Wind moves only loose hair and fabric."),
    2: (5, "One continuous rear-phone shot. She lowers the backpack onto the cloth, releases both straps, and unclips one buckle. The camera remains grounded and imperfectly static. No talking."),
    3: (6, "Locked overhead shot. The two gloved hands unfold exactly one hinged panel section, flatten it, then pause. Panel construction and all nearby objects remain unchanged. No talking."),
    4: (5, "Tight over-shoulder insert. The gloved hand slowly tilts the USB meter toward camera while the weak generic indicator flickers once; the other hand continues shading it. No talking and no camera move."),
    5: (5, "Static medium side shot. She opens the aluminum stand brace until it clicks into place, then releases one hand while the panel remains stable. One mechanically plausible action. No talking."),
    6: (7, "Rear-camera medium close shot. Keeping one hand on the stand, she points to the panel edge and reports calmly. <Subject1> (S1) says, [Chinese] `板子平铺又热又积沙。支起来对准太阳，再把底座固定住。` Restrained lip sync; panel and camp remain fixed."),
    7: (5, "Low close shot. She pushes the single stake deeper once, pulls the attached guy line once, and the stand's small rattle stops. No duplicated tools or equipment. No talking."),
    8: (5, "Macro locked shot. The soft brush makes one slow complete downward stroke; a thin sheet of dry sand falls from the panel edge and reveals clean dark-blue cells. No talking."),
    9: (5, "Ground-level shot. She slides the power station fully into shade and pushes the aligned connector into its socket once. Cable path, panel and backpack remain unchanged. No talking."),
    10: (5, "Locked insert. The gloved thumb taps the phone once; its simple battery symbol turns green and the power station status light glows steadily. All devices and cables remain rigid and consistent. No talking."),
    11: (6, "A restrained human-operated phone move travels slowly from the anchored panel along the single cable to the shaded power station, ending on the woman checking one guy line. No orbit, no drone motion, no equipment changes, no talking."),
    12: (8, "Golden-hour rear-phone medium shot. She raises the charging phone slightly, looks into the lens and speaks with tired relief. <Subject1> (S1) says, [Chinese] `电量在回升，导航也保住了。沙漠里，先解决通信，再谈舒服。` Natural restrained lip sync; she lowers the phone, closes her mouth and breathes out. The background system remains fixed."),
}


KEYFRAME_PREFIX = {1: "dd3c", 3: "dd3b", 5: "dd3b", 6: "dd3b", 7: "dd3b"}


def keyframe_path(shot_id):
    prefix = KEYFRAME_PREFIX.get(shot_id, "dd3")
    return f"{prefix}_kf_S{shot_id:02d}.png"


def video_prefix(shot_id):
    return "dd3c" if shot_id == 1 else "dd3"


def generate_keyframes():
    for item in KEYFRAMES:
        destination = f"{IN_DIR}/{keyframe_path(item['id'])}"
        if os.path.exists(destination):
            print(f"[KF S{item['id']:02d}] exists, skip", flush=True)
            continue
        files = base.run(
            base.qwen_workflow(
                item["prompt"],
                f"desert_keyframe_v3/kf_S{item['id']:02d}",
                item["refs"],
                930000 + item["id"] * 97,
            ),
            f"KF_S{item['id']:02d}",
        )
        import shutil
        shutil.copy(files[0], destination)


def h3_i2v_workflow(shot_id, duration, video_description):
    prompt = f"""subject_definitions:
<Picture 1> is the exact opening frame and geometry anchor. <Subject1> is the woman visible in <Picture 1>.

summary: [keyframe completion] A realistic vertical field-documentary shot in a desert emergency solar story.

retention_analysis:
<Picture 1>: fully_preserved for identity, equipment count, equipment construction, cable routes, clothing, location and lighting; allow only the explicitly described human and environmental motion.

detailed_description:
{base.REALISM}{video_description} {base.NOTEXT}

overall_soundscape: realistic dry desert wind and only the visible physical action sounds. No narration, no music, no cinematic impacts.

non_diegetic_music: none.
"""
    nodes = {
        "unet": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "vvae": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "avae": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "first": {"class_type": "LoadImage", "inputs": {"image": keyframe_path(shot_id)}},
        "i2v": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["clip", 0], "vae": ["vvae", 0], "prompt": prompt,
            "width": W, "height": H, "length": base.h3_len(duration), "first_frame": ["first", 0]}},
        "noise": {"class_type": "RandomNoise", "inputs": {
            "noise_seed": 930000 + shot_id * 149, "control_after_generate": "fixed"}},
        "guider": {"class_type": "BasicGuider", "inputs": {"model": ["unet", 0], "conditioning": ["i2v", 0]}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "sigmas": {"class_type": "BasicScheduler", "inputs": {
            "model": ["unet", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}},
        "sample": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0],
            "sigmas": ["sigmas", 0], "latent_image": ["i2v", 1]}},
        "vdecode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vvae", 0]}},
        "adecode": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sample", 0], "vae": ["avae", 0]}},
        "video": {"class_type": "CreateVideo", "inputs": {"images": ["vdecode", 0], "fps": 24, "audio": ["adecode", 0]}},
        "save": {"class_type": "SaveVideo", "inputs": {
            "video": ["video", 0], "filename_prefix": f"video/desert_keyframe_v3/{video_prefix(shot_id)}_S{shot_id:02d}",
            "format": "auto", "codec": "auto"}},
    }
    return {"prompt": nodes}


def generate_videos(mode):
    ids = {1, 4, 12} if mode == "demo" else set(VIDEO)
    os.makedirs(V_DIR, exist_ok=True)
    for shot_id in sorted(ids):
        if glob.glob(f"{V_DIR}/{video_prefix(shot_id)}_S{shot_id:02d}*.mp4"):
            print(f"[S{shot_id:02d}] exists, skip", flush=True)
            continue
        duration, description = VIDEO[shot_id]
        base.run(h3_i2v_workflow(shot_id, duration, description), f"DD3_S{shot_id:02d}")


def concatenate():
    segments = []
    for shot_id in sorted(VIDEO):
        files = glob.glob(f"{V_DIR}/{video_prefix(shot_id)}_S{shot_id:02d}*.mp4")
        if not files:
            raise RuntimeError(f"S{shot_id:02d} missing")
        segments.append(max(files, key=os.path.getmtime))
    list_path = "/root/story_test/dd3_concat.txt"
    with open(list_path, "w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(f"file '{segment}'\n")
    final = f"{V_DIR}/desert_keyframe_v3_final.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "160k", final,
    ], check=True)
    print(f"FINAL: {final}", flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "keyframes"
    if mode == "keyframes":
        generate_keyframes()
    elif mode == "demo":
        generate_videos("demo")
    elif mode == "full":
        generate_videos("full")
        concatenate()
    else:
        raise SystemExit("usage: desert_keyframe_v3.py keyframes|demo|full")


if __name__ == "__main__":
    main()
