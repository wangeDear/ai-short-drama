#!/usr/bin/env bash
set -euo pipefail

v3_dir=/workspace/ComfyUI/output/video/desert_keyframe_v3
video_dir=/workspace/ComfyUI/output/video/desert_flat_v5
contact_dir=/root/story_test/dd5_contacts
archive=/root/story_test/desert_flat_v5_delivery.tgz

mkdir -p "$contact_dir"
cp "$v3_dir/dd3c_S01_00001_.mp4" "$video_dir/selected_S01.mp4"
cp "$v3_dir/dd3_S02_00001_.mp4" "$video_dir/selected_S02.mp4"

ffmpeg -hide_banner -loglevel error -y \
  -i "$video_dir/desert_flat_v5_final.mp4" \
  -vf "fps=1/3,scale=220:388,tile=5x5" \
  -frames:v 1 "$contact_dir/final_contact_3s.jpg"

shots=(01 02 03 04 05 06 07 08 09 10 12)
for shot in "${shots[@]}"; do
  if [[ "$shot" == "01" || "$shot" == "02" ]]; then
    input="$video_dir/selected_S${shot}.mp4"
  else
    input=$(find "$video_dir" -maxdepth 1 -type f -name "dd5_S${shot}_*.mp4" | sort | tail -n 1)
  fi
  if [[ -z "$input" || ! -f "$input" ]]; then
    echo "Missing S${shot}" >&2
    exit 1
  fi
  ffmpeg -hide_banner -loglevel error -y \
    -i "$input" \
    -vf "fps=1,scale=272:480,tile=4x2" \
    -frames:v 1 "$contact_dir/S${shot}_contact.jpg"
done

ffprobe -v error \
  -show_entries format=duration,size:stream=index,codec_name,width,height,r_frame_rate,sample_rate,channels \
  -of json "$video_dir/desert_flat_v5_final.mp4" > "$contact_dir/final_probe.json"

tar -czf "$archive" \
  -C "$video_dir" . \
  -C /root/story_test dd5_contacts

echo "ARCHIVE: $archive"
