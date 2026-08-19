#!/usr/bin/env bash
set -euo pipefail

video_dir=/workspace/ComfyUI/output/video/desert_keyframe_v3
contact_dir=/root/story_test/dd3_contacts
archive=/root/story_test/desert_keyframe_v3_delivery.tgz

mkdir -p "$contact_dir"

ffmpeg -hide_banner -loglevel error -y \
  -i "$video_dir/desert_keyframe_v3_final.mp4" \
  -vf "fps=1/3,scale=220:388,tile=5x5" \
  -frames:v 1 "$contact_dir/final_contact_3s.jpg"

for shot in $(seq -w 1 12); do
  prefix=dd3
  if [[ "$shot" == "01" ]]; then
    prefix=dd3c
  fi
  input=$(find "$video_dir" -maxdepth 1 -type f -name "${prefix}_S${shot}_*.mp4" | sort | tail -n 1)
  if [[ -z "$input" ]]; then
    echo "Missing S${shot}" >&2
    exit 1
  fi
  ffmpeg -hide_banner -loglevel error -y \
    -i "$input" \
    -vf "fps=1,scale=272:480,tile=4x2" \
    -frames:v 1 "$contact_dir/S${shot}_contact.jpg"
done

ffprobe -v error -show_entries format=duration,size:stream=index,codec_name,width,height,r_frame_rate,sample_rate,channels \
  -of json "$video_dir/desert_keyframe_v3_final.mp4" > "$contact_dir/final_probe.json"

tar -czf "$archive" \
  -C "$video_dir" . \
  -C /root/story_test dd3_contacts

echo "ARCHIVE: $archive"
