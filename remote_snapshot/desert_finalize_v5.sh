#!/usr/bin/env bash
set -euo pipefail

input_dir=/workspace/ComfyUI/input
video_dir=/workspace/ComfyUI/output/video/desert_flat_v5
stage=/root/story_test/dd5_fixed_delivery
contacts="$stage/contacts"
archive=/root/story_test/desert_flat_v5_fixed_delivery.tgz

mkdir -p "$contacts"

ffmpeg -hide_banner -loglevel error -y \
  -loop 1 -i "$input_dir/dd5c_kf_S03.png" \
  -i "$video_dir/dd5_S03_00001_.mp4" \
  -filter_complex "[0:v]zoompan=z='min(zoom+0.00025,1.025)':d=1:s=544x960:fps=24,format=yuv420p[v]" \
  -map "[v]" -map 1:a:0 -t 6 -r 24 \
  -c:v libx264 -crf 18 -preset fast -c:a aac -b:a 160k \
  "$stage/S03_fixed.mp4"

cp "$video_dir/selected_S01.mp4" "$stage/S01.mp4"
cp "$video_dir/selected_S02.mp4" "$stage/S02.mp4"
for shot in 04 05 06 07 08 09 10 12; do
  cp "$video_dir/dd5_S${shot}_00001_.mp4" "$stage/S${shot}.mp4"
done

list=/root/story_test/dd5_fixed_concat.txt
printf '%s\n' \
  "file '$stage/S01.mp4'" \
  "file '$stage/S02.mp4'" \
  "file '$stage/S03_fixed.mp4'" \
  "file '$stage/S04.mp4'" \
  "file '$stage/S05.mp4'" \
  "file '$stage/S06.mp4'" \
  "file '$stage/S07.mp4'" \
  "file '$stage/S08.mp4'" \
  "file '$stage/S09.mp4'" \
  "file '$stage/S10.mp4'" \
  "file '$stage/S12.mp4'" > "$list"

ffmpeg -hide_banner -loglevel error -y \
  -f concat -safe 0 -i "$list" \
  -c:v libx264 -crf 18 -preset fast -c:a aac -b:a 160k \
  "$stage/desert_flat_v5_final_fixed.mp4"

ffmpeg -hide_banner -loglevel error -y \
  -i "$stage/desert_flat_v5_final_fixed.mp4" \
  -vf "fps=1/3,scale=220:388,tile=5x5" \
  -frames:v 1 "$contacts/final_contact_3s.jpg"

for shot in 01 02 03_fixed 04 05 06 07 08 09 10 12; do
  ffmpeg -hide_banner -loglevel error -y \
    -i "$stage/S${shot}.mp4" \
    -vf "fps=1,scale=272:480,tile=4x2" \
    -frames:v 1 "$contacts/S${shot}_contact.jpg"
done

ffprobe -v error \
  -show_entries format=duration,size:stream=index,codec_name,width,height,r_frame_rate,sample_rate,channels \
  -of json "$stage/desert_flat_v5_final_fixed.mp4" > "$contacts/final_probe.json"

tar -czf "$archive" -C /root/story_test dd5_fixed_delivery
echo "ARCHIVE: $archive"
