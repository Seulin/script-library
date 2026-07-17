#!/usr/bin/env python3
"""fangj.github.io Friends 트랜스크립트 → 학습 사이트 JSON 임포터.

대사뿐 아니라 장면 헤딩([Scene: ...]), 섹션 구분(Commercial Break 등),
행동 지침(괄호), unseen(파란 글씨, #0000FF) 구분까지 보존한다.

표준 라이브러리만 사용. 사용 예:
    python3 tools/import_transcript.py \
        --out data/friends/s01e01.imported.json \
        --drama Friends --season 1 --episode 1

기본 소스는 시즌1 1화. 다른 화는 --url 또는 --file 로 지정.
"""

import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.request import urlopen

DEFAULT_URL = "https://fangj.github.io/friends/season/0101.html"
UNSEEN_COLOR = "#0000ff"  # 파란 글씨 = 원 방영본엔 없던 부분

# 에피소드 제목 앞 "S01E07 · " 같은 코드 접두어(표시엔 넣지 않음)
EP_PREFIX_RE = re.compile(r"^\s*S\d+E\d+\s*·\s*")

# 섹션 구분으로 취급할 문구(트림·대소문자 무시 후 매칭)
SECTION_RE = re.compile(
    r"^(commercial break|opening credits|closing credits|opening titles|end credits|end)$",
    re.I,
)

# 대사 본문에 인라인으로 섞여 들어온 대괄호 블록([Scene: ...], [Time Lapse] 등)
BRACKET_RE = re.compile(r"\[[^\]]*\]")
SCENE_BRACKET_RE = re.compile(r"^\[\s*scene\s*:", re.I)

# 대사 끝의 노래 시작 마커 — "(Sung:)" / "(Sung)". 바로 다음 문단(<blockquote> 가사)이
# 화자 라벨 없이 오므로, 이 마커를 신호로 삼아 가사를 같은 화자의 대사로 붙인다.
SUNG_MARKER_RE = re.compile(r"\(\s*sung\s*:?\s*\)\s*$", re.I)
SUNG_PREFIX = "(Sung:) "

# 화자 라벨 없는 문단이 이 비율 이상 이탤릭이면 노래 가사로 본다.
# (실측: 가사 69~100% vs 이탤릭 섞인 일반 지침 13%)
ITALIC_SONG_RATIO = 0.6


class TranscriptParser(HTMLParser):
    """<p> 단위로 (text, unseen, bold) 토큰과 문단별 이탤릭 비율을 수집한다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_p = False
        self.color_stack = []   # <font color> 중첩 추적
        self.bold_depth = 0     # <b>/<strong> 중첩 추적
        self.italic_depth = 0   # <i>/<em> 중첩 추적 — 노래 가사 판별용
        self.tokens = []        # 현재 문단의 (text, unseen, bold)
        self.paragraphs = []    # [(text, unseen, bold), ...] 들의 리스트
        self.italic_ratios = [] # paragraphs 와 같은 길이: 문단 텍스트 중 이탤릭 비율
        self._ital_len = 0
        self._all_len = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "p":
            self.in_p = True
            self.tokens = []
            self._ital_len = 0
            self._all_len = 0
            # 문단 경계에서 상태 초기화(소스의 국소적 태그 불균형이 다음 문단으로 새지 않게).
            # italic_depth 는 일부러 초기화하지 않는다 — 전사본에서 <i>가 <p>를 넘어
            # <blockquote> 가사 전체를 감싸는 경우가 있어(예: s01e11) 유지해야 한다.
            self.color_stack = []
            self.bold_depth = 0
        elif tag == "font":
            self.color_stack.append((attrs.get("color") or "").lower())
        elif tag in ("b", "strong"):
            self.bold_depth += 1
        elif tag in ("i", "em"):
            self.italic_depth += 1
        elif tag == "br" and self.in_p:
            # 줄바꿈 보존(크레딧 등 멀티라인 파싱용). 대사에선 이후 normalize_ws가 공백으로 정리.
            self.tokens.append(("\n", self._unseen(), self.bold_depth > 0))

    def handle_endtag(self, tag):
        if tag == "p":
            if self.in_p:
                self.paragraphs.append(self.tokens)
                self.italic_ratios.append(
                    self._ital_len / self._all_len if self._all_len else 0.0
                )
            self.in_p = False
            self.tokens = []
        elif tag == "font":
            if self.color_stack:
                self.color_stack.pop()
        elif tag in ("b", "strong"):
            self.bold_depth = max(0, self.bold_depth - 1)
        elif tag in ("i", "em"):
            self.italic_depth = max(0, self.italic_depth - 1)

    def handle_data(self, data):
        if self.in_p and data:
            self.tokens.append((data, self._unseen(), self.bold_depth > 0))
            n = len(data.strip())
            if n:
                self._all_len += n
                if self.italic_depth > 0:
                    self._ital_len += n

    def _unseen(self):
        # 가장 안쪽 색이 파란색이면 unseen
        return bool(self.color_stack) and self.color_stack[-1] == UNSEEN_COLOR


def normalize_ws(text):
    return re.sub(r"\s+", " ", text)


def merge_segments(tokens):
    """(text, unseen) 토큰을 인접 unseen 동일 구간끼리 병합해 조각 리스트로."""
    segments = []
    for text, unseen in tokens:
        if not text:
            continue
        if segments and segments[-1]["unseen"] == unseen:
            segments[-1]["text"] += text
        else:
            segments.append({"text": text, "unseen": unseen})
    return segments


def to_value(segments):
    """조각 리스트를 JSON 값으로: 전부 방영이면 문자열, 혼합이면 배열."""
    # 양끝 공백 정리
    cleaned = []
    for seg in segments:
        t = seg["text"]
        if t.strip() == "" and not cleaned:
            continue  # 앞쪽 공백 조각 버림
        cleaned.append({"text": t, "unseen": seg["unseen"]})
    while cleaned and cleaned[-1]["text"].strip() == "":
        cleaned.pop()
    if not cleaned:
        return ""

    if all(not seg["unseen"] for seg in cleaned):
        return normalize_ws("".join(seg["text"] for seg in cleaned)).strip()

    # 혼합: 각 조각 내부 공백만 정규화(조각 경계 공백은 보존)
    out = []
    for seg in cleaned:
        text = normalize_ws(seg["text"])
        item = {"text": text}
        if seg["unseen"]:
            item["unseen"] = True
        out.append(item)
    # 앞/뒤 조각의 바깥 공백 트림
    out[0]["text"] = out[0]["text"].lstrip()
    out[-1]["text"] = out[-1]["text"].rstrip()
    return [s for s in out if s["text"]]


def plain_text(tokens):
    return normalize_ws("".join(t for t, _u, _b in tokens)).strip()


def split_runs(tokens):
    """인접한 같은 bold 상태의 토큰을 런으로 묶는다 → [(bold, [(text, unseen), ...]), ...]."""
    runs = []
    for text, unseen, bold in tokens:
        if runs and runs[-1][0] == bold:
            runs[-1][1].append((text, unseen))
        else:
            runs.append((bold, [(text, unseen)]))
    return runs


def is_speaker_run(bold, sub):
    return bold and "".join(t for t, _u in sub).strip().endswith(":")


def split_body_brackets(body):
    """대사 본문 토큰을 인라인 대괄호 블록 기준으로 쪼갠다.

    body=[(text, unseen), ...] → [(kind, [(text, unseen), ...]), ...]
    kind: 'text'(대사) | 'scene'([Scene: ...]) | 'direction'(그 외 [...]).
    연속된 'text' 조각은 합치고, 각 대괄호 블록은 독립 조각으로 둔다.
    """
    pieces = []

    def push_text(text, unseen):
        if not text:
            return
        if pieces and pieces[-1][0] == "text":
            pieces[-1][1].append((text, unseen))
        else:
            pieces.append(("text", [(text, unseen)]))

    for text, unseen in body:
        idx = 0
        for m in BRACKET_RE.finditer(text):
            if m.start() > idx:
                push_text(text[idx:m.start()], unseen)
            inner = m.group(0)
            kind = "scene" if SCENE_BRACKET_RE.match(inner) else "direction"
            pieces.append((kind, [(inner, unseen)]))
            idx = m.end()
        if idx < len(text):
            push_text(text[idx:], unseen)
    return pieces


def parse_dialogue(tokens):
    """한 문단을 굵은 화자 라벨('…:') 기준으로 나눠 대사 항목 리스트로 변환.

    한 <p> 안에 여러 화자가 들어 있어도(예: Monica: … Joey: …) 각각 분리한다.
    화자가 아닌 굵은 글씨(강조)는 해당 화자의 대사 텍스트로 둔다.
    """
    runs = split_runs(tokens)
    groups = []  # {"speaker": str, "body": [(text, unseen), ...]}
    current = None
    for bold, sub in runs:
        if is_speaker_run(bold, sub):
            if current:
                groups.append(current)
            speaker = "".join(t for t, _u in sub).strip()[:-1].strip()
            current = {"speaker": speaker, "body": []}
        elif current is not None:
            current["body"].extend(sub)
        # 화자가 아직 없고 비화자 텍스트면 무시(잔여 헤더 등)
    if current:
        groups.append(current)

    entries = []
    for g in groups:
        # 본문에 인라인 대괄호([Scene]/[Time Lapse] 등)가 섞여 있으면 분리
        text_body = []
        extras = []  # (kind, segments) — 대사 뒤에 별도 항목으로
        for kind, sub in split_body_brackets(g["body"]):
            if kind == "text":
                text_body.extend(sub)
            else:
                extras.append((kind, sub))

        english = to_value(merge_segments(text_body))
        if english:
            entries.append(
                {
                    "type": "dialogue",
                    "speaker": g["speaker"],
                    "english": english,
                    "korean": "",
                }
            )
        for kind, sub in extras:
            entries.append({"type": kind, "text": to_value(merge_segments(sub))})
    return entries


def classify(tokens):
    """문단 토큰을 항목 리스트로 변환(스킵이면 빈 리스트, 다중 화자면 여러 개)."""
    text = plain_text(tokens)
    if not text:
        return []
    # 전사자 크레딧/메일 헤더 스킵
    if "@" in text or text.lower().startswith(("written by", "transcribed by")):
        return []

    body_segments = merge_segments([(t, u) for t, u, _b in tokens])

    # 1) 장면 헤딩
    if text.startswith("[Scene:") or text.startswith("[scene:"):
        return [{"type": "scene", "text": to_value(body_segments)}]

    # 2) 섹션 구분
    if SECTION_RE.match(text.strip("[]").strip()):
        return [{"type": "section", "text": to_value(body_segments)}]

    # 3) 대사 (굵은 화자 라벨이 하나라도 있으면 — 다중 화자 분리)
    runs = split_runs(tokens)
    if any(is_speaker_run(bold, sub) for bold, sub in runs):
        return parse_dialogue(tokens)

    # 4) 단독 괄호 지침 / 5) 그 외 내레이션 → 지침으로
    return [{"type": "direction", "text": to_value(body_segments)}]


def extract_credits(paragraphs):
    """헤더 문단에서 'Written by' / 'Transcribed by' 크레딧을 추출한다.

    한 <p> 안에 <br>(=\\n)로 구분된 여러 줄로 들어있다. 반환: (written, transcribed).
    """
    written = ""
    transcribers = []
    for tokens in paragraphs:
        raw = "".join(t for t, _u, _b in tokens)
        low = raw.lower()
        if "written by" not in low and "transcribed by" not in low:
            continue
        for line in raw.splitlines():
            line = line.strip()
            m = re.match(r"written by\s*:\s*(.+)", line, re.I)
            if m:
                written = m.group(1).strip().rstrip(".")
            m = re.match(r"(?:additional transcribing by|transcribed by)\s*:\s*(.+)", line, re.I)
            if m:
                name = m.group(1).strip().rstrip(".")
                if name and name not in transcribers:
                    transcribers.append(name)
        break  # 첫 헤더 블록만
    return written, ", ".join(transcribers)


def strip_sung_marker(english):
    """대사 끝의 '(Sung:)' 마커를 떼어낸다 → (새 값, 마커가 있었는지).

    english 는 문자열 또는 [{text, unseen?}] 조각 배열.
    """
    if isinstance(english, str):
        new = SUNG_MARKER_RE.sub("", english).strip()
        return new, new != english.strip()
    if isinstance(english, list) and english:
        last = english[-1]
        text = last.get("text", "")
        new_text = SUNG_MARKER_RE.sub("", text).rstrip()
        if new_text == text.rstrip():
            return english, False
        rest = english[:-1]
        if new_text:
            rest = rest + [dict(last, text=new_text)]
        return (rest or ""), True
    return english, False


def strip_parens_text(text):
    """중첩까지 고려해 (...) 구간을 지운 나머지."""
    out = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            if depth:
                depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def is_spoken_continuation(value):
    """화자 라벨이 없지만 실은 직전 화자의 대사가 이어지는 문단인가?

    전사본은 같은 화자가 계속 말할 때 라벨을 생략하곤 한다
    (예: "(She sees Monica sneaking out) Okay, thank you very much, ...").
    순수 지침은 통째로 괄호 안이거나([Time Lapse] 같은) 대괄호 블록이므로,
    '괄호가 있으면서 괄호 밖에 실제 말이 남는' 경우만 대사로 본다.
    괄호가 아예 없는 문단(내레이션·포스터 문구·가사 등)은 건드리지 않는다.
    """
    text = value if isinstance(value, str) else "".join(s.get("text", "") for s in value)
    t = text.strip()
    if not t or t.startswith("[") or "(" not in t:
        return False
    rest = strip_parens_text(t).strip()
    return len(rest) >= 4 and any(c.isalpha() for c in rest)


def sung_dialogue(speaker, text):
    """가사 문단(화자 라벨 없음)을 '(Sung:) …' 대사 항목으로 만든다."""
    if isinstance(text, list) and text:
        first = text[0]
        english = [dict(first, text=SUNG_PREFIX + first.get("text", ""))] + text[1:]
    else:
        english = SUNG_PREFIX + (text or "")
    return {"type": "dialogue", "speaker": speaker, "english": english, "korean": ""}


def build_entries(paragraphs, italic_ratios):
    """문단들을 항목 리스트로 만들되, 화자 라벨이 없는 문단을 두 가지로 되살린다.

    전사본은 같은 화자가 이어 말하거나 노래할 때 'Phoebe:' 라벨을 생략한다.
    그대로 두면 전부 direction(지침)이 되므로:
      1) 노래 가사 — 이탤릭(<i>/<em>) 비율이 높은 문단 → 직전 화자의 대사 + '(Sung:)' 접두어.
         (이탤릭 단독은 강조·속마음 독백에도 쓰이지만, '화자 라벨 없음'과 겹치는 건 가사뿐이다.)
      2) 이어지는 대사 — 괄호 밖에 실제 말이 남는 문단 → 직전 화자의 대사.
    포스터 문구·내레이션처럼 이탤릭도 괄호도 없는 문단은 그대로 지침으로 둔다.
    """
    entries = []
    last_speaker = None
    pending_singer = None  # 직전 대사가 '(Sung:)'로 끝났으면 그 화자

    for tokens, italic in zip(paragraphs, italic_ratios):
        norm = [(normalize_ws(t) if t.strip() else t, u, b) for t, u, b in tokens]
        new = classify(norm)
        if not new:
            continue

        # 화자 라벨이 없어 지침 하나로만 잡힌 문단을 되살린다
        if len(new) == 1 and new[0].get("type") == "direction":
            text = new[0]["text"]
            plain = text if isinstance(text, str) else "".join(
                s.get("text", "") for s in text
            )
            is_bracket = plain.strip().startswith("[")
            singer = pending_singer or last_speaker
            if singer and not is_bracket and (
                italic >= ITALIC_SONG_RATIO or pending_singer
            ):
                new[0] = sung_dialogue(singer, text)
            elif last_speaker and is_spoken_continuation(text):
                new[0] = {
                    "type": "dialogue",
                    "speaker": last_speaker,
                    "english": text,
                    "korean": "",
                }
        pending_singer = None  # 마커는 바로 다음 문단에만 적용

        # 대사 끝의 '(Sung:)' 마커는 떼고(가사 줄로 옮겨감) 화자를 기억
        for e in new:
            if e.get("type") == "dialogue":
                stripped, was_sung = strip_sung_marker(e["english"])
                if was_sung:
                    e["english"] = stripped
                    pending_singer = e["speaker"]
                last_speaker = e["speaker"]

        # 마커뿐이던 대사는 본문이 비므로 버린다(가사가 다음 항목으로 들어옴)
        new = [
            e
            for e in new
            if not (e.get("type") == "dialogue" and not e["english"])
        ]
        entries.extend(new)

    return entries


def strip_ep_prefix(title):
    """'S01E07 · The One ...' → 'The One ...' (코드 접두어 제거)."""
    return EP_PREFIX_RE.sub("", title or "").strip()


def find_index_json(out_path):
    """--out 위치에서 상위로 올라가며 index.json 을 찾는다(보통 data/index.json)."""
    d = os.path.dirname(os.path.abspath(out_path))
    while True:
        cand = os.path.join(d, "index.json")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def title_from_index(out_path):
    """index.json 에서 --out 파일명과 같은 에피소드의 title(접두어 제거)을 찾는다."""
    idx_path = find_index_json(out_path)
    if not idx_path:
        return None
    try:
        with open(idx_path, encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        return None
    base = os.path.basename(out_path)
    for drama in idx.get("dramas", []):
        for ep in drama.get("episodes", []):
            if os.path.basename(ep.get("file", "")) == base:
                return strip_ep_prefix(ep.get("title", ""))
    return None


def load_html(url, file):
    if file:
        with open(file, encoding="utf-8", errors="replace") as f:
            return f.read()
    with urlopen(url) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="Friends 트랜스크립트 임포터")
    ap.add_argument("--url", default=DEFAULT_URL, help="소스 HTML URL")
    ap.add_argument("--file", help="로컬 HTML 파일(있으면 --url 무시)")
    ap.add_argument("--out", required=True, help="출력 JSON 경로")
    ap.add_argument("--drama", default="Friends", help="작품명(쇼 이름)")
    ap.add_argument(
        "--title",
        default=None,
        help="에피소드 제목. 없으면 index.json 에서 --out 파일명으로 찾아 코드 접두어를 제거해 사용.",
    )
    ap.add_argument("--season", type=int, default=1)
    ap.add_argument("--episode", type=int, default=1)
    args = ap.parse_args()

    html = load_html(args.url, args.file)
    parser = TranscriptParser()
    parser.feed(html)

    written, transcribed = extract_credits(parser.paragraphs)

    entries = build_entries(parser.paragraphs, parser.italic_ratios)

    title = strip_ep_prefix(args.title) if args.title else title_from_index(args.out)

    data = {
        "title": title or "",
        "drama": args.drama,
        "season": args.season,
        "episode": args.episode,
        "writtenBy": written,
        "transcribedBy": transcribed,
        "lines": entries,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # 요약
    from collections import Counter

    kinds = Counter(e.get("type", "dialogue") for e in entries)
    unseen_count = 0
    for e in entries:
        for field in ("english", "text", "korean"):
            v = e.get(field)
            if isinstance(v, list):
                unseen_count += sum(1 for s in v if s.get("unseen"))
    print(f"→ {args.out}", file=sys.stderr)
    print(f"  title: {title or '(없음 — index.json에서 못 찾음)'}", file=sys.stderr)
    print(f"  총 {len(entries)} 항목: " + ", ".join(f"{k}={n}" for k, n in kinds.items()), file=sys.stderr)
    print(f"  unseen 조각: {unseen_count}", file=sys.stderr)


if __name__ == "__main__":
    main()
