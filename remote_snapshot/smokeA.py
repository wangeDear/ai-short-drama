#!/usr/bin/env python3
"""冒烟A: LTX-2.5 T2V multishot 1080p — 验证多镜头切换质量+显存可行性 (distilled 8步)"""
import json, os, time, urllib.request, sys

BASE = "http://127.0.0.1:8188"
OUT_DIR = "/workspace/ComfyUI/output"
W, H, FPS = 1920, 1088, 25
LENGTH = 417  # 20s: 8*20+1... 8*round(500/8)+1 = 8*63+1 = 505? -> 用 8*21+1=169 (6.8s) 更快冒烟
LENGTH = 169  # 6.8s 两镜头, 冒烟够用

PROMPT = ("Photorealistic wilderness survival documentary, natural daylight, handheld camera. "
          "[Shot 1] A Chinese man in his 30s wearing an olive outdoor vest squats beside a pile of dry branches "
          "in a sunlit forest clearing, expression dead serious, tapping a branch against his palm. "
          "[Shot 2] Close-up: he looks up at the camera with a confident smirk and slowly cracks his knuckles. "
          "Sounds: forest birds, gentle wind, distant insects. "
          "Absolutely no subtitles, no on-screen text, no watermark.")
NEG = "text, subtitle, caption, watermark, logo, lowres, blurry, deformed, extra limbs, cartoon, 3D render, animation"

def main():
    n = {}
    n["te"] = {"class_type": "LTXAVTextEncoderLoader", "inputs": {
        "text_encoder": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
        "ckpt_name": "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors", "device": "cpu"}}
    n["pos"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["te", 0], "text": PROMPT}}
    n["neg"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["te", 0], "text": NEG}}
    n["unet"] = {"class_type": "UNETLoader", "inputs": {
        "unet_name": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "weight_dtype": "default"}}
    n["vae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "ltx-2.5-video-vae-bf16.safetensors"}}
    n["avae"] = {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": "ltx-2.5-audio-vae-bf16.safetensors"}}
    n["empty"] = {"class_type": "EmptyLTXVLatentVideo", "inputs": {
        "width": W, "height": H, "length": LENGTH, "batch_size": 1}}
    n["aempty"] = {"class_type": "LTXVEmptyLatentAudio", "inputs": {
        "frames_number": LENGTH, "frame_rate": FPS, "batch_size": 1, "audio_vae": ["avae", 0]}}
    n["concat"] = {"class_type": "LTXVConcatAVLatent", "inputs": {
        "video_latent": ["empty", 0], "audio_latent": ["aempty", 0]}}
    n["sched"] = {"class_type": "LTXVScheduler", "inputs": {
        "steps": 8, "max_shift": 2.05, "base_shift": 0.95, "stretch": True,
        "terminal": 0.1, "latent": ["concat", 0]}}
    n["noise"] = {"class_type": "RandomNoise", "inputs": {
        "noise_seed": 424242, "control_after_generate": "fixed"}}
    n["guider"] = {"class_type": "BasicGuider", "inputs": {"model": ["unet", 0], "conditioning": ["pos", 0]}}
    n["samp"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}}
    n["sc"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["samp", 0],
        "sigmas": ["sched", 0], "latent_image": ["concat", 0]}}
    n["sep"] = {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["sc", 0]}}
    n["vdec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sep", 0], "vae": ["vae", 0]}}
    n["adec"] = {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["sep", 1], "audio_vae": ["avae", 0]}}
    n["cv"] = {"class_type": "CreateVideo", "inputs": {"images": ["vdec", 0], "fps": FPS, "audio": ["adec", 0]}}
    n["save"] = {"class_type": "SaveVideo", "inputs": {
        "video": ["cv", 0], "filename_prefix": "video/LTXsmoke/smokeA_multishot",
        "format": "auto", "codec": "auto"}}
    req = urllib.request.Request(BASE + "/prompt", data=json.dumps({"prompt": n}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("SUBMIT FAIL:", e.read().decode()[:500]); sys.exit(1)
    print("submitted", pid, flush=True)
    t0 = time.time()
    while True:
        time.sleep(10)
        h = json.loads(urllib.request.urlopen(BASE + f"/history/{pid}", timeout=180).read())
        if pid not in h: continue
        info = h[pid]
        files = []
        for o in info.get("outputs", {}).values():
            for f in (o.get("videos") or o.get("images") or []):
                files.append(os.path.join(OUT_DIR, f.get("subfolder", ""), f["filename"]))
        if files:
            print(f"DONE {round(time.time()-t0)}s ->", files, flush=True); return
        for m in info.get("status", {}).get("messages", []):
            if m[0] == "execution_error":
                print("ERROR:", m[1].get("node_type"), str(m[1].get("exception_message"))[:300], flush=True); sys.exit(1)
        if time.time() - t0 > 2400:
            print("timeout"); sys.exit(1)

if __name__ == "__main__":
    main()
