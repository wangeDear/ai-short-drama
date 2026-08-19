#!/usr/bin/env python3
"""沙漠离网电力导演版 v5：三折软板全程平铺，优先物理连续性。"""
import glob
import os
import shutil
import subprocess
import sys

import desert_director_v2 as base
import desert_keyframe_v3 as v3


IN_DIR = base.IN_DIR
OUT_DIR = base.OUT_DIR
V3_DIR = f"{OUT_DIR}/video/desert_keyframe_v3"
V5_DIR = f"{OUT_DIR}/video/desert_flat_v5"
W, H = base.W, base.H


PANEL_RULE = (
    "Preserve the exact same ONE dark-blue THREE-SECTION soft fabric solar charger from image 1: three "
    "equal rectangular cell sections in one straight row, joined by two blue fabric hinges, lying completely "
    "FLAT on the same beige groundsheet. Preserve its cell pattern, blue border, size and cable. It must never "
    "stand upright or turn into a rigid panel. No tent, no metal frame, no kickstand, no extra solar panel. "
)


KEYFRAMES = [
    {"id": 5, "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"), "prompt": PANEL_RULE + (
        "Create an overhead field-documentary frame. The same woman's two worn black-gloved hands grip two "
        "opposite blue fabric corners and rotate the whole flat charger slightly on the cloth to face the sun. "
        "One olive backpack, exactly one pocket-size matte-black power bank, one coiled USB cable and one black "
        "brush sit at the edge of the cloth. No face, no duplicated gear, no text or logos, harsh real sun."
    )},
    {"id": 6, "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"), "prompt": PANEL_RULE + (
        "Create a medium rear-phone documentary frame. The same woman from image 2 kneels beside the fully "
        "visible flat charger, one hand shading the cells and the other resting on her knee. She looks toward "
        "the phone camera ready to explain. One olive backpack, one small black power bank, one cable and one "
        "brush only. Natural dusty tired face, one chest camera, no commercial pose, no text."
    )},
    {"id": 7, "refs": ("dd3_kf_S04.png",), "prompt": PANEL_RULE + (
        "Create a tight low insert of only the charger's lower-right blue fabric corner and metal eyelet. The "
        "same dusty khaki sleeves and worn black-gloved hands press one short dark sand peg into the dune. One "
        "thin white cord runs from that peg to this single eyelet. No face, no extra hands, tools or stakes."
    )},
    {"id": 8, "refs": ("dd3_kf_S04.png",), "prompt": PANEL_RULE + (
        "Create a macro phone frame over the center section. Fine dry sand coats the cells. One worn black "
        "glove holds one plain black soft brush, leaving a narrow clean strip behind it. Only one khaki sleeve "
        "enters frame. No water, no face, no extra brush, no text. Natural close focus."
    )},
    {"id": 9, "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"), "prompt": PANEL_RULE + (
        "Create a ground-level documentary frame. The same woman slides exactly one pocket-size matte-black "
        "USB power bank into the narrow shadow cast by the olive backpack and aligns the charger's one existing "
        "USB plug with it. The unchanged flat three-section charger remains clearly visible behind her. One "
        "black brush only. No large battery box, no duplicate wire, no text."
    )},
    {"id": 10, "refs": ("dd3_kf_S04.png",), "prompt": (
        "Create a tight daylight shaded insert on the same beige groundsheet. Exactly one pocket-size matte-black "
        "USB power bank sits partly under the same olive backpack, connected to the solar charger's one black "
        "cable. One scuffed smartphone lies beside it, connected by one short cable, screen angled away and "
        "unreadable. One tiny steady green hardware LED on the power bank conveys charging. One gloved thumb "
        "near the phone. No fake UI, no extra cable, no brush, no large battery, no night scene, no text."
    )},
    {"id": 11, "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"), "prompt": PANEL_RULE + (
        "Create a wide, slightly imperfect rear-phone documentary frame. Show the whole flat charger secured "
        "by exactly four short pegs and four thin white corner cords. Its single cable leads to exactly one "
        "pocket-size power bank shaded by one olive backpack. One phone and one black brush lie nearby. The same "
        "woman crouches at the far corner checking one cord. Everything fits on one groundsheet; no extra gear."
    )},
    {"id": 12, "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"), "prompt": PANEL_RULE + (
        "Create the final golden-hour rear-phone medium frame. Preserve the same woman's natural face, dusty "
        "clothes and single chest camera from image 2. She sits on the groundsheet just beyond the fully visible "
        "flat charger and holds one charging phone loosely with its screen toward herself and away from camera. "
        "The single cable leads to one small power bank under the backpack edge. Exhausted relief, low sun, wind "
        "in loose hair, restrained color. No added objects, fake UI or text."
    )},
]


REFINEMENTS = [
    {"id": 8, "refs": ("dd5_kf_S08.png",), "prompt": (
        "Edit image 1 while preserving its exact camera angle, four-section blue fabric solar charger, sand, "
        "groundsheet, sleeve and glove. Remove the large empty black rectangular frame lying across the solar "
        "cells completely. Show exactly one ordinary small black bristle brush held by the gloved hand, its "
        "bristles touching the dusty cells and leaving one narrow clean strip. No other object, cable, frame, "
        "screen, tool, text or logo. Photorealistic documentary macro."
    )},
    {"id": 10, "refs": ("dd5_kf_S10.png",), "prompt": (
        "Edit image 1 while preserving the same daylight, olive backpack, beige cloth, glove and solar panel "
        "edge. Keep exactly TWO electronic objects only: one scuffed black smartphone lying on the cloth and "
        "one pocket-size matte-black power bank partly inside the backpack. Remove the second handheld phone-like "
        "device entirely. One short cable connects the phone to the power bank; one solar cable enters the power "
        "bank. A single tiny green LED glows on the power bank. Phone screen stays dark and unreadable. No text."
    )},
    {"id": 11, "refs": ("dd5_kf_S11.png",), "prompt": (
        "Edit image 1 while preserving its camera angle, exact four-section blue fabric solar charger, woman, "
        "backpack, groundsheet, black brush and desert. Remove every white cord crossing over the solar cells. "
        "Show only two thin white safety cords, each attached to an OUTER corner eyelet and running outward across "
        "the cloth to one short dark sand peg beyond the panel. Remove the device sitting on top of the backpack. "
        "Keep one small power bank tucked beside the backpack and one black cable. No extra gear, no glowing knots."
    )},
    {"id": 12, "refs": ("dd5_kf_S12.png",), "prompt": (
        "Edit image 1 while preserving the exact woman's face, dusty clothing, one chest camera, sunset, flat "
        "four-section blue charger, groundsheet, backpack and phone in her hand. Remove the electronic device "
        "hanging from her right hip and remove its cable completely. Keep exactly one pocket-size matte-black "
        "power bank on the groundsheet beside the panel with one cable. Turn the handheld phone screen fully away "
        "from camera. No other object, screen, UI, text or logo. Natural exhausted documentary portrait."
    )},
]


FINAL_REFINEMENTS = [
    {"id": 3, "refs": ("dd5_kf_S05.png", "dd2_hero_v2.png"), "prompt": (
        "Using the exact dark-blue FOUR-SECTION fabric solar charger design, cell pattern and blue borders from "
        "image 1, create a locked overhead documentary frame one moment before it is opened. The charger is "
        "folded accordion-style into one compact rectangular stack on a beige groundsheet; four equal fabric "
        "layers are visibly aligned along one side. Only the same woman's dusty khaki sleeves and two black "
        "gloved hands hold the folded stack. One olive backpack, one pocket-size black power bank, one coiled "
        "USB cable and one black brush. No deployed panel, face, duplicate gear, tent, text or logo."
    )},
    {"id": 4, "refs": ("dd5_kf_S05.png",), "prompt": (
        "Preserve the exact same ONE dark-blue FOUR-SECTION soft fabric solar charger from image 1, including "
        "all four equal cell sections, three blue fabric hinges, border, size and cable. Lay it completely flat "
        "on the same beige groundsheet. Create a tight over-shoulder documentary test frame: one worn black glove "
        "holds a single small unbranded USB meter at the panel edge while the other glove shades its screen. The "
        "screen shows one weak generic blue bar only, with no readable numbers or text. No stand or extra device."
    )},
    {"id": 6, "refs": ("dd5_kf_S06.png",), "prompt": (
        "Edit image 1 while preserving the exact woman's face, dusty clothing, single chest camera, kneeling "
        "pose, flat blue four-section solar charger, beige groundsheet, olive backpack, black brush and desert. "
        "Remove the smartphone and cable from her raised hand completely; her empty gloved hand shades her eyes. "
        "Remove the background tent completely. Keep exactly one pocket-size matte-black power bank beside the "
        "charger and remove any second phone-like object. Natural hard daylight, no new gear, no text or logo."
    )},
    {"id": 10, "refs": ("dd5b_kf_S10.png",), "prompt": (
        "Recompose image 1 as a tight macro crop showing ONLY the single matte-black pocket-size power bank partly "
        "inside the olive backpack pocket. One solar USB cable enters it. Preserve the tiny steady green hardware "
        "LED. Exclude every phone, handheld device, solar panel, hand and other electronics from the frame. Beige "
        "groundsheet at the edge, natural daylight shadow, photorealistic documentary detail, no text or logo."
    )},
    {"id": 11, "refs": ("dd5_kf_S05.png", "dd2_hero_v2.png"), "prompt": (
        "Using the exact same ONE blue FOUR-SECTION fabric solar charger from image 1, create a wide imperfect "
        "rear-phone documentary frame. The entire charger lies completely flat and unchanged on one beige "
        "groundsheet. One black cable leads to one pocket-size power bank shaded by one olive backpack. The same "
        "woman from image 2 crouches at the far edge and presses one blue fabric corner flat with one hand. One "
        "black brush lies beside the bag. No white cords, no stakes, no tent, no extra device, no text or logo."
    )},
]


VIDEO = {
    3: (6, "Locked overhead shot. The two gloved hands unfold exactly one layer of the same accordion stack, reveal the four-section blue fabric charger, flatten its two outer corners, then pause. Object count and construction remain unchanged. No talking."),
    4: (5, "Tight over-shoulder insert. One glove slowly tilts the single USB meter toward camera while its weak generic blue bar flickers once; the other glove continues shading it. The complete flat four-section charger stays unchanged. No talking."),
    5: (5, "Locked overhead shot. Her two hands rotate the same complete flat four-section charger a few degrees clockwise on the groundsheet, flatten both corners, then release. It remains soft, flat and unchanged. No talking."),
    6: (7, "Rear-phone medium shot. She shades the flat charger's cells with one hand, gestures once to its four corners and reports calmly. <Subject1> (S1) says, [Chinese] `沙地太软，支架反而不稳。我把板铺平、四角固定，先保证不断电。` Restrained lip sync; charger and gear stay fixed."),
    7: (5, "Low locked close shot. She presses the one short peg deeper once and pulls the attached thin cord once. The charger's blue fabric corner stops fluttering. No duplicated hands, tools or gear. No talking."),
    8: (5, "Macro locked shot. The single soft brush makes one slow complete stroke across the same cells. A thin veil of dry sand falls off and one clean strip remains. No water, no talking."),
    9: (5, "Ground-level locked shot. She slides the pocket-size power bank farther into the backpack's shadow and inserts the single aligned USB plug once. Flat charger, cable path and brush remain unchanged. No talking."),
    10: (5, "Locked daylight macro. The single cable settles naturally, then the power bank's tiny green hardware LED turns on and stays steady. The one power bank and backpack pocket remain rigid and unchanged. No hands, no phones and no talking."),
    12: (8, "Golden-hour rear-phone medium shot. She raises the charging phone slightly while keeping its screen toward herself, looks into the lens and speaks with tired relief. <Subject1> (S1) says, [Chinese] `电量在回升，导航也保住了。沙漠里，先保住通信，再谈舒服。` Natural restrained lip sync; she lowers the phone and exhales. The exact flat portable setup remains fixed."),
}


FINAL_C_IDS = {3, 4, 6, 10, 11}
REFINED_B_IDS = {8, 12}


def kf_name(shot_id):
    if shot_id in FINAL_C_IDS:
        prefix = "dd5c"
    elif shot_id in REFINED_B_IDS:
        prefix = "dd5b"
    else:
        prefix = "dd5"
    return f"{prefix}_kf_S{shot_id:02d}.png"


def generate_keyframes():
    for item in KEYFRAMES:
        destination = f"{IN_DIR}/{kf_name(item['id'])}"
        if os.path.exists(destination):
            print(f"[KF5 S{item['id']:02d}] exists, skip", flush=True)
            continue
        files = base.run(base.qwen_workflow(
            item["prompt"], f"desert_flat_v5/kf_S{item['id']:02d}", item["refs"],
            950000 + item["id"] * 103,
        ), f"KF5_S{item['id']:02d}")
        shutil.copy(files[0], destination)


def generate_refinements():
    for item in REFINEMENTS:
        destination = f"{IN_DIR}/dd5b_kf_S{item['id']:02d}.png"
        if os.path.exists(destination):
            print(f"[KF5B S{item['id']:02d}] exists, skip", flush=True)
            continue
        files = base.run(base.qwen_workflow(
            item["prompt"], f"desert_flat_v5/refined_S{item['id']:02d}", item["refs"],
            955000 + item["id"] * 107,
        ), f"KF5B_S{item['id']:02d}")
        shutil.copy(files[0], destination)


def generate_final_refinements():
    for item in FINAL_REFINEMENTS:
        destination = f"{IN_DIR}/dd5c_kf_S{item['id']:02d}.png"
        if os.path.exists(destination):
            print(f"[KF5C S{item['id']:02d}] exists, skip", flush=True)
            continue
        files = base.run(base.qwen_workflow(
            item["prompt"], f"desert_flat_v5/final_S{item['id']:02d}", item["refs"],
            958000 + item["id"] * 109,
        ), f"KF5C_S{item['id']:02d}")
        shutil.copy(files[0], destination)


def h3_workflow(shot_id, duration, description):
    old_path, old_prefix = v3.keyframe_path, v3.video_prefix
    try:
        v3.keyframe_path = lambda _: kf_name(shot_id)
        v3.video_prefix = lambda _: "dd5"
        workflow = v3.h3_i2v_workflow(shot_id, duration, description)
        workflow["prompt"]["save"]["inputs"]["filename_prefix"] = f"video/desert_flat_v5/dd5_S{shot_id:02d}"
        return workflow
    finally:
        v3.keyframe_path, v3.video_prefix = old_path, old_prefix


def generate_videos():
    os.makedirs(V5_DIR, exist_ok=True)
    for shot_id in sorted(VIDEO):
        if glob.glob(f"{V5_DIR}/dd5_S{shot_id:02d}*.mp4"):
            print(f"[V5 S{shot_id:02d}] exists, skip", flush=True)
            continue
        duration, description = VIDEO[shot_id]
        base.run(h3_workflow(shot_id, duration, description), f"DD5_S{shot_id:02d}")


def concatenate():
    segments = []
    for shot_id in [1, 2, *sorted(VIDEO)]:
        if shot_id == 1:
            pattern = f"{V3_DIR}/dd3c_S01*.mp4"
        elif shot_id == 2:
            pattern = f"{V3_DIR}/dd3_S{shot_id:02d}*.mp4"
        else:
            pattern = f"{V5_DIR}/dd5_S{shot_id:02d}*.mp4"
        files = glob.glob(pattern)
        if not files:
            raise RuntimeError(f"S{shot_id:02d} missing: {pattern}")
        segments.append(max(files, key=os.path.getmtime))
    list_path = "/root/story_test/dd5_concat.txt"
    with open(list_path, "w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(f"file '{segment}'\n")
    final = f"{V5_DIR}/desert_flat_v5_final.mp4"
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
    elif mode == "refine":
        generate_refinements()
    elif mode == "final_refine":
        generate_final_refinements()
    elif mode == "full":
        generate_videos()
        concatenate()
    else:
        raise SystemExit("usage: desert_flat_v5.py keyframes|refine|final_refine|full")


if __name__ == "__main__":
    main()
