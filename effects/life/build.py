#!/usr/bin/env python3
"""Build the Game of Life lighting effect (effect 9) -> effects/life/build/life.ihx, for patch_firmware.py --life.

usage: effects/life/build.py [--gen-ms 250] [--density 38] [--color RRGGBB] [--max-gens 200] [--tick-ms 1.0]
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "live"))
import stream_video as sv  # noqa: E402  (physical key positions)

AREA = (0xEE40, 0xEFFB)         # below the bootloader's jump slot at 0xEFFB
SPEED_SCALE = (2.0, 1.5, 1.0, 0.7, 0.5)   # generation period per speed setting 0 (slow) .. 4 (fast)


def tool(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    sys.exit(f"{names[0]} not found (it comes with SDCC)")


def key_mask():
    """13 bytes, bit (col*6 + row) set where the keyboard has a key at physical matrix position (col, row)."""
    mask = bytearray(13)
    for col, row in sv.KEYS:
        i = col * 6 + row
        mask[i >> 3] |= 1 << (i & 7)
    return bytes(mask)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gen-ms", type=float, default=250, help="ms per generation at the middle speed (default 250)")
    ap.add_argument("--density", type=int, default=38, help="%% of keys alive in a new random board (default 38)")
    ap.add_argument("--max-gens", type=int, default=200, help="new board after this many generations (default 200)")
    ap.add_argument("--still", type=int, default=8,
                    help="generations to keep showing a board that stopped changing (default 8)")
    ap.add_argument("--color", default="ffffff", help="cell colour RRGGBB (default white)")
    ap.add_argument("--tick-ms", type=float, default=1.0, help="firmware timer tick in ms (see docs/BADAPPLE.md)")
    a = ap.parse_args()
    if not 1 <= a.still < a.max_gens <= 255:
        sys.exit("need 1 <= --still < --max-gens <= 255")

    col = bytes.fromhex(a.color.lstrip("#"))
    settings = {"COL_R": col[0], "COL_G": col[1], "COL_B": col[2], "DENSITY": round(a.density * 256 / 100),
                "GEN_MAX": a.max_gens, "STILL": a.still}
    if not 1 <= settings["DENSITY"] <= 255:
        sys.exit("--density must be 1..99")
    for i, s in enumerate(SPEED_SCALE):
        p = round(a.gen_ms / a.tick_ms * s)
        if not 1 <= p <= 0xFFFF:
            sys.exit(f"generation period {p} ticks out of range")
        settings[f"FRAME_P{i}"] = p

    build = os.path.join(HERE, "build")
    os.makedirs(build, exist_ok=True)
    asm = os.path.join(build, "life.asm")
    with open(asm, "w") as f:
        for k, v in settings.items():
            f.write(f"{k} = {v:#x}\n")
        f.write(open(os.path.join(HERE, "life.asm")).read())
        f.write("        .db " + ", ".join(f"{b:#04x}" for b in key_mask()) + "\n")
    subprocess.run([tool("sdas8051", "sdcc-sdas8051"), "-plosgff", asm], check=True)
    ihx = asm[:-4] + ".ihx"
    subprocess.run([tool("sdld", "sdcc-sdld"), "-n", "-i", ihx, asm[:-4] + ".rel"], check=True)
    addrs = []
    for line in open(ihx):
        r = bytes.fromhex(line.strip()[1:])
        if r[3] == 0:
            addrs += range(r[1] << 8 | r[2], (r[1] << 8 | r[2]) + r[0])
    lo, end = min(addrs), max(addrs) + 1
    if lo != AREA[0] or end > AREA[1]:
        sys.exit(f"error: must lie in {AREA[0]:#06x}-{AREA[1] - 1:#06x}, got {lo:#06x}-{end - 1:#06x}")
    print(f"built {os.path.relpath(ihx)}: {end - lo} bytes at {lo:#06x}-{end - 1:#06x} ({AREA[1] - end} bytes left), "
          f"{a.gen_ms:g} ms per generation at the middle speed")


if __name__ == "__main__":
    main()
