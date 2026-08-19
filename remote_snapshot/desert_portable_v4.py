#!/usr/bin/env python3
"""沙漠离网电力导演版 v4：统一为背包可携带的三折柔性太阳能板。"""
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
V4_DIR = f"{OUT_DIR}/video/desert_portable_v4"
W, H = base.W, base.H


KEYFRAMES = [
    {
        "id": 5,
        "refs": ("dd3_kf_S04.png", "dd2_hero_v2.png"),
        "prompt": (
            "Use the exact same compact dark-blue THREE-SECTION fabric folding solar charger shown in "
            "image 1; preserve its size, cell pattern, blue fabric border and two hinges exactly. Create a "
            "static vertical side documentary frame with the same woman from image 2 kneeling on the beige "
            "groundsheet. She raises only the far edge about 25 degrees and opens the charger's two tiny "
            "integrated fabric kickstands behind it. This remains a backpack-size soft charger, about 70 cm "
            "wide when open, not a rigid roof and not a large array. One olive backpack, one black power bank, "
            "one coiled USB cable and one black brush remain on the cloth. No aluminum frame, no tripod, no "
            "power station, no extra panel, no text or logos. Harsh natural desert sun, candid phone footage."
        ),
    },
    {
        "id": 6,
        "refs": ("dd4_kf_S05.png", "dd2_hero_v2.png"),
        "prompt": (
            "Continue the exact same moment and preserve every object from image 1: one small dark-blue "
            "three-section soft folding solar charger tilted only 25 degrees on its tiny fabric kickstands, "
            "one olive backpack, one pocket-size black power bank, one USB cable and one black brush. The same "
            "woman from image 2 kneels beside the charger, one gloved hand lightly holding its upper fabric "
            "edge and the other resting on her knee. She looks toward a phone camera ready to explain. Keep "
            "the charger's backpackable scale and construction unchanged. No rigid solar modules, no metal "
            "legs, no big battery box, no duplicate gear, no text. Tired dusty face, hard midday sun."
        ),
    },
    {
        "id": 7,
        "refs": ("dd4_kf_S06.png",),
        "prompt": (
            "Create a tight low documentary insert of the lower right corner of the exact same small blue "
            "three-section fabric solar charger from image 1. Preserve its soft blue border, size and tiny "
            "kickstand. The same woman's worn black-gloved hands press one short dark sand peg into the dune. "
            "A single thin white cord is tied from that peg to the charger's corner eyelet so wind cannot flip "
            "it. Only dusty khaki sleeves enter frame. No metal array, no long pole, no tool, no extra hands, "
            "no extra stakes and no text. Real sand compression and harsh sunlight."
        ),
    },
    {
        "id": 8,
        "refs": ("dd4_kf_S06.png",),
        "prompt": (
            "Create a macro phone-camera frame of the exact same compact blue THREE-SECTION fabric solar "
            "charger in image 1. Keep the same cell pattern and blue seams. Fine dry sand coats the cells. One "
            "worn black glove holds the same plain black soft brush at the top, leaving one narrow clean strip "
            "behind it. Only one dusty khaki sleeve enters frame. No water, no metal frame, no extra panel, "
            "no face, no text or logos. Natural close focus and imperfect field-documentary composition."
        ),
    },
    {
        "id": 9,
        "refs": ("dd4_kf_S06.png", "dd2_hero_v2.png"),
        "prompt": (
            "Create a ground-level documentary frame continuing image 1. Preserve the same one small blue "
            "three-section fabric solar charger, tilted on tiny fabric kickstands, with the same backpackable "
            "scale. The same woman from image 2 slides exactly one pocket-size matte-black USB power bank into "
            "the narrow shadow beneath the olive backpack and aligns one existing USB cable plug with it. The "
            "charger remains visible behind her and unchanged. One brush lies on the cloth. No large power "
            "station, no rigid panel, no duplicate wire, no readable text."
        ),
    },
    {
        "id": 10,
        "refs": ("dd4_kf_S09.png",),
        "prompt": (
            "Create a tight shaded insert using the exact same pocket-size matte-black power bank, USB cable, "
            "olive backpack and beige groundsheet from image 1. A scuffed smartphone lies beside the power bank "
            "connected by one short cable. The phone screen is angled away and shows no readable UI; charging "
            "is conveyed only by one tiny steady green hardware LED on the power bank. One gloved thumb rests "
            "near the phone. No fake screen text, no extra cables, no large battery box, no night scene."
        ),
    },
    {
        "id": 11,
        "refs": ("dd4_kf_S09.png", "dd2_hero_v2.png"),
        "prompt": (
            "Create a slightly imperfect wide rear-phone documentary frame of the exact small portable setup "
            "from image 1. Show one backpack-size blue three-section fabric solar charger low on tiny fabric "
            "kickstands, exactly two thin cords to two short sand pegs, one USB cable leading to one pocket-size "
            "power bank shaded by the same olive backpack, one phone and one black brush. The same woman from "
            "image 2 crouches at the far corner checking one cord. Everything fits on one beige groundsheet. "
            "No large rigid array, no aluminum legs, no tent, no extra device, no commercial composition."
        ),
    },
    {
        "id": 12,
        "refs": ("dd4_kf_S11.png", "dd2_hero_v2.png"),
        "prompt": (
            "Create the final golden-hour rear-phone medium frame and preserve the exact portable camp from "
            "image 1: one small blue three-section fabric charger on low kickstands, two cords and pegs, one "
            "USB cable, one pocket-size power bank in the backpack's shade, one phone and one brush. Preserve "
            "the exact same woman's natural face, dusty clothes and single chest camera from image 2. She sits "
            "on the beige groundsheet and loosely holds the charging phone with its screen turned toward her, "
            "away from camera. Exhausted relief, not triumph; wind-loosened hair, low sun, restrained color. "
            "No rigid panel, no big battery, no new objects, no readable UI or text."
        ),
    },
]


VIDEO = {
    5: (5, "Static medium side shot. She unfolds the two tiny fabric kickstands until they settle, gently lowers the same small three-section soft charger onto them, then releases one hand. The charger keeps the exact same size and construction. No talking."),
    6: (7, "Rear-camera medium close shot. Keeping one hand lightly on the small charger's fabric edge, she points at its low angle and reports calmly. <Subject1> (S1) says, [Chinese] `这块折叠板功率不大，但给手机和导航续命够用。支低一点，也不容易被风掀翻。` Restrained natural lip sync; all equipment stays fixed."),
    7: (5, "Low locked close shot. She presses the one short peg deeper once, pulls the attached thin cord once, and the small charger's corner stops fluttering. No duplicated hands, tools or gear. No talking."),
    8: (5, "Macro locked shot. The soft brush makes one slow complete downward stroke. A thin veil of dry sand falls away, revealing the same blue cells and fabric seams. No water and no talking."),
    9: (5, "Ground-level locked shot. She slides the pocket-size power bank fully into the backpack's shadow and inserts the single aligned USB plug once. The small charger, cable path and brush remain unchanged. No talking."),
    10: (5, "Locked shaded insert. The gloved thumb wakes the phone once while its screen remains oblique and unreadable; the power bank's tiny green hardware LED turns on and stays steady. Devices and cables do not morph. No talking."),
    11: (6, "A restrained human-operated phone move travels slowly from the two pegged corners of the small blue charger along its single cable to the shaded pocket power bank, ending on the woman checking one cord. No orbit, no drone move, no equipment changes and no talking."),
    12: (8, "Golden-hour rear-phone medium shot. She raises the charging phone slightly while keeping its screen toward herself, looks into the lens and speaks with tired relief. <Subject1> (S1) says, [Chinese] `电量在回升，导航也保住了。沙漠里，先保住通信，再谈舒服。` Natural restrained lip sync; she lowers the phone and exhales. The exact small portable setup remains fixed."),
}


def kf_name(shot_id):
    return f"dd4_kf_S{shot_id:02d}.png"


def generate_keyframes():
    for item in KEYFRAMES:
        destination = f"{IN_DIR}/{kf_name(item['id'])}"
        if os.path.exists(destination):
            print(f"[KF4 S{item['id']:02d}] exists, skip", flush=True)
            continue
        files = base.run(
            base.qwen_workflow(
                item["prompt"],
                f"desert_portable_v4/kf_S{item['id']:02d}",
                item["refs"],
                940000 + item["id"] * 101,
            ),
            f"KF4_S{item['id']:02d}",
        )
        shutil.copy(files[0], destination)


def h3_workflow(shot_id, duration, description):
    original = v3.keyframe_path
    original_prefix = v3.video_prefix
    try:
        v3.keyframe_path = lambda _: kf_name(shot_id)
        v3.video_prefix = lambda _: "dd4"
        workflow = v3.h3_i2v_workflow(shot_id, duration, description)
        workflow["prompt"]["save"]["inputs"]["filename_prefix"] = (
            f"video/desert_portable_v4/dd4_S{shot_id:02d}"
        )
        return workflow
    finally:
        v3.keyframe_path = original
        v3.video_prefix = original_prefix


def generate_videos():
    os.makedirs(V4_DIR, exist_ok=True)
    for shot_id in sorted(VIDEO):
        if glob.glob(f"{V4_DIR}/dd4_S{shot_id:02d}*.mp4"):
            print(f"[V4 S{shot_id:02d}] exists, skip", flush=True)
            continue
        duration, description = VIDEO[shot_id]
        base.run(h3_workflow(shot_id, duration, description), f"DD4_S{shot_id:02d}")


def concatenate():
    segments = []
    for shot_id in range(1, 13):
        if shot_id == 1:
            pattern = f"{V3_DIR}/dd3c_S01*.mp4"
        elif shot_id <= 4:
            pattern = f"{V3_DIR}/dd3_S{shot_id:02d}*.mp4"
        else:
            pattern = f"{V4_DIR}/dd4_S{shot_id:02d}*.mp4"
        files = glob.glob(pattern)
        if not files:
            raise RuntimeError(f"S{shot_id:02d} missing: {pattern}")
        segments.append(max(files, key=os.path.getmtime))
    list_path = "/root/story_test/dd4_concat.txt"
    with open(list_path, "w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(f"file '{segment}'\n")
    final = f"{V4_DIR}/desert_portable_v4_final.mp4"
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
    elif mode == "videos":
        generate_videos()
    elif mode == "full":
        generate_videos()
        concatenate()
    else:
        raise SystemExit("usage: desert_portable_v4.py keyframes|videos|full")


if __name__ == "__main__":
    main()
