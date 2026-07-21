"""从 miku/icon.png 生成 Windows 多尺寸 icon.ico。

详细信息/小图标视图需要经典 BMP/DIB 条目；仅 PNG 压缩 ICO 在「详细信息」下列表
常显示空白（大图标模式仍正常）。此处小尺寸用 BMP，256 用 PNG。
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "miku" / "icon.png"
OUTS = [
    Path(__file__).resolve().parent / "icon.ico",
    ROOT / "miku" / "icon.ico",
    ROOT / "frontend" / "assets" / "miku.ico",
]


def _image_to_bmp_dib(im: Image.Image) -> bytes:
    """Classic ICO image: BITMAPINFOHEADER + BGRA XOR (bottom-up) + 1-bit AND mask."""
    im = im.convert("RGBA")
    w, h = im.size
    # BGRA bottom-up
    pixels = im.load()
    xor = bytearray()
    row_pad = (4 - (w * 4) % 4) % 4
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            xor.extend((b, g, r, a))
        xor.extend(b"\x00" * row_pad)

    # AND mask: 1 bit per pixel, padded to 32-bit boundary per row
    and_row_bytes = ((w + 31) // 32) * 4
    and_mask = bytearray(and_row_bytes * h)  # fully opaque → 0

    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        w,           # biWidth
        h * 2,       # biHeight (XOR + AND)
        1,           # biPlanes
        32,          # biBitCount
        0,           # BI_RGB
        len(xor) + len(and_mask),
        0,
        0,
        0,
        0,
    )
    return header + bytes(xor) + bytes(and_mask)


def _image_to_png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def build_ico(src: Path, dest: Path) -> None:
    src_img = Image.open(src).convert("RGBA")
    w, h = src_img.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(src_img, ((side - w) // 2, (side - h) // 2), src_img)

    # Small sizes: BMP (Details view). 256: PNG (modern shell large icon).
    specs: list[tuple[int, bytes]] = []
    for s in (16, 24, 32, 48, 64, 128):
        im = canvas.resize((s, s), Image.Resampling.LANCZOS)
        specs.append((s, _image_to_bmp_dib(im)))
    im256 = canvas.resize((256, 256), Image.Resampling.LANCZOS)
    specs.append((256, _image_to_png(im256)))

    count = len(specs)
    offset = 6 + 16 * count
    parts = [struct.pack("<HHH", 0, 1, count)]
    blobs = []
    for s, data in specs:
        blobs.append(data)
        parts.append(
            struct.pack(
                "<BBBBHHII",
                0 if s >= 256 else s,
                0 if s >= 256 else s,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        offset += len(data)
    parts.extend(blobs)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"".join(parts))
    print(f"Wrote {dest} ({dest.stat().st_size} bytes, sizes={[s for s, _ in specs]})")


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Source icon not found: {SRC}")
    for out in OUTS:
        build_ico(SRC, out)


if __name__ == "__main__":
    main()
