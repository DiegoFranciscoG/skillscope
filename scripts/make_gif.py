"""Turn docs/img/frames/*.png (from web/scripts/capture.mjs) into docs/img/demo.gif."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "docs" / "img" / "frames"
OUT = ROOT / "docs" / "img" / "demo.gif"
WIDTH = 960
# Milliseconds each kind of frame stays on screen; the name after the number picks the pace.
PACE = {"explore": 1800, "typing": 450, "search": 1800, "detail": 2600, "gaps": 2400}


def main() -> None:
    paths = sorted(FRAMES.glob("*.png"))
    if not paths:
        raise SystemExit("No frames: run `node web/scripts/capture.mjs` first.")
    images: list[Image.Image] = []
    durations: list[int] = []
    for path in paths:
        with Image.open(path) as source:
            frame = source.convert("RGB")
        height = round(frame.height * WIDTH / frame.width)
        frame = frame.resize((WIDTH, height), Image.Resampling.LANCZOS)
        images.append(frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
        durations.append(PACE.get(path.stem.split("-", 1)[1], 1000))
    images[0].save(
        OUT, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True
    )
    print(f"{OUT.relative_to(ROOT)}: {len(images)} frames, {OUT.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    main()
