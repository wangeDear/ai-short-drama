#!/usr/bin/env python3
"""沙漠篇·段落式叙事实验: S05→S06→S07 搭建段落
伪长镜头三件套: ①单镜拉长(12/12/14s) ②帧链接(上镜尾帧=下镜参考图3)
③环境音贯穿拼接(风声bed盖接缝)
"""
import json, os, time, urllib.request, shutil, glob, subprocess

BASE = "http://127.0.0.1:8188"
IN_DIR = "/workspace/ComfyUI/input"
OUT_DIR = "/workspace/ComfyUI/output"
V_DIR = f"{OUT_DIR}/video/desert_seg"
W, H = 544, 960
STATUS = "/root/story_test/status_seg.json"

HERO = ("a Chinese woman in her early 30s, dark hair in a practical low ponytail, khaki "
        "quick-dry outdoor jacket, sand-colored tactical neck gaiter pulled down around her "
        "neck, black tactical gloves, GoPro chest mount — a desert survival tech vlog host")
OTHER = ("Realistic vertical vlog footage, 9:16, authentic handheld phone camera, harsh "
         "desert sunlight, hard shadows, sun flare, documentary realism. ")
EVE = ("Realistic vertical vlog footage, 9:16, warm golden sunset light, long hard shadows, "
       "handheld phone camera, documentary realism. ")
NOTEXT = "Absolutely no subtitles, no on-screen text, no watermark. "
NEG = "text, subtitle, caption, watermark, lowres, blurry, deformed, extra limbs, cartoon, 3D render, other people"
LINK_NOTE = ("<Picture {n}> is a continuity reference frame: the exact final moment of the "
             "previous shot — <Subject1>'s pose, the props and the panel position continue "
             "directly from this frame.")


def h3_len(sec):
    n = max(5, round(sec * 24))
    r = n % 17
    if r != 5: n += (5 - r) % 17
    return n


def sp6(body, soundscape, n_refs=2):
    extra = ("\n" + LINK_NOTE.format(n=3) if n_refs == 3 else "")
    retention = ("<Picture 1>: fully_preserved — <Subject1>'s face, ponytail, outfit and gear must match exactly.\n"
                 "<Picture 2>: weak_reference — only the desert setting and daylight.")
    if n_refs == 3:
        retention += "\n<Picture 3>: weak_reference — continuity of pose and prop positions from the previous moment."
    return ("subject_definitions:\n"
            f"<Subject1> is {HERO}, visual identity from <Picture 1>.\n"
            "<Picture 2> shows the desert location and lighting: vast golden dunes, harsh sun." + extra + "\n\n"
            "summary: [reference generation] A vertical vlog clip of the host building her off-grid power setup in a vast golden desert, continuous action.\n\n"
            "retention_analysis:\n" + retention + "\n\n"
            f"detailed_description: {body}\n\n"
            f"overall_soundscape: {soundscape}.\n\n"
            "non_diegetic_music: none.\n")


def talk(lines, lead="She speaks Mandarin Chinese clearly to the camera, lips moving in natural sync:"):
    parts = []
    for t in lines:
        parts.append(f"{lead} <Subject1> (S1) says, [Chinese] `{t}`")
        lead = "She continues speaking Mandarin with precise lip-sync:"
    return " ".join(parts) + " She closes her mouth at the end."


# 段落 3 镜(承接式: 尾状态=下镜入场状态)
def shots():
    return [
        dict(id=5, dur=12, link_from=None, prompt=sp6(
            OTHER + "Medium side view, continuous from the previous moment: <Subject1> kneels beside the deep-blue solar panel lying flat on the sand. She picks up a dry dead stick and stones, props one edge of the panel up into a tilt angle, wedging the stick firmly. Wind gusts blow sand across the frame; she presses one gloved hand down on the panel. While bracing it she speaks to the camera, lip-sync clear: " +
            talk(["先拿枯木和石头支个倾角，先顶一下。风有点大，我先按住板子，别让它翻了。"]) +
            " She stays kneeling, hand pressing the panel, looking at her work.",
            "steady desert wind bed, wood knocking on stone, sand hissing across fabric", 2)),
        dict(id=6, dur=12, link_from="seg_S05", prompt=sp6(
            OTHER + "Continuous action: <Subject1>'s gloved hand still presses on the tilted solar panel; the wooden stick prop visibly trembles and rattles in the wind. She looks up at the shaking stick, still holding the panel, and speaks with a wry grin: " +
            talk(["不行，木头支架一直在抖，风一吹就晃，这么下去迟早要断。撤了，直接上专业装备。"]) +
            " She pulls the stick out and tosses it aside, reaching for her backpack.",
            "steady desert wind bed, creaking trembling wood, rattling panel", 3)),
        # S07 拆解为 4 个原子动作镜(手部特写为主, 快切蒙太奇)
        dict(id=71, dur=6, link_from="seg_S06", prompt=sp6(
            OTHER + "Extreme close-up, overhead angle: her two gloved hands work above an open equipment case. The right hand picks up one silver aluminum tube; the left hand picks up a black three-way joint, aligns it to the tube end and pushes it in with a firm click. Only this single action, slow and deliberate, fingers clearly gripping. She speaks briefly off-camera: " +
            talk(["铝合金管，配三通接头。"], lead="Her voice continues off-screen, calm and technical:") +
            " Hands pause on the connected pieces.",
            "aluminum tube clinking in case, plastic joint click, steady desert wind bed", 3)),
        dict(id=72, dur=6, link_from="seg_S71", prompt=sp6(
            OTHER + "Extreme close-up: a ratchet wrench socket seats onto the joint screw; her hand rotates the wrench three firm turns, each with a metallic ratcheting click, the connection tightening visibly. One single action, close on hands and tool. " +
            talk(["一颗一颗，拧紧。"], lead="Off-screen voice, precise lip-sync:") +
            " The wrench stops turning.",
            "ratchet wrench clicks, metal friction, steady desert wind bed", 3)),
        dict(id=73, dur=8, link_from="seg_S72", prompt=sp6(
            EVE + "Medium close view: a half-built silver aluminum frame stands on the sand; she slides one more tube into the top three-way joint, taps it home with her palm, then squares the frame with both hands. The structure visibly grows one piece at a time. She speaks while working: " +
            talk(["框架一根一根接起来，结构这就出来了。"], lead="She speaks over her shoulder while assembling, lip-sync clear:") +
            " She steadies the finished frame.",
            "tube sliding into joint, palm tap, frame settling into sand, evening wind", 3)),
        dict(id=74, dur=8, link_from="seg_S73", prompt=sp6(
            EVE + "Continuous: she lifts the deep-blue solar panel from the sand and lowers it onto the finished aluminum frame, hands aligning the mounting holes, pressing each corner clamp down until it clicks. Then she tilts the whole panel up by adjusting the frame hinge, warm sunset light catching the surface. She speaks with quiet satisfaction: " +
            talk(["板子固定上去，角度还能调。这才像话，专业的事，就得用专业的家伙。"]) +
            " She pats the mounted panel once.",
            "panel clamps clicking, hinge creak adjusting, evening wind, satisfied tone", 3)),
    ]


def status(**kw):
    cur = json.load(open(STATUS)) if os.path.exists(STATUS) else {}
    cur.update(kw, ts=time.strftime("%H:%M:%S"))
    json.dump(cur, open(STATUS, "w"), ensure_ascii=False, indent=1)


def post(path, payload=None):
    req = urllib.request.Request(BASE + path,
        data=json.dumps(payload).encode() if payload is not None else b"{}",
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


def run(wf, tag):
    pid = post("/prompt", wf)["prompt_id"]
    status(stage=tag, done=False, error="")
    print(f"[{tag}] submitted", flush=True)
    t0 = time.time()
    while True:
        time.sleep(8)
        h = json.loads(urllib.request.urlopen(BASE + f"/history/{pid}", timeout=300).read())
        if pid not in h: continue
        info = h[pid]
        files = []
        for o in info.get("outputs", {}).values():
            for f in (o.get("videos") or o.get("images") or []):
                files.append(os.path.join(OUT_DIR, f.get("subfolder", ""), f["filename"]))
        if files:
            status(stage=tag, done=True, secs=round(time.time() - t0))
            print(f"[{tag}] DONE {round(time.time()-t0)}s", flush=True)
            return files
        for m in info.get("status", {}).get("messages", []):
            if m[0] == "execution_error":
                status(stage=tag, done=True, error=str(m[1].get("exception_message", ""))[:200])
                raise RuntimeError(f"{tag}: {m[1].get('node_type')}: {m[1].get('exception_message','')[:300]}")
        if time.time() - t0 > 1800:
            raise RuntimeError(f"{tag} timeout")


def h3_wf(shot, extra_refs):
    n = {}
    n["unet"] = {"class_type": "UNETLoader",
                 "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}}
    n["clip"] = {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}}
    n["vvae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}}
    n["avae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}}
    n["noise"] = {"class_type": "RandomNoise",
                  "inputs": {"noise_seed": 995000 + shot["id"] * 31, "control_after_generate": "fixed"}}
    n["guider"] = {"class_type": "BasicGuider", "inputs": {"model": ["unet", 0], "conditioning": ["i2v", 0]}}
    n["samp"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    n["sig"] = {"class_type": "BasicScheduler", "inputs": {"model": ["unet", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}}
    n["vdec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sc", 0], "vae": ["vvae", 0]}}
    n["adec"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sc", 0], "vae": ["avae", 0]}}
    n["cv"] = {"class_type": "CreateVideo", "inputs": {"images": ["vdec", 0], "fps": 24, "audio": ["adec", 0]}}
    n["save"] = {"class_type": "SaveVideo", "inputs": {
        "video": ["cv", 0], "filename_prefix": f"video/desert_seg/seg_S{shot['id']:02d}",
        "format": "auto", "codec": "auto"}}
    refs = ["dh_hero.png", "sd_desert.png"] + extra_refs
    ref_imgs = []
    for i, r in enumerate(refs, 1):
        n[f"load{i}"] = {"class_type": "LoadImage", "inputs": {"image": r}}
        ref_imgs.append([f"load{i}", 0])
    n["i2v"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
        "clip": ["clip", 0], "vae": ["vvae", 0], "audio_vae": ["avae", 0],
        "prompt": shot["prompt"] + " " + NOTEXT, "width": W, "height": H,
        "length": h3_len(shot["dur"]), "ref_image_size": "match", "ref_images": ref_imgs}}
    n["sc"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["samp", 0],
        "sigmas": ["sig", 0], "latent_image": ["i2v", 1]}}
    return {"prompt": n}


def extract_last_frame(video, name):
    dst = f"{IN_DIR}/{name}.png"
    subprocess.run(["ffmpeg", "-y", "-sseof", "-0.1", "-i", video, "-update", "1",
                    "-frames:v", "1", dst], check=True, capture_output=True)
    return name + ".png"


def latest(prefix):
    fs = glob.glob(f"{V_DIR}/{prefix}*.mp4")
    if not fs: raise RuntimeError(f"no video {prefix}")
    return sorted(fs, key=os.path.getmtime)[-1]


def main():
    os.makedirs(V_DIR, exist_ok=True)
    status(stage="start", done=False, error="")
    prev_file = None
    for s in shots():
        if glob.glob(f"{V_DIR}/seg_S{s['id']:02d}*.mp4"):
            print(f"[S{s['id']:02d}] skip", flush=True)
        else:
            extra = []
            if s["link_from"] and prev_file:
                link = extract_last_frame(prev_file, s["link_from"])
                extra = [link]
                print(f"[link] {s['link_from']}.png", flush=True)
            status(phase="V", shot=s["id"])
            run(h3_wf(s, extra), f"S{s['id']:02d}")
        prev_file = latest(f"seg_S{s['id']:02d}")
    # 拼接: 硬切视频 + 贯穿风声 bed 盖接缝
    status(phase="MIX")
    segs = [latest(f"seg_S{s['id']:02d}") for s in shots()]
    lst = "/root/story_test/seglist.txt"
    with open(lst, "w") as f:
        for s in segs: f.write(f"file '{s}'\n")
    merged = "/root/story_test/seg_merged.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "160k", merged], check=True)
    dur = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                          "-of", "csv=p=0", merged], capture_output=True, text=True).stdout.strip()
    # 风声 bed: 白噪声 lowpass 600Hz + 缓慢起伏包络
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
        f"anoisesrc=color=pink:amplitude=0.35:duration={dur}:seed=7",
        "-af", "lowpass=f=550,highpass=f=80,volume=0.30",
        "/root/story_test/wind_bed.wav"], check=True, capture_output=True)
    final = f"{V_DIR}/seg_final.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", merged, "-i", "/root/story_test/wind_bed.wav",
                    "-filter_complex", "[1:a]volume=0.16[b];[0:a][b]amix=inputs=2:duration=first:normalize=0[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    final], check=True)
    status(stage="all", done=True, final=final, dur=dur)
    print("FINAL:", final, flush=True)


if __name__ == "__main__":
    main()
