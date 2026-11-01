#!/usr/bin/env python3
"""Check the built Game of Life effect in uCsim against a Python model of the same rules.

Runs effect init + N generations in the 8051 simulator (renderer 0x63E5 replaced by a stub that decrements
lit levels, like the real one) and compares the live cells, generation counter and random state.
usage: tests/test_life.py [N ...] [--seed BYTE]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "..", "effects", "life", "build")
sys.path.insert(0, os.path.join(HERE, "..", "tools", "live"))
import stream_video as sv  # noqa: E402

UCSIM = shutil.which("ucsim_51") or shutil.which("sdcc-ucsim_51") or shutil.which("s51")
if not UCSIM:
    sys.exit("uCsim not found (it comes with SDCC)")
IHX = os.path.join(BUILD, "life.ihx")
S = {m.group(1): int(m.group(2), 16) for m in
     re.finditer(r"^(\w+) = (0x[0-9a-f]+)$", open(os.path.join(BUILD, "life.asm")).read(), re.M)}
BASE = 0xEE40
PALADDR, CFGADDR, CFGVAL, PAL = 0xC800 + 21 * 9, 0x0309 + 0x3B + 2 * 8, 0x21, (0x65, 0x43, 0x21)
RENDER_STUB = [0x90, 0x00, 0x17, 0x7F, 102, 0xE0, 0x60, 0x02, 0x14, 0xF0, 0xA3, 0xDF, 0xF8, 0x22]


# ---- reference model ----
def led(pc, r):
    if r == 4 and 1 <= pc <= 12:
        return 12 if pc == 1 else pc - 1
    return pc


class Model:
    def __init__(self, tick):
        self.rng = [0xAC, tick | 1]
        self.alive = [False] * 102
        self.seed()

    def seed(self):
        self.gen = 0
        hi, lo = self.rng
        for i in range(102):
            carry = lo & 1
            lo = (lo >> 1) | ((hi & 1) << 7)
            hi >>= 1
            if carry:
                hi ^= 0xB4
            self.alive[i] = lo < S["DENSITY"]
        self.rng = [hi, lo]

    def step(self):
        new = [False] * 102
        for pc in range(17):
            for r in range(6):
                if (pc, r) not in sv.KEYS:
                    continue
                total = sum(self.alive[led(c, rr) * 6 + rr] for c in (pc - 1, pc, pc + 1) for rr in (r - 1, r, r + 1)
                            if 0 <= c < 17 and 0 <= rr < 6 and (c, rr) in sv.KEYS)
                me = led(pc, r) * 6 + r
                new[me] = total == 3 or (total == 4 and self.alive[me])
        changed = new != self.alive
        self.alive = new
        self.gen += 1
        if self.gen == S["GEN_MAX"]:
            self.seed()
        elif not changed and self.gen < S["GEN_MAX"] - S["STILL"]:
            self.gen = S["GEN_MAX"] - S["STILL"]


# ---- simulator ----
def run(n, tick):
    period = S["FRAME_P2"]
    lo, hi = n & 0xFF, (n >> 8) + (1 if n & 0xFF else 0)
    stub = [0x75, 0x81, 0x60,
            0x90, 0x0E, 0xC7, 0x74, 9, 0xF0,           # mode = 9
            0x90, 0x0D, 0x94, 0x74, 2, 0xF0,           # speed = 2
            0x90, 0x03, 0x01, 0x74, tick, 0xF0,        # tick counter low byte = random seed
            0xD2, 0x21,                                # mode just changed
            0x12, BASE >> 8, BASE & 0xFF]              # init
    if n:
        stub += [0x75, 0x30, lo, 0x75, 0x31, hi]   # loop counter in IRAM 0x30/0x31 (the effect uses R0-R7)
        loop = len(stub)
        stub += [0x90, 0x03, 0x00, 0x74, period >> 8, 0xF0, 0xA3, 0x74, period & 0xFF, 0xF0,
                 0x12, (BASE + 3) >> 8, (BASE + 3) & 0xFF]
        stub += [0xD5, 0x30, (loop - len(stub) - 3) & 0xFF]
        stub += [0xD5, 0x31, (loop - len(stub) - 3) & 0xFF]
    done = len(stub)
    stub += [0x80, 0xFE]
    cmds = [f'file "{IHX}"', "fill xram 0 0xffff 0",
            "set memory rom 0 " + " ".join(f"{b:#04x}" for b in stub),
            "set memory rom 0x63e5 " + " ".join(f"{b:#04x}" for b in RENDER_STUB),
            "set memory rom 0x1b0e 0x22",
            f"set memory rom {PALADDR:#x} 0x12 0x34 0x56 0x65 0x43 0x21",
            f"set memory xram {CFGADDR:#x} {CFGVAL:#x}",
            f"break {done:#x}", "pc 0", "run", "dump xram 0x0000 0x0fff 16"]
    out = subprocess.run([UCSIM], input="\n".join(cmds) + "\nkill\n",
                         capture_output=True, text=True, timeout=600).stdout
    out = out[out.rfind("dump xram"):]
    mem = {}
    for line in out.splitlines():
        m = re.match(r"\s*0x([0-9a-f]{4})\s+((?:[0-9a-f]{2} )+)", line)
        if m:
            base = int(m.group(1), 16)
            for i, b in enumerate(m.group(2).split()):
                if base + i < 0x1000:
                    mem[base + i] = int(b, 16)
    return mem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gens", nargs="*", type=int)
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0x5A)
    a = ap.parse_args()
    gens = a.gens or [0, 1, 2, 3, 5, 10, 20, 50, 100, S["GEN_MAX"] - 1, S["GEN_MAX"], S["GEN_MAX"] + 1, 450]
    ok = True
    for n in gens:
        m = Model(a.seed)
        for _ in range(n):
            m.step()
        mem = run(n, a.seed)
        sim = [bool(mem.get(0x17 + i, 0)) for i in range(102)]
        state = (mem.get(0x0EC1), mem.get(0x0EC2), mem.get(0x0EC3))
        want = (m.gen, *m.rng)
        stray = sorted(hex(x) for x, v in mem.items() if v and not (
            0x17 <= x < 0x17 + 102 or 0x0424 <= x < 0x0424 + 306 or 0x0EC1 <= x <= 0x0EC3
            or x in (0x0300, 0x0301, 0x0D94, 0x0EC7, CFGADDR)))
        colours_ok = all(mem.get(0x0424 + i, 0) == PAL[i % 3] for i in range(306))
        keys_only = all(not sim[led(pc, r) * 6 + r] for pc in range(17) for r in range(6)
                        if (pc, r) not in sv.KEYS and led(pc, r) * 6 + r not in
                        {led(c, rr) * 6 + rr for c, rr in sv.KEYS}) or state[0] == 0  # a fresh board fills every slot
        good = sim == m.alive and state == want and not stray and keys_only and colours_ok
        ok &= good
        print(f"gen {n:3d}: {sum(sim):2d} alive (model {sum(m.alive):2d}), gen counter {state[0]} "
              f"(model {want[0]}){', STRAY ' + str(stray) if stray else ''}  {'ok' if good else 'MISMATCH'}")
    print("all ok" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
