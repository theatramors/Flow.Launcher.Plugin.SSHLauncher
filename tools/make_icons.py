# -*- coding: utf-8 -*-
"""Generate the plugin icons as RGBA PNGs (stdlib only, supersampled).

    python3 tools/make_icons.py
"""

import math
import os
import struct
import zlib

SIZE = 256
SS = 4  # supersampling factor

BASE = (0x1E, 0x1E, 0x2E)
BORDER = (0x31, 0x32, 0x44)
BLUE = (0x89, 0xB4, 0xFA)
GREEN = (0xA6, 0xE3, 0xA1)
RED = (0xF3, 0x8B, 0xA8)
YELLOW = (0xF9, 0xE2, 0xAF)


def write_png(path, pixels, width, height):
    raw = b"".join(
        b"\x00" + b"".join(bytes(pixels[y][x]) for x in range(width)) for y in range(height)
    )

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + data)


class Canvas(object):
    def __init__(self, size=SIZE):
        self.size = size
        self.alpha = [[0.0] * size for _ in range(size)]
        self.colour = [[(0, 0, 0)] * size for _ in range(size)]

    def paint(self, predicate, colour):
        size = self.size
        for y in range(size):
            row_alpha = self.alpha[y]
            row_colour = self.colour[y]
            for x in range(size):
                hits = 0
                for sy in range(SS):
                    py = y + (sy + 0.5) / SS
                    for sx in range(SS):
                        px = x + (sx + 0.5) / SS
                        if predicate(px, py):
                            hits += 1
                if not hits:
                    continue
                coverage = hits / float(SS * SS)
                old = row_alpha[x]
                new = old + coverage * (1.0 - old)
                if new <= 0:
                    continue
                weight = coverage / new if new else 1.0
                blended = tuple(
                    int(round(row_colour[x][i] * (1 - weight) + colour[i] * weight)) for i in range(3)
                )
                row_colour[x] = blended
                row_alpha[x] = new

    def to_pixels(self):
        size = self.size
        return [
            [
                (
                    self.colour[y][x][0],
                    self.colour[y][x][1],
                    self.colour[y][x][2],
                    int(round(self.alpha[y][x] * 255)),
                )
                for x in range(size)
            ]
            for y in range(size)
        ]


def rounded_rect(x0, y0, x1, y1, radius):
    def predicate(x, y):
        dx = max(x0 + radius - x, 0) + max(x - (x1 - radius), 0)
        dy = max(y0 + radius - y, 0) + max(y - (y1 - radius), 0)
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        return dx * dx + dy * dy <= radius * radius

    return predicate


def capsule(x0, y0, x1, y1, half_width):
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy

    def predicate(x, y):
        if length_sq == 0:
            return (x - x0) ** 2 + (y - y0) ** 2 <= half_width ** 2
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / length_sq))
        px, py = x0 + t * dx, y0 + t * dy
        return (x - px) ** 2 + (y - py) ** 2 <= half_width ** 2

    return predicate


def circle(cx, cy, radius):
    return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius


def ring(cx, cy, outer, inner):
    return lambda x, y: inner ** 2 <= (x - cx) ** 2 + (y - cy) ** 2 <= outer ** 2


def ssh_icon():
    canvas = Canvas()
    canvas.paint(rounded_rect(14, 26, 242, 230, 38), BASE)
    canvas.paint(ring(128, 128, 999, 0) and (lambda x, y: False), BORDER)
    # window frame
    canvas.paint(
        lambda x, y: (abs(x - 128) <= 114 and abs(y - 90) <= 2) or (abs(x - 128) <= 2 and 26 <= y <= 230),
        BORDER,
    )
    for index, colour in enumerate((RED, YELLOW, GREEN)):
        canvas.paint(circle(46 + index * 22, 62, 7), colour)
    # prompt chevron + cursor
    canvas.paint(capsule(66, 128, 100, 158, 7), BLUE)
    canvas.paint(capsule(100, 158, 66, 188, 7), BLUE)
    canvas.paint(capsule(122, 188, 176, 188, 7), GREEN)
    return canvas


def settings_icon():
    canvas = Canvas()
    cx = cy = 128
    # Short, wide teeth on a thick ring read as a gear; the hub hole is simply
    # left unpainted (painting then clearing leaves a dark anti-aliased ring).
    canvas.paint(ring(cx, cy, 94, 34), BLUE)
    for index in range(8):
        angle = index * math.pi / 4
        x0, y0 = cx + math.cos(angle) * 78, cy + math.sin(angle) * 78
        x1, y1 = cx + math.cos(angle) * 110, cy + math.sin(angle) * 110
        canvas.paint(capsule(x0, y0, x1, y1, 16), BLUE)
    return canvas.to_pixels()


def main():
    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Images")
    os.makedirs(target, exist_ok=True)
    ssh_path = os.path.join(target, "ssh.png")
    write_png(ssh_path, ssh_icon().to_pixels(), SIZE, SIZE)
    settings_path = os.path.join(target, "settings.png")
    write_png(settings_path, settings_icon(), SIZE, SIZE)
    for path in (ssh_path, settings_path):
        print("%s  %d bytes" % (path, os.path.getsize(path)))


if __name__ == "__main__":
    main()
