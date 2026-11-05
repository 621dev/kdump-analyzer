"""webui/static/icon.svg와 같은 모양의 Windows 아이콘(kdump-tools.ico)을 만듭니다.

외부 라이브러리 없이 PNG를 직접 그려 ICO 파일에 담습니다. 아이콘 모양을 바꿀 때만 다시 실행합니다.
    python windows/make-icon.py            # windows/kdump-tools.ico 생성
    python windows/make-icon.py --preview  # 256px 미리보기 PNG도 함께 저장
"""
import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
BLUE = (37, 99, 235)      # #2563eb
WHITE = (255, 255, 255)
POINTS = [(7, 21), (12, 15), (16, 19), (20, 11), (25, 21)]   # icon.svg의 꺾은선 (32x32 기준)
STROKE = 2.6
SIZES = [16, 24, 32, 48, 64, 128, 256]
SUPERSAMPLE = 3


def inside_rounded_square(x, y):
    """32x32 안의 반지름 8 둥근 사각형인지."""
    qx, qy = abs(x - 16) - 8, abs(y - 16) - 8
    outside = math.hypot(max(qx, 0), max(qy, 0))
    return outside + min(max(qx, qy), 0) - 8 <= 0


def dist_to_segment(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size):
    segments = list(zip(POINTS, POINTS[1:]))
    n = SUPERSAMPLE * SUPERSAMPLE
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            covered = 0
            r = g = b = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = (px + (sx + 0.5) / SUPERSAMPLE) / size * 32
                    y = (py + (sy + 0.5) / SUPERSAMPLE) / size * 32
                    if not inside_rounded_square(x, y):
                        continue
                    covered += 1
                    stroke = any(dist_to_segment(x, y, a, c) <= STROKE / 2 for a, c in segments)
                    color = WHITE if stroke else BLUE
                    r += color[0]
                    g += color[1]
                    b += color[2]
            if covered:
                row += bytes((r // covered, g // covered, b // covered, covered * 255 // n))
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))
    return rows


def png(size, rows):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    images = {size: png(size, render(size)) for size in SIZES}
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, data = b"", b""
    for size in SIZES:
        blob = images[size]
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    path = os.path.join(HERE, "kdump-tools.ico")
    with open(path, "wb") as f:
        f.write(header + entries + data)
    print("만들었습니다: %s (%d KB)" % (path, os.path.getsize(path) // 1024))
    if "--preview" in sys.argv:
        preview = os.path.join(HERE, "kdump-tools-preview.png")
        with open(preview, "wb") as f:
            f.write(images[256])
        print("미리보기: " + preview)


if __name__ == "__main__":
    main()
