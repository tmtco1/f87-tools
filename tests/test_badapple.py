#!/usr/bin/env python3
"""Check the built player in uCsim: run effect init + N frames and compare the key levels with what
build.py says the keyboard should show after frame N.

The renderer (0x63E5) is replaced by a stub that does what matters here: decrement every lit level.
usage: tests/test_badapple.py [N ...]      (default: a spread of frames, including the loop back to the start)
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "..", "effects", "badapple", "build")
UCSIM = shutil.which("ucsim_51") or shutil.which("sdcc-ucsim_51") or shutil.which("s51")
if not UCSIM:
    sys.exit("uCsim not found (it comes with SDCC)")
build = json.load(open(os.path.join(BUILD, "badapple.json")))
frames = build["frames"]
period = build["settings"]["FRAME_P2"]
PALADDR, CFGADDR, CFGVAL, PAL = 0xC800 + 21 * 6, 0x0309 + 0x3B + 2 * 5, 0x21, (0x65, 0x43, 0x21)
IHX = os.path.join(BUILD, "badapple.ihx")

# decrement every non-zero level at 0x0017..0x007C, like the real renderer
RENDER_STUB = [0x90, 0x00, 0x17, 0x7F, 102, 0xE0, 0x60, 0x02, 0x14, 0xF0, 0xA3, 0xDF, 0xF8, 0x22]


def run(n):
    lo, hi = n & 0xFF, (n >> 8) + (1 if n & 0xFF else 0)
    stub = [0x75, 0x81, 0x60,                       # MOV SP,#0x60
            0x90, 0x0E, 0xC7, 0x74, 6, 0xF0,        # mode = 6
            0x90, 0x0D, 0x94, 0x74, 2, 0xF0,        # speed = 2 (middle)
            0xD2, 0x21,                             # SETB 0x21: mode just changed
            0x12, 0xDC, 0x00]                       # LCALL ba_init
    if n:
        stub += [0x78, lo, 0x79, hi]                # R0/R1 = frame count
        loop = len(stub)
        stub += [0x90, 0x03, 0x00, 0x74, period >> 8, 0xF0, 0xA3, 0x74, period & 0xFF, 0xF0,  # ticks = period
                 0x12, 0xDC, 0x03]                  # LCALL ba_frame
        stub += [0xD8, (loop - len(stub) - 2) & 0xFF]
        stub += [0xD9, (loop - len(stub) - 2) & 0xFF]
    done = len(stub)
    stub += [0x80, 0xFE]
    cmds = [f'file "{IHX}"', "fill xram 0 0xffff 0",
            "set memory rom 0 " + " ".join(f"{b:#04x}" for b in stub),
            "set memory rom 0x63e5 " + " ".join(f"{b:#04x}" for b in RENDER_STUB),
            "set memory rom 0x1b0e 0x22",           # init switch continues: RET here
            f"set memory rom {PALADDR:#x} 0x12 0x34 0x56 0x65 0x43 0x21",   # palette slots 0, 1 of this effect
            f"set memory xram {CFGADDR:#x} {CFGVAL:#x}",              # config byte: speed 2, colour slot 1
            f"break {done:#x}", "pc 0", "run", "dump bit 0x21 0x22", "dump xram 0x0000 0x0fff 16"]
    out = subprocess.run([UCSIM], input="\n".join(cmds) + "\nkill\n",
                         capture_output=True, text=True, timeout=600).stdout
    mem = {}
    out_xram = out[out.rfind("dump xram"):] if "dump xram" in out else out
    for line in out_xram.splitlines():
        m = re.match(r"\s*0x([0-9a-f]{4})\s+((?:[0-9a-f]{2} )+)", line)
        if m:
            base = int(m.group(1), 16)
            for i, b in enumerate(m.group(2).split()):
                if base + i < 0x1000:
                    mem[base + i] = int(b, 16)
    if f"{done:04x}" not in out.lower() and "breakpoint" not in out.lower():
        print(out[-2000:])
    return mem, out


def main():
    total = len(frames)
    ns = [int(x) for x in sys.argv[1:]] or [0, 1, 2, 3, 10, 50, total // 2, total - 1, total, total + 1, total + 2]
    ok = True
    for n in ns:
        mem, out = run(n)
        lit = sorted(i for i in range(102) if mem.get(0x17 + i, 0))
        levels = {mem.get(0x17 + i, 0) for i in lit}
        # frame n of the loop (after the last frame the player starts over from black)
        k = n % (total + 1)
        want = [] if k == 0 else frames[k - 1]
        colours_ok = all(mem.get(0x0424 + i, 0) == PAL[i % 3]
                         for i in range(306))
        stray = sorted(hex(a) for a, v in mem.items() if v and not (
            0x17 <= a < 0x17 + 102 or 0x0424 <= a < 0x0424 + 306 or 0x0EC1 <= a <= 0x0EC3
            or a in (0x0300, 0x0301, 0x0D94, 0x0EC7, CFGADDR)))
        good = lit == want and colours_ok and not stray and levels <= {31}
        ok &= good
        print(f"frame {n:4d}: {len(lit):2d} keys lit (expected {len(want):2d}), levels {sorted(levels)}"
              f"{'' if colours_ok else ', COLOURS WRONG'}{', STRAY ' + str(stray) if stray else ''}"
              f"  {'ok' if good else 'MISMATCH'}")
    print("all ok" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
