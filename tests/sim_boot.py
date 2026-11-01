#!/usr/bin/env python3
"""Simulate a boot animation blob in uCsim the way the firmware drives it, and show the LED
buffers after each frame.

For frame count N it runs: clear XRAM, set up the boot state (what 0xB1B3 does), then N x LCALL 0xEC80.
usage: sim_boot.py effects/anim/build/boot_fkeys.ihx [frames] [--firmware base_f87_decrypted.bin]
"""
import re
import shutil
import subprocess
import sys

UCSIM = shutil.which("ucsim_51") or shutil.which("sdcc-ucsim_51") or shutil.which("s51")
if not UCSIM:
    sys.exit("uCsim not found (it comes with SDCC as ucsim_51 / sdcc-ucsim_51 / s51)")

import argparse
import os
import tempfile

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("ihx", help="animation built by effects/anim/build.sh")
ap.add_argument("frames", nargs="?", type=int, default=40)
ap.add_argument("--firmware", metavar="BIN",
                help="load this firmware image (e.g. base_f87_decrypted.bin) underneath, so reads of "
                     "firmware tables (key maps at 0x2B5F, colour wheel at 0x279C...) return real data")
args = ap.parse_args()
ihx, frames = args.ihx, args.frames

fw_ihx = None
if args.firmware:
    data = open(args.firmware, "rb").read()[:0xEC80]
    fd, fw_ihx = tempfile.mkstemp(suffix=".ihx")
    import atexit
    atexit.register(os.remove, fw_ihx)
    with os.fdopen(fd, "w") as f:
        for a in range(0, len(data), 32):
            chunk = data[a:a + 32]
            rec = bytes([len(chunk), a >> 8, a & 0xFF, 0]) + chunk
            f.write(":" + (rec + bytes([(-sum(rec)) & 0xFF])).hex().upper() + "\n")
        f.write(":00000001FF\n")
# LED grid (col, row) -> key name for the AULA F87 (ANSI, checked against a photo of the board).
# Rows 0-3 and 5 match the keymap; row 4 is in LED order (Z sits at LED column 12, see docs).
# The whole mapping is verified on the keyboard with tools/live/stream_video.py --test.
GRID = [
    "Esc  -    F1   F2   F3   F4   F5   F6   F7   F8   F9   F10  F11  F12  PrtS ScrL Paus",
    "`    1    2    3    4    5    6    7    8    9    0    -    =    Bksp Ins  Home PgUp",
    "Tab  Q    W    E    R    T    Y    U    I    O    P    [    ]    \\    Del  End  PgDn",
    "Caps A    S    D    F    G    H    J    K    L    ;    '    -    Ent  -    -    -",
    "LSft X    C    V    B    N    M    ,    .    /    -    -    Z    RSft -    Up   -",
    "LCtl Win  LAlt -    -    Spc  -    -    RAlt Fn   Code -    -    RCtl Lt   Dn   Rt",
]
NAMES = [row.split() for row in GRID]


def key(c, r):
    n = NAMES[r][c]
    return n if n != "-" else f"({c},{r})"


def simulate(n):
    stub = []
    for _ in range(n):
        stub += [0x12, 0xEC, 0x80]                     # LCALL 0xEC80
    stub += [0x80, 0xFE]                               # SJMP $
    cmds = ([f'file "{fw_ihx}"'] if fw_ihx else []) + [f'file "{ihx}"', "fill xram 0 0x0fff 0",
            "set memory rom 0 " + " ".join(f"{b:#04x}" for b in stub),
            "set memory xram 0x0ec1 0 0 0xff 0xff",    # row=0 col=0 dir=right running
            f"break {len(stub) - 2:#x}", "pc 0", "run",
            "dump xram 0x0ec0 0x0ecf 16", "dump xram 0x0000 0x0fff 16"]
    out = subprocess.run([UCSIM], input="\n".join(cmds) + "\nkill\n",
                         capture_output=True, text=True, timeout=60).stdout
    mem = {}
    for line in out.splitlines():
        m = re.match(r"\s*0x([0-9a-f]{4})\s+((?:[0-9a-f]{2} )+)", line)
        if m:
            base = int(m.group(1), 16)
            for i, b in enumerate(m.group(2).split()):
                mem[base + i] = int(b, 16)
    return mem


for n in range(frames + 1):
    m = simulate(n)
    level = {(c, r): m.get(0x0017 + c * 6 + r, 0) for c in range(17) for r in range(6)}
    colour = {(c, r): tuple(m.get(0x0424 + c * 18 + r * 3 + i, 0) for i in range(3)) for c in range(17) for r in range(6)}
    lit = [(c, r) for (c, r), v in level.items() if v]
    touched = [hex(a) for a, v in m.items() if v and not (0x0017 <= a < 0x0017 + 102 or 0x0424 <= a < 0x0424 + 306
                                                           or 0x0EC1 <= a <= 0x0EC4)]
    desc = ", ".join(key(c, r) + ("" if colour[(c, r)] == (255, 255, 255) else f"(rgb {colour[(c, r)]})")
                     for c, r in sorted(lit, key=lambda k: (k[1], k[0])))
    print(f"after {n:2d} frames: POS={m.get(0x0EC2):2d} RUN={m.get(0x0EC4):#04x}  lit: {desc or '-'}"
          + (f"  STRAY WRITES {touched}" if touched else ""))
