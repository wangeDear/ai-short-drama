#!/usr/bin/env python3
"""《沙漠生存·离网电力篇》H3 vlog 竖屏 · 女探险者版
12镜 | 竖屏544x960 | 六段式原生对白(口型) | 全cut硬切
用法: python3 desert_vlog.py assets|demo|full
  assets: 生成2张Qwen资产图  demo: 3镜试跑(S1/S3/S7)  full: 全量+拼接
断点续跑: 产物存在即跳过。状态: /root/story_test/status.json
"""
import json, os, time, urllib.request, shutil, glob, subprocess

BASE = "http://127.0.0.1:8188"
IN_DIR = "/workspace/ComfyUI/input"
OUT_DIR = "/workspace/ComfyUI/output"
V_DIR = f"{OUT_DIR}/video/desert_vlog"
W, H = 544, 960
STATUS = "/root/story_test/status.json"

HERO = ("a Chinese woman in her early 30s, dark hair in a practical low ponytail, khaki "
        "quick-dry outdoor jacket, sand-colored tactical neck gaiter pulled down around her "
        "neck, black tactical gloves, GoPro chest mount — a desert survival tech vlog host")
SELFIE = ("Realistic handheld selfie vlog footage, vertical 9:16, phone front camera at arm's "
          "length, face large and centered, slight natural hand shake, harsh desert sunlight, "
          "sun flare, realistic skin texture with sweat and fine dust. ")
OTHER = ("Realistic vertical vlog footage, 9:16, authentic handheld phone camera, harsh "
         "desert sunlight, hard shadows, sun flare, documentary realism. ")
EVE = ("Realistic vertical vlog footage, 9:16, warm golden sunset light, long hard shadows, "
       "handheld phone camera, documentary realism. ")
NOTEXT = "Absolutely no subtitles, no on-screen text, no watermark. "
NEG = "text, subtitle, caption, watermark, lowres, blurry, deformed, extra limbs, cartoon, 3D render, other people, modern buildings"


def h3_len(sec):
    n = max(5, round(sec * 24))
    r = n % 17
    if r != 5: n += (5 - r) % 17
    return n


def sp6(retention, body, soundscape, music="none"):
    return f"""subject_definitions:
<Subject1> is {HERO}, visual identity from <Picture 1>.
<Picture 2> shows the desert location and lighting: vast golden dunes, deep blue sky, harsh sun.

summary: [reference generation] A vertical selfie vlog clip of the host in a vast golden desert.

retention_analysis:
<Picture 1>: fully_preserved — <Subject1>'s face, ponytail, outfit and gear must match exactly.
<Picture 2>: weak_reference — only the desert setting and daylight. {retention}

detailed_description: {body}

overall_soundscape: {soundscape}.

non_diegetic_music: {music}.
"""


def talk(lines, lead="She looks straight into the lens and speaks Mandarin Chinese clearly, lips moving in natural sync:"):
    parts = []
    for t in lines:
        parts.append(f"{lead} <Subject1> (S1) says, [Chinese] `{t}`")
        lead = "She continues speaking Mandarin with precise lip-sync:"
    return " ".join(parts) + " She closes her mouth at the end."


# ---- 12 镜: (id, dur, refs, prompt) ----
def shots():
    S = []
    def add(sid, dur, prompt, refs=("dh_hero.png", "sd_desert.png")):
        S.append(dict(id=sid, dur=dur, prompt=prompt, refs=list(refs)))
    add(1, 10,
        sp6("", SELFIE + "Wide selfie framing at arm's length with slight fisheye distortion: <Subject1> looks into the lens, face streaked with sweat and dust, tense but determined. She raises her phone toward the lens showing a nearly empty battery icon and weak signal bars, then speaks while holding it up: " +
            talk(["兄弟们，坏消息，手机只剩百分之二的电，GPS信号也快没了。"]) +
            " Behind her endless rolling golden dunes shimmer under a cloudless blue sky; wind tugs at her ponytail. She lowers the phone and presses her lips together.",
            "howling desert wind, hissing sand grains, faint fabric flapping"))
    add(2, 8,
        sp6("", SELFIE + "<Subject1> slowly pans the selfie camera across the horizon: rolling golden dunes to the edge of vision, deep blue cloudless sky, sun flare hitting the lens. She turns back to face the camera and speaks with resolve: " +
            talk(["这片沙漠一眼望不到头。当务之急，是把电搞起来。"]) + " Determined nod, mouth closed.",
            "wind gusts, fabric flapping, distant dune echo"))
    add(3, 6,
        sp6("", OTHER + "Overhead POV shot looking down at her gloved hands: she pulls a folded deep-blue solar panel from a tactical backpack, unfolds it flat onto the sand, connects a USB tester and cable to her phone. She speaks while working, hands busy: " +
            talk(["先试最简单的，折叠太阳能板，直接铺沙地上。"], lead="She narrates to the camera while her hands work, lips moving in sync:"),
            "backpack zipper, velcro rip, sand crunch, plastic unwrap"))
    add(4, 9,
        sp6("", OTHER + "Close-up: she leans toward the USB tester screen, tiny current numbers flickering unsteadily between 0.00 and 0.12. She frowns, taps the meter, then looks into the lens and explains, frowning: " +
            talk(["电流零点一二安，还不稳。板子效率上不来，这线也不能直接放沙子里，太热降功率。"]) +
            " She shakes her head, lips pressed.",
            "electronic beep, wind"))
    add(5, 6,
        sp6("", OTHER + "Medium side view: kneeling on the sand, she props one edge of the solar panel up with a dry dead stick and stones, forming a tilt angle; wind blows sand across the frame, one gloved hand pressing the panel steady. She speaks while bracing it: " +
            talk(["拿枯木和石头支个倾角。风有点大，先按住。"], lead="She says while pressing the panel, lip-sync clear:"),
            "wood knocking on stone, sandblast against fabric"))
    add(6, 7,
        sp6("", OTHER + "Close-up of the wooden stick支架 visibly trembling in the wind, the panel rattling; <Subject1> shakes her head with a wry grin and speaks to the lens: " +
            talk(["木头支架一直抖，这么下去迟早得断。上专业装备。"]) + " She smirks and tosses the stick aside.",
            "creaking wood, rattling panel, wind"))
    add(7, 7,
        sp6("", EVE + "Detailed close view: her gloved hands assemble metal aluminum tubes and three-way joints with a ratchet wrench, tightening each connection into an adjustable frame; the solar panel is bolted onto it and tilted against the low warm sunset. She speaks while wrenching: " +
            talk(["铝合金管加三通，扳手拧紧，角度可调。这才像话。"], lead="She narrates over her shoulder while tightening bolts, lip-sync clear:"),
            "ratchet wrench clicks, metal clinks, evening wind"))
    add(8, 5,
        sp6("", OTHER + "Extreme close-up: a spray bottle squirts a jet of water across the sand-dusted solar panel; fine sand washes away, the deep-blue surface gleaming again. Her face leans into frame and she speaks briefly: " +
            talk(["板面积沙，冲干净效率能提不少。"]),
            "water spray jet, rivulets hissing on hot panel"))
    add(9, 6,
        sp6("", OTHER + "Close-up: an IR thermometer points at a battery pack showing a high temperature reading; her hands wrap a transparent cooling water tube around the pack and connect a small pump. She speaks while coiling: " +
            talk(["电池温度偏高，缠圈冷却水管，物理降温。"], lead="She explains while coiling the tube, lip-sync clear:"),
            "IR thermometer beep, water trickling through tube"))
    add(10, 8,
        sp6("", OTHER + "Medium view: she yanks the pull-cord of a small diesel generator; it coughs to life with a puff of black smoke. She turns her head aside from the smoke with a grin and speaks to the lens: " +
            talk(["再来台发电机兜底，黑烟是大了点，但稳。"]) + " She pats the generator.",
            "pull-cord engine crank, diesel clatter, smoke puff"))
    add(11, 10,
        sp6("", EVE + "Smooth orbit shot circling the finished off-grid power system on the dune: two solar panels on the metal frame, battery pack with cooling tubes, inverter control box, water pump and the diesel generator, all glowing in warm sunset light. <Subject1> stands beside it presenting to the camera, speaking proudly: " +
            talk(["看这套系统，双板阵列，金属支架，蓄电池，逆变器，水泵。离网电力，齐活。"]) +
            " She spreads her arms at the system.",
            "low wind, inverter hum, distant generator purr"))
    add(12, 8,
        sp6("", EVE + "Close-up: she opens the distribution box and adjusts wiring, separating a low-voltage port, plugs in her phone; the screen shows a green charging icon with the battery number climbing. She raises the phone to the lens and speaks with quiet triumph: " +
            talk(["低压端口专门给手机供电，电量在涨。在沙漠里，电，就是命。"]) +
            " She holds the phone up a beat, then lowers it, mouth closed.",
            "electrical click, soft charge chime, evening ambience"))
    return S


DEMO_IDS = {1, 3, 7}


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
            for f in (o.get("images") or o.get("videos") or []):
                files.append(os.path.join(OUT_DIR, f.get("subfolder", ""), f["filename"]))
        if files:
            status(stage=tag, done=True, secs=round(time.time() - t0))
            print(f"[{tag}] DONE {round(time.time()-t0)}s", flush=True)
            return files
        for m in info.get("status", {}).get("messages", []):
            if m[0] == "execution_error":
                status(stage=tag, done=True, error=f"{m[1].get('node_type')}: {m[1].get('exception_message','')[:200]}")
                raise RuntimeError(f"{tag}: {m[1].get('node_type')}: {m[1].get('exception_message','')[:300]}")
        if time.time() - t0 > 1800:
            raise RuntimeError(f"{tag} timeout")


ASSETS = {
    "dh_hero": ("Photorealistic character reference: " + HERO + ". Standing in golden desert "
                "dunes, harsh sunlight, hard shadows, sweat and fine dust on face, confident "
                "calm expression. Vertical 544x960 portrait, full upper body visible."),
    "sd_desert": ("Photorealistic scene reference: vast golden sand desert, rolling dunes to "
                  "the horizon, cloudless deep blue sky, harsh midday sun high in frame, sun "
                  "flare, wind-blown sand texture. No people, no objects. Vertical 544x960."),
}


def qwen_wf(prompt, prefix):
    n = {}
    n["unet"] = {"class_type": "UNETLoader",
                 "inputs": {"unet_name": "qwen_image_edit_2511_fp8mixed.safetensors", "weight_dtype": "default"}}
    n["shift"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 3.1}}
    n["cfgn"] = {"class_type": "CFGNorm", "inputs": {"model": ["shift", 0], "strength": 1.0}}
    n["lora"] = {"class_type": "LoraLoaderModelOnly",
                 "inputs": {"model": ["cfgn", 0],
                            "lora_name": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
                            "strength_model": 1.0}}
    n["clip"] = {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}}
    n["vae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}}
    n["pos"] = {"class_type": "TextEncodeQwenImageEditPlus",
                "inputs": {"clip": ["clip", 0], "vae": ["vae", 0], "prompt": prompt}}
    n["neg"] = {"class_type": "TextEncodeQwenImageEditPlus",
                "inputs": {"clip": ["clip", 0], "vae": ["vae", 0], "prompt": NEG}}
    n["empty"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}}
    n["ks"] = {"class_type": "KSampler", "inputs": {
        "model": ["lora", 0], "positive": ["pos", 0], "negative": ["neg", 0],
        "latent_image": ["empty", 0], "seed": 880000,
        "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
    n["dec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}}
    n["save"] = {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": prefix}}
    return {"prompt": n}


def h3_wf(shot):
    n = {}
    n["unet"] = {"class_type": "UNETLoader",
                 "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}}
    n["clip"] = {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}}
    n["vvae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}}
    n["avae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}}
    n["noise"] = {"class_type": "RandomNoise",
                  "inputs": {"noise_seed": 880000 + shot["id"] * 31, "control_after_generate": "fixed"}}
    n["guider"] = {"class_type": "BasicGuider", "inputs": {"model": ["unet", 0], "conditioning": ["i2v", 0]}}
    n["samp"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    n["sig"] = {"class_type": "BasicScheduler", "inputs": {"model": ["unet", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}}
    n["vdec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sc", 0], "vae": ["vvae", 0]}}
    n["adec"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sc", 0], "vae": ["avae", 0]}}
    n["cv"] = {"class_type": "CreateVideo", "inputs": {"images": ["vdec", 0], "fps": 24, "audio": ["adec", 0]}}
    n["save"] = {"class_type": "SaveVideo", "inputs": {
        "video": ["cv", 0], "filename_prefix": f"video/desert_vlog/ds_S{shot['id']:02d}",
        "format": "auto", "codec": "auto"}}
    ref_imgs = []
    for i, r in enumerate(shot["refs"], 1):
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


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    status(stage=f"start:{mode}", done=False, error="")
    os.makedirs(V_DIR, exist_ok=True)

    if mode in ("assets", "all"):
        for name, pr in ASSETS.items():
            dst = f"{IN_DIR}/{name}.png"
            if os.path.exists(dst): print(f"[{name}] skip", flush=True); continue
            f = run(qwen_wf(pr, f"desert/asset_{name}"), name)
            shutil.copy(f[0], dst)

    if mode in ("demo", "full", "all"):
        ids = DEMO_IDS if mode == "demo" else None
        for s in shots():
            if ids and s["id"] not in ids: continue
            if glob.glob(f"{V_DIR}/ds_S{s['id']:02d}*.mp4"):
                print(f"[S{s['id']:02d}] skip", flush=True); continue
            status(phase="V", shot=s["id"], total=12, mode=mode)
            run(h3_wf(s), f"S{s['id']:02d}")

    if mode in ("full", "all"):
        status(phase="CONCAT")
        segs = []
        for s in shots():
            fs = glob.glob(f"{V_DIR}/ds_S{s['id']:02d}*.mp4")
            if not fs: raise RuntimeError(f"S{s['id']:02d} missing")
            segs.append(sorted(fs, key=os.path.getmtime)[-1])
        lst = "/root/story_test/dlist.txt"
        with open(lst, "w") as f:
            for s in segs: f.write(f"file '{s}'\n")
        final = f"{V_DIR}/desert_final.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                        "-c:a", "aac", "-b:a", "160k", final], check=True)
        status(stage="all", done=True, final=final, shots=12)
        print("FINAL:", final, flush=True)
    if mode == "demo":
        status(stage="demo_done", done=True)
        print("DEMO DONE", flush=True)


if __name__ == "__main__":
    main()
