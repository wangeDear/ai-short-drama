"""剧本文本 → 分镜自动分段（FR-PROJ-002 扩展）。

支持三种输入（自动识别）：
1. Markdown 镜表（docs/07 同款：| S01 | 镜型 | 时长 | 画面 | 台词 | soundscape |）；
2. 结构化剧本（场/镜标题 + 描述行 + 角色台词行）；
3. 纯叙事文本（按目标时长聚句分段）。

时长公式与 docs/02 流水线定稿 v2 一致：口型镜 = 台词字数 ÷ 4字/s + 2s。
无 LLM 时提示词仅为草稿基线，需人工润色为六段式模板。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADER_PATTERNS = [
    re.compile(r"^#{1,4}\s*(?!#)(.+)$"),  # Markdown 标题
    re.compile(r"^【?第?\s*[\d一二三四五六七八九十百]+\s*[场幕镜](?:次)?】?\s*[：:、.]?\s*(.*)$"),
    re.compile(r"^[Ss](\d{1,3})\s*[：:、.]\s*(.*)$"),
    re.compile(r"^(\d{1,3})\s*[、.]\s*\S.*$"),  # 有序列表（要求后面有内容，避免年份等误判）
]

DIALOGUE_RE = re.compile(r"^([^：:「」“”\s]{1,12})\s*[：:]\s*(.+)$")
QUOTE_RE = re.compile(r"[「“]([^」”]+)[」”]")
PAREN_RE = re.compile(r"[（(]([^）)]+)[)）]")
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|S|秒)")
READING_SPEED = 4.0  # 字/秒（v2 定稿：台词字数÷4字/s）
MIN_DURATION = 3.0
MAX_DURATION = 15.0


@dataclass
class ParsedShot:
    code: str = ""
    title: str = ""
    description: str = ""
    voice_text: str = ""
    ambience_text: str = ""
    characters: list[str] = field(default_factory=list)
    duration: float = 0.0
    seed: int | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "title": self.title,
            "description": self.description,
            "voice_text": self.voice_text,
            "ambience_text": self.ambience_text,
            "characters": "、".join(self.characters),
            "duration": round(self.duration, 1),
            "seed": self.seed,
        }


def dialogue_duration(text: str) -> float:
    """口型镜时长公式：台词字数 ÷ 4字/s + 2s（v2 定稿）。"""
    clean = re.sub(r"\s+", "", text or "")
    return min(MAX_DURATION, max(MIN_DURATION, len(clean) / READING_SPEED + 2.0))


def _is_separator(row: str) -> bool:
    return bool(re.match(r"^[\s|:\-—]+$", row))


def _parse_duration(cell: str, voice: str) -> float:
    match = DURATION_RE.search(cell or "")
    if match:
        return float(match.group(1))
    if voice:
        return dialogue_duration(voice)
    return 0.0


def _parse_table(lines: list[str]) -> list[ParsedShot]:
    rows = [line.strip() for line in lines if line.strip().startswith("|")]
    if len(rows) < 2:
        return []

    header_cells: list[str] = []
    header_idx = -1
    for index, row in enumerate(rows):
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        joined = "".join(cells)
        if any(key in joined for key in ("台词", "时长", "画面", "镜型", "运镜", "soundscape")) and not re.search(
            r"\d+\s*(?:s|秒)", joined
        ):
            header_cells = cells
            header_idx = index
            break

    def column_of(*keywords: str, default: int | None = None) -> int | None:
        if header_cells:
            for position, cell in enumerate(header_cells):
                if any(keyword in cell for keyword in keywords):
                    return position
        return default

    col_code = column_of("#", "编号", "镜号", default=0)
    col_title = column_of("镜型", "类型")
    col_duration = column_of("时长", default=2)
    col_picture = column_of("画面", "运镜", "描述", default=3)
    col_voice = column_of("台词", "对白", "旁白", default=4)
    col_sound = column_of("soundscape", "环境音", "音效")

    def cell_of(cells: list[str], index: int | None) -> str:
        if index is None or index >= len(cells):
            return ""
        return cells[index].strip()

    shots: list[ParsedShot] = []
    for row in rows[header_idx + 1 if header_idx >= 0 else 0 :]:
        if _is_separator(row):
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if not any(cells):
            continue
        code = cell_of(cells, col_code)
        if not re.search(r"[A-Za-z\d]", code):
            continue  # 表尾说明行
        voice = cell_of(cells, col_voice)
        # 去掉（画外边做边说）之类的舞台指示，保留为画面描述补充
        paren_note = ""
        paren_match = PAREN_RE.search(voice)
        if paren_match:
            paren_note = paren_match.group(1)
        quoted = QUOTE_RE.findall(voice)
        voice_clean = " ".join(quoted) if quoted else PAREN_RE.sub("", voice).strip().strip('"“”')
        picture = cell_of(cells, col_picture)
        shot = ParsedShot(
            code=re.sub(r"\s+", "", code),
            title=cell_of(cells, col_title),
            description=(picture + ("（" + paren_note + "）" if paren_note else "")).strip(),
            voice_text=voice_clean,
            ambience_text=cell_of(cells, col_sound),
            duration=_parse_duration(cell_of(cells, col_duration), voice_clean),
        )
        shots.append(shot)
    return shots


def _parse_structured(lines: list[str], default_duration: float) -> list[ParsedShot]:
    shots: list[ParsedShot] = []
    current: ParsedShot | None = None
    description_lines: list[str] = []

    def flush() -> None:
        nonlocal current, description_lines
        if current is not None:
            current.description = "\n".join(description_lines).strip()
            if not current.duration:
                current.duration = dialogue_duration(current.voice_text) if current.voice_text else default_duration
            shots.append(current)
        current = None
        description_lines = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        header_text = None
        for pattern in HEADER_PATTERNS:
            match = pattern.match(line)
            if match:
                # 跳过纯数字年份/序号误判：要求标题行不是 "2026" 这类
                header_text = line.lstrip("#").strip()
                break
        if header_text is not None and not DURATION_RE.search(header_text):
            flush()
            current = ParsedShot(title=header_text[:80])
            continue
        if current is None:
            current = ParsedShot(title="")
        dialogue = DIALOGUE_RE.match(line)
        if dialogue and not line.startswith(("http", "【")):
            role = dialogue.group(1).strip()
            content = dialogue.group(2).strip()
            quoted = QUOTE_RE.findall(content)
            content = " ".join(quoted) if quoted else content.strip('"“”')
            current.voice_text = (current.voice_text + " " + content).strip()
            if role and role not in ("旁白", "画外音", "OS") and role not in current.characters:
                current.characters.append(role)
        else:
            description_lines.append(line)

    flush()
    return shots


def _parse_narrative(text: str, target_seconds: float) -> list[ParsedShot]:
    sentences = [s.strip() for s in re.split(r"(?<=[。！？；\n])", text) if s.strip()]
    if not sentences:
        return []
    max_chars = max(12, int((target_seconds - 1.0) * READING_SPEED))
    chunks: list[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = (buffer + sentence).strip()
        if buffer and len(candidate) > max_chars:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer = candidate
    if buffer:
        chunks.append(buffer)
    return [
        ParsedShot(description=chunk, duration=max(MIN_DURATION, min(target_seconds, len(chunk) / READING_SPEED + 2)))
        for chunk in chunks
    ]


def _has_structure(lines: list[str]) -> bool:
    """是否存在结构化标记（场/镜标题或角色台词行）。"""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern.match(stripped) for pattern in HEADER_PATTERNS):
            return True
        if DIALOGUE_RE.match(stripped) and not stripped.startswith("http"):
            return True
    return False


def parse_script(
    text: str,
    *,
    default_duration: float = 6.0,
    target_seconds: float = 10.0,
    base_seed: int = 42,
) -> list[dict]:
    """解析剧本为分镜 dict 列表（自动识别镜表/结构化/叙事三种格式）。"""
    if not (text or "").strip():
        return []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    shots = _parse_table(lines)
    structured = False
    if not shots:
        shots = _parse_structured(lines, default_duration)
        structured = _has_structure(lines)
    if len(shots) <= 1 and not structured:
        shots = _parse_narrative(text, target_seconds)

    results: list[dict] = []
    for index, shot in enumerate(shots, start=1):
        shot.code = shot.code or f"S{index:02d}"
        shot.seed = (base_seed + index * 17) % (2**31)
        results.append(shot.to_dict())
    return results
