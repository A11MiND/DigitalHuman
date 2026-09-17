#!/usr/bin/env python3
"""Generate unified lobby-card portraits for every character.

The lobby cards were a mix of anime, 3D and photographic art. This
re-renders each character in ONE house style — upper body, smiling,
welcoming, flat pastel backdrop — using MiniMax image-01 with the
character's existing portrait as a subject reference, so the face and
costume stay recognisably the same person.

Output goes to static/images/cards/<id>.png, which is what the lobby
card reads (see `art` in static/js/i18n.js). The chat avatar videos are
untouched.

  ./scripts/gen_card_portraits.py --list
  ./scripts/gen_card_portraits.py --only qin-shihuang --count 3
  ./scripts/gen_card_portraits.py --all --count 3
  ./scripts/gen_card_portraits.py --pick qin-shihuang=2
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CHARACTERS = ROOT / "characters"
CARDS_DIR = ROOT / "static" / "images" / "cards"
DRAFTS = ROOT / ".generated" / "card-portraits"

HOSTS = {"cn": "api.minimaxi.com", "global": "api.minimax.io"}


def _env(name: str, default: str = "") -> str:
    """Read from the process env, falling back to the project .env."""
    val = os.getenv(name)
    if val:
        return val.strip()
    envfile = ROOT / ".env"
    if envfile.is_file():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return default


API_KEY = _env("MINIMAX_API_KEY")
REGION = (_env("MINIMAX_REGION", "cn") or "cn").lower()
API_BASE = f"https://{HOSTS.get(REGION, HOSTS['cn'])}/v1"

# ── House style ───────────────────────────────────────────────────────
# Shared by every card so the row reads as one set.
STYLE = (
    "photorealistic studio portrait, upper body from the chest up, facing camera, "
    "warm genuine smile, friendly welcoming expression, "
    "neutral white studio light on the subject only, high-key commercial photography, "
    "true-to-life natural colour. Background: solid flat matte {tint} paper backdrop, "
    "hex {hex}, lit perfectly flat and even like a colour swatch, no light falloff, "
    "no warm glow, no golden-hour cast, no spotlight, no gradient, no vignette. "
    "No scenery, no text, no watermark, no border. Sharp focus on the eyes, "
    "shallow depth of field on the subject only, centred square composition with "
    "headroom above the hair, editorial magazine quality"
)

NEGATIVE = (
    "anime, cartoon, illustration, painting, 3d render, cgi, full body, legs, "
    "landscape, text, watermark, frowning, stern, dark lighting, heavy shadows, "
    "profile view, looking away, multiple people, vignette, film grain, sepia, "
    "dark background, golden hour, warm glow, orange cast, sunset lighting, "
    "gradient background, spotlight, rim light, textured background, fabric backdrop"
)

# Per-character costume/identity brief + the pastel field from the design.
# `tint` must stay in sync with CHARACTERS[].tint in static/js/i18n.js.
SUBJECTS: dict[str, dict] = {
    "character-49fd372d": {
        "label": "李白 / Li Bai",
        "tint": "pale butter yellow",
        "hex": "#F8F0CB",
        "brief": (
            "a Tang dynasty Chinese male poet in his thirties, shoulders squared to "
            "the camera, flowing white silk hanfu robes with wide sleeves, "
            "long dark hair in a topknot with a simple hairpin, neat short beard, "
            "holding a small white porcelain wine cup near his chest, "
            "cheerful romantic scholar, big warm genuine smile, eyes bright with "
            "good humour"
        ),
    },
    "qin-shihuang": {
        "label": "秦始皇 / Qin Shi Huang",
        "tint": "pale mint green",
        "hex": "#DCEEE3",
        "brief": (
            "the first emperor of China, a poised Chinese man of middle age, "
            "matching exactly the reference image's crown with its hanging bead "
            "strings, hairstyle, and the brown and gold robe with grey-blue "
            "embroidered collar, neat short beard, broad warm smile with the "
            "corners of the mouth clearly raised, eyes crinkled with happiness, "
            "cheerful and approachable, not stern, not serious"
        ),
    },
    "elizabeth-i": {
        "label": "Elizabeth I",
        "tint": "pale lilac",
        "hex": "#E4DDF6",
        "brief": (
            "Queen Elizabeth I of England, a regal pale-skinned woman with tightly "
            "curled auburn red hair, a wide white starched Elizabethan lace ruff "
            "collar, strands of pearls, a small jewelled gold crown set with pearls, "
            "richly embroidered dark gown, refined intelligent gaze, warm confident "
            "smile, Tudor period, NOT Elizabeth II"
        ),
    },
    "character-b4e8368c": {
        "label": "杜甫 / Du Fu",
        "tint": "pale sage green",
        "hex": "#E7EEDC",
        "brief": (
            "a Tang dynasty Chinese male poet in his fifties, plain undyed scholar's "
            "robe with a dark collar band, black cloth futou scholar cap, "
            "greying beard and moustache, weathered kind face, "
            "gentle compassionate smile, humble and welcoming"
        ),
    },
    "maryknoll-teacher": {
        "label": "小瑪老師 / Mr Ma",
        "tint": "pale sky blue",
        "hex": "#DDE8F5",
        "brief": (
            "matching exactly the reference image's young Hong Kong Chinese man: "
            "tousled dark hair, thin wire-frame glasses, black blazer over a "
            "white shirt and dark tie, clean-shaven, warm genuine smile, "
            "approachable and encouraging school admissions teacher, "
            "professional but relaxed, not stern, not serious"
        ),
    },
    "you-beauty-advisor": {
        "label": "詩雅 / Ivy",
        "tint": "pale blush pink",
        "hex": "#FBE4DC",
        "brief": (
            "a polished young Hong Kong Chinese woman working as a medical-aesthetics "
            "client consultant, soft cream blouse, long straight dark hair, "
            "subtle natural makeup, calm reassuring professional smile, "
            "warm and attentive"
        ),
    },
    "you-beauty-newclient": {
        "label": "凱晴 / Kelly",
        "tint": "pale peach",
        "hex": "#FBEEDC",
        "brief": (
            "a casual young Hong Kong Chinese woman in her late twenties visiting a "
            "clinic for the first time, simple light knit top, shoulder-length dark "
            "hair, minimal makeup, slightly shy but friendly open smile, "
            "natural and approachable"
        ),
    },
}


def build_prompt(cfg: dict) -> str:
    return f"{cfg['brief']}. {STYLE.format(tint=cfg['tint'], hex=cfg['hex'])}. Avoid: {NEGATIVE}."


def reference_data_uri(char_id: str, ref_override: Path | None = None) -> str:
    """Load the character's reference portrait as a normalised JPEG data URI.

    Several portraits have a .jpg name but are really PNG or WebP, so decode
    with Pillow and re-encode rather than trusting the extension. Pass
    `ref_override` to use a specific file instead of character.json's icon
    (e.g. a different official artwork that better matches the character).
    """
    if ref_override is not None:
        src = ref_override
    else:
        meta_path = CHARACTERS / char_id / "character.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        src = CHARACTERS / char_id / meta.get("icon", "portrait.jpg")
    if not src.is_file():
        raise SystemExit(f"missing portrait: {src}")

    im = Image.open(src).convert("RGB")
    im.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def generate(char_id: str, count: int, ref_override: Path | None = None) -> list[Path]:
    cfg = SUBJECTS[char_id]
    out_dir = DRAFTS / char_id
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "model": "image-01",
        "prompt": build_prompt(cfg),
        "subject_reference": [
            {"type": "character", "image_file": reference_data_uri(char_id, ref_override)}
        ],
        "aspect_ratio": "1:1",
        "n": count,
        "response_format": "url",
        "prompt_optimizer": True,
    }

    print(f"→ {cfg['label']} ({char_id}) ×{count}", flush=True)
    with httpx.Client(timeout=300.0) as client:
        res = client.post(
            f"{API_BASE}/image_generation",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
    if res.status_code >= 400:
        raise SystemExit(f"  image API {res.status_code}: {res.text[:400]}")

    data = res.json()
    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code"):
        raise SystemExit(f"  image API error: {base_resp}")

    urls: list[str] = []
    payload_data = data.get("data")
    if isinstance(payload_data, dict):
        urls += payload_data.get("image_urls") or payload_data.get("images") or []
    urls += data.get("image_urls") or []
    urls = [u for u in urls if isinstance(u, str) and u]
    if not urls:
        raise SystemExit(f"  no images returned: {json.dumps(data)[:400]}")

    saved = []
    with httpx.Client(timeout=180.0, follow_redirects=True) as client:
        for idx, url in enumerate(urls, start=1):
            dest = out_dir / f"cand-{idx}.png"
            if url.startswith("data:"):
                raw = base64.b64decode(url.split(",", 1)[-1])
            else:
                raw = client.get(url).content
            Image.open(io.BytesIO(raw)).convert("RGB").save(dest, format="PNG")
            saved.append(dest)
            print(f"  saved {dest.relative_to(ROOT)}")
    return saved


def pick(char_id: str, index: int) -> None:
    src = DRAFTS / char_id / f"cand-{index}.png"
    if not src.is_file():
        raise SystemExit(f"no such candidate: {src}")
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    dest = CARDS_DIR / f"{char_id}.png"

    # Cards render at 92:100; trim the square to that so the browser is not
    # cropping the chin or the top of a crown at display time.
    im = Image.open(src).convert("RGB")
    w, h = im.size
    target = 92 / 100
    new_w = int(round(h * target))
    if new_w < w:
        left = (w - new_w) // 2
        im = im.crop((left, 0, left + new_w, h))
    im.save(dest, format="PNG", optimize=True)
    print(f"picked {src.relative_to(ROOT)} → {dest.relative_to(ROOT)} ({im.size[0]}×{im.size[1]})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="generate for every configured character")
    ap.add_argument("--only", action="append", default=[], help="character id (repeatable)")
    ap.add_argument("--count", type=int, default=3, help="candidates per character (default 3)")
    ap.add_argument("--ref", type=Path, default=None, help="use this image file as the identity reference instead of character.json's icon")
    ap.add_argument("--pick", action="append", default=[], help="<char_id>=<n> promote a candidate")
    ap.add_argument("--list", action="store_true", help="list configured characters")
    args = ap.parse_args()

    if args.list:
        for cid, cfg in SUBJECTS.items():
            print(f"{cid:24} {cfg['label']:26} {cfg['hex']}  {cfg['tint']}")
        return

    if args.pick:
        for spec in args.pick:
            cid, _, idx = spec.partition("=")
            pick(cid, int(idx or 1))
        return

    if not API_KEY:
        raise SystemExit("MINIMAX_API_KEY not configured")

    targets = list(SUBJECTS) if args.all else args.only
    if not targets:
        ap.error("pass --all, --only <id>, --pick <id>=<n> or --list")

    for cid in targets:
        if cid not in SUBJECTS:
            raise SystemExit(f"unknown character: {cid}")
        generate(cid, args.count, ref_override=args.ref)
        time.sleep(1)


if __name__ == "__main__":
    main()
