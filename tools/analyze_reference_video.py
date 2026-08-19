#!/usr/bin/env python3
"""Create metadata, scene candidates, and timestamped contact sheets for a video."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--scene-threshold", type=float, default=0.18)
    args = parser.parse_args()

    output = args.output.resolve()
    frames_dir = output / "frames_1fps"
    scenes_dir = output / "scene_candidates"
    contacts_dir = output / "contacts"
    for directory in (frames_dir, scenes_dir, contacts_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)

    probe = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(args.video),
        ],
        capture_output=True,
    )
    metadata = json.loads(probe.stdout)
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(args.video),
            "-vf",
            f"fps=1/{args.interval},scale=240:-2",
            "-q:v",
            "3",
            str(frames_dir / "frame_%04d.jpg"),
        ]
    )

    scene_filter = (
        f"select='gt(scene,{args.scene_threshold})',showinfo,scale=480:-2"
    )
    scene_proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(args.video),
            "-vf",
            scene_filter,
            "-vsync",
            "vfr",
            "-q:v",
            "2",
            str(scenes_dir / "scene_%03d.jpg"),
        ],
        check=True,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    scene_times = [float(value) for value in PTS_RE.findall(scene_proc.stderr)]
    (output / "scene_times.json").write_text(
        json.dumps(
            {"threshold": args.scene_threshold, "times_seconds": scene_times},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    frame_paths = sorted(frames_dir.glob("*.jpg"))
    columns, rows = 4, 5
    per_page = columns * rows
    tile_w, tile_h = 240, 436
    label_h = 24
    for page_index in range(math.ceil(len(frame_paths) / per_page)):
        page_frames = frame_paths[page_index * per_page : (page_index + 1) * per_page]
        canvas = Image.new("RGB", (columns * tile_w, rows * (tile_h + label_h)), "white")
        draw = ImageDraw.Draw(canvas)
        for cell, frame_path in enumerate(page_frames):
            with Image.open(frame_path) as image:
                image = image.convert("RGB")
                x = (cell % columns) * tile_w
                y = (cell // columns) * (tile_h + label_h)
                canvas.paste(image, (x, y))
                frame_number = int(frame_path.stem.split("_")[-1])
                seconds = (frame_number - 1) * args.interval
                draw.text((x + 6, y + tile_h + 4), f"t={seconds:05.1f}s", fill="black")
        canvas.save(contacts_dir / f"contact_{page_index + 1:02d}.jpg", quality=90)

    summary = {
        "video": str(args.video),
        "duration": float(metadata["format"]["duration"]),
        "interval": args.interval,
        "frame_count": len(frame_paths),
        "contact_pages": math.ceil(len(frame_paths) / per_page),
        "scene_candidates": len(scene_times),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
