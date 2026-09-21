"""Description, JSON, and mixed queries in community-visual-v1 space.

VISION.app blends a written description with optional JSON examples. Community
cannot use SigLIP or OWLv2, so the description is rendered into the same
six-face integer extractor used for panoramic queries. JSON examples stay
Street View faces. Mixed search is a weighted average of those two embeddings.
"""

from __future__ import annotations

from .features import MODEL_ID, embedding_for, render_faces, signed_int8


PROMPT_MAX = 400
DESCRIPTION_WEIGHTS = (0, 25, 50, 75, 100)
# Longer phrases first so "bird nest" wins over "bird".
PALETTE = (
    ("bird nest", 96, 72, 48),
    ("forest", 28, 88, 38),
    ("ocean", 20, 70, 140),
    ("water", 32, 92, 154),
    ("night", 22, 26, 42),
    ("brick", 150, 62, 48),
    ("snow", 240, 244, 248),
    ("sand", 196, 168, 118),
    ("road", 86, 86, 86),
    ("sky", 92, 152, 214),
    ("orange", 220, 120, 30),
    ("purple", 130, 50, 170),
    ("yellow", 210, 190, 40),
    ("green", 40, 160, 50),
    ("brown", 120, 70, 40),
    ("white", 230, 230, 230),
    ("black", 25, 25, 25),
    ("pink", 210, 90, 140),
    ("blue", 40, 70, 190),
    ("grey", 128, 128, 128),
    ("gray", 128, 128, 128),
    ("red", 210, 42, 42),
)
DARK_WORDS = ("dark", "night", "black", "shadow")
BRIGHT_WORDS = ("bright", "sunny", "white", "snow", "daylight")


def normalize_prompt(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())


def parse_prompt(value: str | None) -> str:
    prompt = normalize_prompt(value)
    if not prompt:
        return ""
    if len(prompt) > PROMPT_MAX:
        raise ValueError("invalid_query")
    return prompt


def snap_description_weight(value, *, has_json: bool, has_prompt: bool) -> int:
    if not has_json:
        return 100
    if not has_prompt:
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 50
    return min(DESCRIPTION_WEIGHTS, key=lambda item: abs(item - number))


def _padded(prompt: str) -> str:
    return f" {prompt} "


def _tint_description_faces(faces: bytearray, prompt: str) -> None:
    padded = _padded(prompt)
    remaining = padded
    targets = []
    for token, red, green, blue in sorted(PALETTE, key=lambda item: len(item[0]), reverse=True):
        needle = f" {token} "
        if needle in remaining:
            targets.append((red, green, blue))
            remaining = remaining.replace(needle, " ")
    dark = sum(1 for word in DARK_WORDS if f" {word} " in padded)
    bright = sum(1 for word in BRIGHT_WORDS if f" {word} " in padded)
    if not targets and not dark and not bright:
        return
    if targets:
        count = len(targets)
        target_r = sum(item[0] for item in targets) // count
        target_g = sum(item[1] for item in targets) // count
        target_b = sum(item[2] for item in targets) // count
        strength = min(70, 25 + 15 * min(4, count))
    else:
        target_r = target_g = target_b = 128
        strength = 0
    shift = bright * 18 - dark * 18
    keep = 100 - strength
    for index in range(0, len(faces), 3):
        red = (faces[index] * keep + target_r * strength) // 100 + shift
        green = (faces[index + 1] * keep + target_g * strength) // 100 + shift
        blue = (faces[index + 2] * keep + target_b * strength) // 100 + shift
        faces[index] = 0 if red < 0 else 255 if red > 255 else red
        faces[index + 1] = 0 if green < 0 else 255 if green > 255 else green
        faces[index + 2] = 0 if blue < 0 else 255 if blue > 255 else blue


def description_faces(prompt: str, lane: str) -> bytes:
    normalized = parse_prompt(prompt)
    if not normalized:
        raise ValueError("invalid_query")
    faces = bytearray(render_faces(f"description:{normalized}", "prompt", lane, MODEL_ID))
    _tint_description_faces(faces, normalized)
    return bytes(faces)


def description_embedding(prompt: str, lane: str) -> bytes:
    return embedding_for(lane, description_faces(prompt, lane))


def mix_embeddings(visual: bytes, textual: bytes, description_weight: int) -> bytes:
    if len(visual) != len(textual):
        raise ValueError("query_width")
    weight = snap_description_weight(description_weight, has_json=True, has_prompt=True)
    if weight <= 0:
        return visual
    if weight >= 100:
        return textual
    visual_weight = 100 - weight
    mixed = []
    for vis, text in zip(signed_int8(visual), signed_int8(textual)):
        value = int((vis * visual_weight + text * weight) / 100)
        mixed.append(max(-127, min(127, value)))
    return bytes((item + 256) % 256 if item < 0 else item for item in mixed)
