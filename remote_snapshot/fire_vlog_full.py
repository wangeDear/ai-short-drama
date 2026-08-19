#!/usr/bin/env python3
"""《森林求生·取火篇》H3 vlog 竖屏全量版
24镜(3复用demo+21新) | 竖屏544x960 | 六段式原生对白(口型)+画外镜混合
系统音(叮+TTS)后期叠加 | 全cut硬切 | BGM极低垫底 | 完成后关机(由调用方执行)
"""
import json, os, time, urllib.request, shutil, glob, subprocess, asyncio

BASE = "http://127.0.0.1:8188"
IN_DIR = "/workspace/ComfyUI/input"
OUT_DIR = "/workspace/ComfyUI/output"
V_DIR = f"{OUT_DIR}/video/H3vlog_full"
AUD = "/root/story_test/audio_vlog"
W, H = 544, 960
STATUS = "/root/story_test/status.json"

HERO = ("a Chinese man in his early 30s, short black hair, light stubble, olive outdoor vest "
        "over a dark t-shirt — a wilderness survival vlog host")
SELFIE = ("Realistic handheld selfie vlog footage, vertical 9:16, phone front camera at arm's "
          "length, face large and centered, slight natural hand shake, natural daylight, "
          "realistic skin texture. ")
OTHER = ("Realistic vertical vlog footage, 9:16, authentic handheld phone camera, natural "
         "daylight, documentary realism. ")
STORMC = ("Realistic vertical vlog footage, 9:16, dark overcast storm light, wind, handheld "
          "phone camera, documentary realism. ")
NOTEXT = "Absolutely no subtitles, no on-screen text, no watermark. "
NEG = "text, subtitle, caption, watermark, lowres, blurry, deformed, extra limbs, cartoon, 3D render"


def h3_len(sec):
    n = max(5, round(sec * 24))
    r = n % 17
    if r != 5: n += (5 - r) % 17
    return n


def sp6(retention, body, soundscape, music="none"):
    return f"""subject_definitions:
<Subject1> is {HERO}, visual identity from <Picture 1>.
<Picture 2> shows the scene location and lighting.

summary: [reference generation] A vertical selfie vlog clip of the host in a sunlit forest clearing.

retention_analysis:
<Picture 1>: fully_preserved — <Subject1>'s face, hair and outfit must match exactly.
<Picture 2>: weak_reference — only the setting and daylight. {retention}

detailed_description: {body}

overall_soundscape: {soundscape}.

non_diegetic_music: {music}.
"""


def talk(lines, lead="He looks straight into the lens and speaks Mandarin Chinese clearly, lips moving in natural sync:"):
    """生成口型台词段: lines=[(编号台词),...]"""
    parts = []
    for t in lines:
        parts.append(f"{lead} <Subject1> (S1) says, [Chinese] `{t}`")
        lead = "He continues speaking Mandarin with precise lip-sync:"
    return " ".join(parts) + " He closes his mouth at the end."


# ---- 24 镜: (id, dur, refs, prompt, kind)  kind: talk/fx/sys(后期叠音)/reuse ----
def shots():
    S = []
    def add(sid, dur, refs, prompt, kind="talk", file=None):
        S.append(dict(id=sid, dur=dur, refs=refs, prompt=prompt, kind=kind, file=file))
    # 幕1
    add(1, 11, ["fd_selfie.png", "fr_forest.png"], "", "reuse", "demo_D1_00001_.mp4")
    add(2, 9, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> holds the phone at arm's length, rolls his eyes with mild disdain and shakes his head, then speaks with mocking sarcasm: " +
            talk(["网上那些求生博主，钻木取火，搓得满头大汗，半小时冒个火星。就这？还上热门。"]) +
            " He smirks and waves his hand dismissively.", "forest birdsong, gentle wind"))
    add(3, 8, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> suddenly freezes mid-thought, eyebrows raised, listening to an unseen notification sound (he stays silent for a beat, mouth closed). Then he snorts with a cocky grin and speaks: " +
            talk(["三小时？我直接，手搓三件套。"]) + " He cracks a confident smile at the lens.",
            "forest ambience, a soft electronic ding, birdsong"))
    # 幕2 莱顿瓶
    add(4, 8, ["fd_overhead.png", "fr_forest.png"], "", "reuse", "demo_D2_00001_.mp4")
    add(5, 8, ["fd_overhead.png", "fr_forest.png"],
        sp6("", OTHER + "Close-up of <Subject1>'s hands holding up a finished homemade device: a plastic bottle neatly wrapped in tin foil with a copper wire through its mouth. He turns it slowly toward the camera, then his face leans into frame and he speaks while presenting it: " +
            talk(["第一步，锡纸糊瓶身。第二步，铜丝捅进去。搞定。"]) +
            " He taps the bottle proudly.", "leaves rustling, birdsong"))
    add(6, 8, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "Wide selfie framing showing his torso: <Subject1> rubs a wool sweater furiously against the tin-foil bottle with both hands, faster and faster, gritting his teeth, then speaks while still rubbing: " +
            talk(["第三步，最关键的一步，摩擦！"]) + " Sweat on his brow, comedic effort.",
            "vigorous fabric rubbing, static crackle, birdsong"))
    add(7, 6, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> leans his face very close to the lens, holds up the device, and slowly brings his finger toward the copper wire tip, whispering with tense lip-sync: " +
            talk(["现在，见证，静电的威力。"]) + " His eyes dart between finger and lens, mouth closed, breath held.",
            "near silence, faint static hum, heartbeat"))
    add(8, 5, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "A tiny bright blue spark snaps between wire and finger; <Subject1> jerks back with a yelp, hair slightly standing, then grins and shouts to the lens: " +
            talk(["看！放电了！"]) + " He shakes his hand laughing.",
            "electric snap crack, yelp, laughter"))
    add(9, 6, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> rubs his zapped finger, frowning at the tiny device with wounded pride, listening to an unseen notification (silent beat, mouth closed), then narrows his eyes and speaks with ambition: " +
            talk(["太小了。升级。"]) + " Slow confident smirk.",
            "soft electronic ding, forest ambience"))
    # 幕3 特斯拉
    add(10, 7, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> speaks to the lens with the excited tone of unveiling a big project: " +
            talk(["二号产物，特斯拉线圈。能把电压，抬到天上去的玩意儿。"]) +
            " He raises his eyebrows twice.", "forest ambience"))
    add(11, 9, ["fd_overhead.png", "fr_forest.png"],
        sp6("", OTHER + "Overhead view: <Subject1> squats over a ground cloth with two magnets, a coil of lacquered copper wire, a wooden stick — beside them a stick already densely wound with hundreds of neat copper turns. He taps each item and the finished coil, then looks up into the lens and speaks: " +
            talk(["材料，磁铁，铜线，木棍。铜线绕木棍，一千圈。"]), "items clinking, birdsong"))
    add(12, 8, ["fd_storm.png", "fr_forest.png"],
        sp6("", OTHER + "Fixed-camera full view: <Subject1> squats cranking a crude wooden hand-crank generator with the coil mounted, arms blurring, face going red with effort, shouting to the camera mid-crank with energetic lip-sync: " +
            talk(["没有电？自己摇！机械能，转电能！摇得越快，电压越高！"]),
            "creaky cranking, rising electric hum, heavy breathing"))
    add(13, 7, ["fd_storm.png", "fr_forest.png"],
        sp6("", OTHER + "Close-up: a violet-blue electric arc sizzles between two electrodes of his device; a dry leaf held nearby bursts into a small flame. <Subject1>'s face leans in behind it, wide-eyed, shouting excitedly to the lens: " +
            talk(["看见没！电弧！三千摄氏度！能点火了！"]),
            "electric sizzle arc, leaf flame whoosh, excited breathing"))
    add(14, 8, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> calmly pinches out the small flame, then turns to the lens, chin lifted with theatrical arrogance, speaking slowly: " +
            talk(["但用电弧点树叶，太没牌面了。这不符合，我的人设。"]) +
            " He crosses his arms, unimpressed.", "flame snuff, forest ambience"))
    add(15, 4, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> freezes listening to an unseen notification, eyebrows slowly rising above a smug grin (mouth closed, holding back laughter), then he nods slowly.", "soft electronic ding, forest ambience"))
    # 幕4 风筝
    add(16, 10, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> speaks to the lens with sudden solemn gravity, like announcing a sacred project: " +
            talk(["三号产物，终极作品，天基引雷装置。真正的狠人，不自己造火，让老天，给你火。"]) +
            " He holds the stare, dead serious.", "forest ambience, distant faint thunder"))
    add(17, 7, ["fd_overhead.png", "fr_forest.png"],
        sp6("", OTHER + "Overhead view: <Subject1> kneels over a finished diamond kite of bamboo and cloth, a steel needle bound upright at its tip, a long copper wire spool beside. His hands run along the frame checking joints, then he looks up into the lens and speaks: " +
            talk(["竹条扎骨架，布蒙面，顶端绑金属针。"]), "bamboo tapping, wire unspooling"))
    add(18, 6, ["fd_storm.png", "fr_forest.png"],
        sp6("", OTHER + "Low angle: <Subject1> hammers an iron stake into the earth and connects the copper wire to it, then rises and gazes up at the darkening sky, speaking to the camera over his shoulder: " +
            talk(["铜线接针，另一头，接地。"]) + " Wind picks up.",
            "stake hammering, wire humming, wind"))
    add(19, 5, ["fd_selfie.png", "fr_forest.png"],
        sp6("", SELFIE + "<Subject1> looks into the lens with devout reverence, speaks slowly like a disciple honoring a master: " +
            talk(["富兰克林，永远的神。"]) + " He gives a solemn slow nod.",
            "forest ambience, distant thunder roll"))
    add(20, 6, ["fd_storm.png", "fr_storm.png"],
        sp6("", STORMC + "Low-angle view: the diamond kite climbs into churning black storm clouds, tail fluttering, copper wire faintly glowing; below, <Subject1> grips the line with both hands, face tilted up, holy tension. He counts down loudly to the camera, lip-sync clear: " +
            talk(["风筝上天，铜线导雷。三，二，一，"]),
            "howling wind, wire vibration, thunder roll"))
    # 幕5 天雷
    add(21, 6, ["fd_storm.png", "fr_storm.png"],
        sp6("", STORMC + "Wide low-angle: a lightning bolt strikes sideways through the clouds and slams into the tall dead tree — the crown erupts into roaring orange flames, embers swirl upward, thick smoke rises. Natural-looking jagged bolt, realistic fire spread, motion blur.",
            "massive thunder crack, fire roaring, wind"))
    add(22, 6, ["fd_selfie.png", "fr_storm.png"],
        sp6("", STORMC + SELFIE + "<Subject1> turns to the lens with the burning tree glowing behind him, arms half raised in triumph, shouting joyfully: " +
            talk(["火，搞定！三件套，没白搓！"]) + " Big proud grin.",
            "fire roar behind, wind, joyful voice"))
    add(23, 6, ["fd_storm.png", "fr_storm.png"],
        sp6("", STORMC + "Medium view: the fire spreads higher up the great tree against the storm sky; <Subject1> stands small before it, slowly his grin freezes into wide-eyed horror (mouth slowly closing), listening to an unseen notification, then swallows.", "fire roaring, crackling, wind, soft electronic ding"))
    add(24, 9, ["fd_selfie.png", "fr_storm.png"],
        sp6("", STORMC + SELFIE + "<Subject1> looks into the lens with an awkward sheepish grin, glancing back at the huge fire, scratching his head, then speaks with nervous laughter: " +
            talk(["等等，这个火，是不是，有点大。"]) +
            " He shrugs helplessly and backs away, speaking over his shoulder: " +
            talk(["下期，这火，怎么灭。"], lead="He continues with a forced smile, precise lip-sync:") +
            " Freeze on his helpless expression.",
            "fire roar, crow cawing, nervous chuckle"))
    return S


SYS_LINES = {  # 系统音(后期TTS叠加), (镜id, 台词)
    3: "叮！取火任务已发布。基础解法：钻木取火。预计耗时：三小时。",
    9: "叮！产物①测试结果：电压约五千伏，火花零点三毫米。结论：点不着木头，也电不死人，但，能电到你自己。",
    15: "叮！产物②测试成功：电弧温度三千摄氏度，可引燃。但宿主，似乎，还有想法。",
    23: "叮！宿主完成取火。火源强度：森林火灾级。评价：S级，超纲。",
}
SYS_VOICE = "zh-CN-XiaoyiNeural"


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
                status(stage=tag, done=True, error=f"{m[1].get('node_type')}: {m[1].get('exception_message','')[:200]}")
                raise RuntimeError(f"{tag}: {m[1].get('node_type')}: {m[1].get('exception_message','')[:300]}")
        if time.time() - t0 > 1800:
            raise RuntimeError(f"{tag} timeout")


def h3_wf(shot):
    n = {}
    n["unet"] = {"class_type": "UNETLoader",
                 "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}}
    n["clip"] = {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}}
    n["vvae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}}
    n["avae"] = {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}}
    n["noise"] = {"class_type": "RandomNoise",
                  "inputs": {"noise_seed": 770000 + shot["id"] * 31, "control_after_generate": "fixed"}}
    n["guider"] = {"class_type": "BasicGuider", "inputs": {"model": ["unet", 0], "conditioning": ["i2v", 0]}}
    n["samp"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    n["sig"] = {"class_type": "BasicScheduler", "inputs": {"model": ["unet", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}}
    n["vdec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sc", 0], "vae": ["vvae", 0]}}
    n["adec"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sc", 0], "vae": ["avae", 0]}}
    n["cv"] = {"class_type": "CreateVideo", "inputs": {"images": ["vdec", 0], "fps": 24, "audio": ["adec", 0]}}
    n["save"] = {"class_type": "SaveVideo", "inputs": {
        "video": ["cv", 0], "filename_prefix": f"video/H3vlog_full/vs_S{shot['id']:02d}",
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


def dur_of(f):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", f], capture_output=True, text=True)
    return float(r.stdout.strip())


async def tts_one(text, voice, out):
    import edge_tts
    for attempt in range(4):
        try:
            c = edge_tts.Communicate(text, voice, rate="+8%")
            await c.save(out)
            if os.path.getsize(out) > 1000: return True
        except Exception:
            await asyncio.sleep(3)
    return False


def main():
    status(stage="start", done=False, error="")
    os.makedirs(V_DIR, exist_ok=True)
    SH = shots()
    # 复用 demo 的镜1/4: 拷进 V_DIR
    for s in SH:
        if s["kind"] == "reuse":
            src = f"{OUT_DIR}/video/H3vlog/{s['file']}"
            dst = f"{V_DIR}/vs_S{s['id']:02d}_reuse.mp4"
            if not os.path.exists(dst): shutil.copy(src, dst)
            print(f"[S{s['id']:02d}] reuse", flush=True)
    # 生成新镜
    for s in SH:
        if glob.glob(f"{V_DIR}/vs_S{s['id']:02d}*.mp4"):
            print(f"[S{s['id']:02d}] skip", flush=True); continue
        status(phase="V", shot=s["id"], total=24)
        run(h3_wf(s), f"S{s['id']:02d}")
    # 系统音
    os.makedirs(AUD, exist_ok=True)
    for sid, text in SYS_LINES.items():
        out = f"{AUD}/sys{sid}.mp3"
        if not os.path.exists(out):
            ok = asyncio.run(tts_one(text, SYS_VOICE, out))
            if not ok: raise RuntimeError(f"TTS sys{sid} fail")
        print(f"[sys{sid}] ok", flush=True)
    # 叠加系统音 -> 拼接
    status(phase="MIX")
    segs = []
    for s in SH:
        vf = sorted(glob.glob(f"{V_DIR}/vs_S{s['id']:02d}*.mp4"), key=os.path.getmtime)[-1]
        if s["id"] in SYS_LINES:
            out = f"{AUD}/mixsys{s['id']:02d}.mp4"
            subprocess.run(["ffmpeg", "-y", "-i", vf, "-i", f"{AUD}/sys{s['id']}.mp3",
                "-filter_complex",
                "[1:a]adelay=1500|1500,apad[sa];[0:a][sa]amix=inputs=2:duration=first:weights=1 0.9[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                out], check=True, capture_output=True)
            vf = out
        segs.append(vf)
    lst = "/root/story_test/vlist.txt"
    with open(lst, "w") as f:
        for s in segs: f.write(f"file '{s}'\n")
    merged = "/root/story_test/vlog_merged.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", merged], check=True, capture_output=True)
    total = dur_of(merged)
    # BGM 极低垫底
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
        f"aevalsrc=0.20*sin(2*PI*110*t)*pow(max(0\\,sin(2*PI*2*t))\\,8):s=44100:d={total}",
        "-af", "volume=0.5,aecho=0.6:0.4:120:0.3", "/root/story_test/vbgm.wav"],
        check=True, capture_output=True)
    final = f"{V_DIR}/vlog_final.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", merged, "-i", "/root/story_test/vbgm.wav",
                    "-filter_complex", "[1:a]volume=0.08[b];[0:a][b]amix=inputs=2:duration=first[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-crf", "18",
                    "-preset", "fast", "-c:a", "aac", "-b:a", "160k", final], check=True)
    status(stage="all", done=True, final=final, shots=24)
    print("FINAL:", final, flush=True)


if __name__ == "__main__":
    main()
