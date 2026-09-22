"""Bild-Upload-Helfer für das WebPanel.

Karten werden für Discord bewusst als kompakte WebP-Dateien gespeichert. Sehr
große Originale und lange Animationen sind ein häufiger Grund dafür, dass ein
Embed-Bild erst deutlich nach der Nachricht erscheint.
"""

from __future__ import annotations

import math
import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


WEBP_QUALITY = _env_int("CARD_IMAGE_WEBP_QUALITY", 82, 1, 100)
WEBP_METHOD = 5
MAX_CARD_DIMENSION = _env_int("CARD_IMAGE_MAX_DIMENSION", 1200, 256, 4096)
MAX_ANIMATED_DIMENSION = _env_int("CARD_IMAGE_ANIMATED_MAX_DIMENSION", 960, 256, 2048)
MAX_ANIMATION_FRAMES = _env_int("CARD_IMAGE_MAX_FRAMES", 80, 1, 300)
MAX_CARD_BYTES = _env_int("CARD_IMAGE_MAX_BYTES", 6 * 1024 * 1024, 512 * 1024, 25 * 1024 * 1024)


def _thumbnail(image: Image.Image, max_dimension: int) -> Image.Image:
    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    return image


def _static_frame(source: Image.Image) -> Image.Image:
    frame = ImageOps.exif_transpose(source).convert("RGBA" if "A" in source.getbands() else "RGB")
    return _thumbnail(frame, MAX_CARD_DIMENSION)


def _save_static_webp(image: Image.Image, dest: Path, *, quality: int = WEBP_QUALITY) -> None:
    image.save(dest, format="WEBP", quality=quality, method=WEBP_METHOD)


def _animation_frames(source: Image.Image) -> tuple[list[Image.Image], list[int]]:
    raw_frames: list[Image.Image] = []
    raw_durations: list[int] = []
    default_duration = int(source.info.get("duration", 100) or 100)
    for frame in ImageSequence.Iterator(source):
        raw_frames.append(_thumbnail(frame.convert("RGBA"), MAX_ANIMATED_DIMENSION))
        raw_durations.append(max(20, int(frame.info.get("duration", default_duration) or default_duration)))

    if not raw_frames:
        raise ValueError("image_without_frames")
    if len(raw_frames) <= MAX_ANIMATION_FRAMES:
        return raw_frames, raw_durations

    # Lange Animationen gleichmäßig ausdünnen. Die Dauer ausgelassener Frames
    # wird dem jeweils behaltenen Frame zugeschlagen, damit das Tempo gleich bleibt.
    step = math.ceil(len(raw_frames) / MAX_ANIMATION_FRAMES)
    frames: list[Image.Image] = []
    durations: list[int] = []
    for start in range(0, len(raw_frames), step):
        frames.append(raw_frames[start])
        durations.append(sum(raw_durations[start:start + step]))
    return frames, durations


def _save_animated_webp(source: Image.Image, dest: Path) -> None:
    frames, durations = _animation_frames(source)
    first, *rest = frames
    first.save(
        dest,
        format="WEBP",
        save_all=bool(rest),
        append_images=rest,
        duration=durations,
        loop=int(source.info.get("loop", 0) or 0),
        quality=WEBP_QUALITY,
        method=WEBP_METHOD,
    )

    if dest.stat().st_size <= MAX_CARD_BYTES:
        return

    # Discord soll die Karte lieber sofort als Standbild zeigen als minutenlang
    # an einer übergroßen Animation zu laden.
    _save_static_webp(first, dest, quality=min(WEBP_QUALITY, 76))


def _write_optimized_webp(raw: bytes, dest: Path) -> None:
    temp = dest.with_name(f".{dest.name}.tmp")
    try:
        with Image.open(BytesIO(raw)) as source:
            is_animated = bool(getattr(source, "is_animated", False) and getattr(source, "n_frames", 1) > 1)
            if is_animated:
                _save_animated_webp(source, temp)
            else:
                _save_static_webp(_static_frame(source), temp)
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)


def save_card_upload(raw: bytes, ext: str, directory: Path, stem: str) -> Path:
    """Validiert und speichert ein Kartenbild als Discord-freundliches WebP."""
    del ext  # Der echte Bildtyp wird von Pillow erkannt, nicht vom Dateinamen.
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{stem}.webp"
    _write_optimized_webp(raw, dest)
    return dest


def card_image_needs_optimization(path: Path) -> bool:
    """Prüft ohne Re-Encoding, ob eine lokale Karte noch dem alten Format entspricht."""
    if path.suffix.lower() != ".webp" or path.stat().st_size > MAX_CARD_BYTES:
        return True
    with Image.open(path) as image:
        animated = bool(getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1)
        max_dimension = MAX_ANIMATED_DIMENSION if animated else MAX_CARD_DIMENSION
        if max(image.size) > max_dimension:
            return True
        return animated and getattr(image, "n_frames", 1) > MAX_ANIMATION_FRAMES


def optimize_existing_card_image(path: Path) -> Path:
    """Migriert ein vorhandenes lokales Kartenbild atomar zu optimiertem WebP."""
    dest = path.with_suffix(".webp")
    _write_optimized_webp(path.read_bytes(), dest)
    if path != dest:
        path.unlink(missing_ok=True)
    return dest
