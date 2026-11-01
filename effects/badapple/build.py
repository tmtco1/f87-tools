#!/usr/bin/env python3
"""Build the Bad Apple lighting effect: encode a video for the 87 keys and assemble it with the player.

The video is sampled per key (same layout as tools/live/stream_video.py), turned into on/off, and stored as
"which keys changed" per frame. It's cut off when the free flash (0xDC00-0xEBFF, 4 KB) is full, then
it loops. Output: effects/badapple/build/badapple.ihx, for patch_firmware.py --badapple.

usage: effects/badapple/build.py VIDEO [--fps 10] [--start SEC] [--tick-ms 1.0] [--color RRGGBB] ...
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "live"))
import stream_video as sv  # noqa: E402  (key layout and sampling)

AREA = (0xDC00, 0xEC00)
ROWS = 6
MAX_HOLD = 126                  # 0x80|127 would be the end marker 0xFF
SPEED_SCALE = (1.2, 1.1, 1.0, 0.9, 0.8)   # frame period per speed setting 0 (slow) .. 4 (fast)


def tool(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    sys.exit(f"{names[0]} not found (it comes with SDCC)")


def assemble(build, settings, data):
    asm = os.path.join(build, "badapple.asm")
    with open(asm, "w") as f:
        for k, v in settings.items():
            f.write(f"{k} = {v:#x}\n")
        f.write(open(os.path.join(HERE, "player.asm")).read())
        for i in range(0, len(data), 16):
            f.write("        .db " + ", ".join(f"{b:#04x}" for b in data[i:i + 16]) + "\n")
    rel, ihx = asm[:-4] + ".rel", asm[:-4] + ".ihx"
    subprocess.run([tool("sdas8051", "sdcc-sdas8051"), "-plosgff", asm], check=True)
    subprocess.run([tool("sdld", "sdcc-sdld"), "-n", "-i", ihx, rel], check=True)
    addrs = []
    for line in open(ihx):
        r = bytes.fromhex(line.strip()[1:])
        if r[3] == 0:
            a = r[1] << 8 | r[2]
            addrs += range(a, a + r[0])
    return ihx, min(addrs), max(addrs) + 1


def frames(a):
    W, H = sv.GRID_W, sv.GRID_H
    fit = {
        "stretch": f"scale={W}:{H}:flags=area",
        "crop": f"crop=iw:'min(ih,iw*{H}/{W})',scale={W}:{H}:flags=area",
        "pad": f"scale={W}:{H}:flags=area:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
    }[a.fit]
    cmd = ["ffmpeg", "-loglevel", "error"] + (["-ss", str(a.start)] if a.start else []) + \
          ["-i", a.video, "-vf", f"fps={a.fps},{fit},format=gray", "-f", "rawvideo", "-"]
    dec = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    regions = sv.key_regions()
    n = W * H
    try:
        while True:
            f = dec.stdout.read(n)
            if len(f) < n:
                break
            on = set()
            for (c, r), px in regions.items():
                v = sum(f[i] for i in px) // len(px)
                if (v >= a.threshold) != a.invert:
                    on.add(c * ROWS + r)
            yield on
    finally:
        dec.kill()
        dec.wait()


def encode(a, budget):
    """Returns the video bytes (with end marker) and, per stored frame, the keys that are on."""
    out = bytearray()
    shown = []
    prev, hold = set(), 0
    for on in frames(a):
        changed = sorted(on ^ prev)
        if not changed:
            if hold == MAX_HOLD:
                if len(out) + 1 > budget:
                    break
                out.append(0x80 | hold)
                hold = 0
            hold += 1
            shown.append(sorted(on))
            continue
        need = (1 if hold else 0) + 1 + len(changed)
        if len(out) + need > budget:
            break
        if hold:
            out.append(0x80 | hold)
            hold = 0
        out.append(len(changed))
        out += bytes(changed)
        shown.append(sorted(on))
        prev = on
    if hold:
        if len(out) + 1 <= budget:
            out.append(0x80 | hold)
        else:
            del shown[-hold:]
    out.append(0xFF)
    return bytes(out), shown


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="any video ffmpeg can read")
    ap.add_argument("--fps", type=float, default=10, help="frames per second stored (default 10)")
    ap.add_argument("--start", type=float, default=0, help="start at this many seconds into the video")
    ap.add_argument("--tick-ms", type=float, default=1.0,
                    help="length of a firmware timer tick in ms (default 1.0, not measured; see the docs)")
    ap.add_argument("--fit", choices=("stretch", "crop", "pad"), default="stretch")
    ap.add_argument("--threshold", type=int, default=128, help="grey level 0-255 from which a key is on")
    ap.add_argument("--invert", action="store_true", help="light the dark parts instead")
    ap.add_argument("--color", default="ffffff", help="key colour RRGGBB (default white)")
    a = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found")

    build = os.path.join(HERE, "build")
    os.makedirs(build, exist_ok=True)
    col = bytes.fromhex(a.color.lstrip("#"))
    ticks = 1000 / (a.fps * a.tick_ms)
    settings = {"COL_R": col[0], "COL_G": col[1], "COL_B": col[2]}
    for i, s in enumerate(SPEED_SCALE):
        p = round(ticks * s)
        if not 1 <= p <= 0xFFFF:
            sys.exit(f"frame period {p} ticks out of range; check --fps / --tick-ms")
        settings[f"FRAME_P{i}"] = p

    _, lo, end = assemble(build, settings, b"")         # player alone, to size the video budget
    if lo != AREA[0]:
        sys.exit(f"player must start at {AREA[0]:#06x}")
    data, shown = encode(a, AREA[1] - end - 1)          # -1: room for the end marker
    ihx, lo, end = assemble(build, settings, data)
    if end > AREA[1]:
        sys.exit(f"doesn't fit: ends at {end:#06x}")
    json.dump({"video": data.hex(), "frames": shown, "settings": settings},
              open(os.path.join(build, "badapple.json"), "w"))
    secs = len(shown) / a.fps
    print(f"built {os.path.relpath(ihx)}: player {AREA[0]:#06x}, {len(data)} bytes of video, "
          f"{len(shown)} frames = {secs:.1f} s at {a.fps:g} fps, ends {end - 1:#06x} ({AREA[1] - end} bytes left)")
    print(f"frame period {settings['FRAME_P2']} ticks at the middle speed (speed 0..4: "
          + ", ".join(str(settings[f'FRAME_P{i}']) for i in range(5)) + ")")


if __name__ == "__main__":
    main()
