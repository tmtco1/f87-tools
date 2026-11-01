#!/usr/bin/env python3
"""Change the USB and Bluetooth names in the AULA F87 base firmware (base_f87_decrypted.bin).

USB: the GET_DESCRIPTOR handler (0x3FEB) loads each string's address and length as immediates.
     New string descriptors are written to unused flash at 0xEE00 and those immediates are retargeted.
BT:  0xA063 copies a 13-byte name into the packet sent to the radio module. The name is patched in place
     and both length immediates are set to the new length (the rest of the packet is zero-filled by the
     original code).

Custom lighting effects: --badapple (effect 6, a video stored in flash), --life (effect 9, Game of Life),
or --effect IHX for your own; see docs/CUSTOM_EFFECTS.md.

Boot animation (power-on snake, lighting mode 0x26): can be disabled, or its snake-step and fade
periods (in timer ticks) changed.

usage: patch_firmware.py IN.bin OUT.bin [--manufacturer S] [--product S] [--bt-name S] [--bt3-name S] [--bt5-name S]
                                     [--no-boot-anim] [--boot-step N] [--boot-fade N]
"""
import argparse
import hashlib
import os
import sys

BASE_SHA256 = None  # filled from the known image below
KNOWN_MD5 = "acc16504615d3808d646915ddb95856e"  # base_f87_decrypted.bin

STR_AREA = 0xEE00          # free flash, unreferenced by the firmware, below the relocated reset vector at 0xEFFB
STR_AREA_END = 0xEF00

# (hi_imm, lo_imm, len_imm, expected original address, expected original length)
USB_SITES = {
    "manufacturer": [(0x40D2, 0x40D6, 0x40DF, 0x5B14, 0x11),   # string index 1
                     (0x41A4, 0x41A8, 0x41B1, 0x5B2F, 0x11)],  # string index 0xFF, same text
    "product":      [(0x411A, 0x411E, 0x4127, 0x5CD6, 0x20)],  # string index 2
}
# slot -> (name address, packet length immediate, loop bound immediate)
BT_SITES = {
    "bt3": (0xAD9B, 0xA072, 0xA090),   # a063(1): "AULA-F87 3.0 "
    "bt5": (0xADA8, 0xA09A, 0xA0B7),   # a063(0): "AULA-F87 5.0 "
}
BT_MAX = 13

# Boot animation (lighting mode 0x26, frame handler 0x1D0B)
BOOT_FLAG_SET = 0x8C22     # main(): SETB 0x33 ("booting") -> CLR 0x33 skips the boot animation entirely
BOOT_FADE_IMM = 0x1D11     # SUBB A,#5 : fade all lit keys one step every N ticks (bigger = longer trail)
BOOT_STEP_IMM = 0x1D25     # SUBB A,#1 : advance the snake one key every N ticks (bigger = slower)
BOOT_STEP_CALL = 0x1D52    # LCALL 0x8B26 (snake step) -> LCALL <custom animation entry>
CODE_AREA = (0xEC80, 0xEE00)   # 384 free bytes in the sector holding the firmware's own code (0xEC00-0xEC64)

# Custom lighting effects (docs/CUSTOM_EFFECTS.md): blobs with a 10-byte header
#   +0 LJMP init, +3 LJMP frame, +6 LJMP next (0x1B0E, patched to chain), +9 mode
# installed into the effect slots the stock firmware leaves empty.
EFFECT_AREAS = [(0xDC00, 0xEC00), (0xEE00, 0xEFFB)]   # free flash; the second one shares 0xEE00 with the USB strings
EFFECT_INIT = 0x179C        # default target of the effect-init switch (0x175B, ?C?CCASE table): 0x1B0E
EFFECT_INIT_NEXT = 0x1B0E
FRAME_TABLE = 0x1B37        # LJMP per mode 0..0x11; empty slots hold LJMP 0x1DC8 (a RET)
EFFECT_SLOTS = {6: 0x4F78, 9: 0x4F82, 14: 0x4F8C}   # mode -> Fn "next effect" skip (CJNE A,#mode)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # repo root (tools/ is one below)
EFFECT_PRESETS = {"badapple": "effects/badapple/build/badapple.ihx", "life": "effects/life/build/life.ihx"}

# Custom boot animations: anim/<file>.c built with effects/anim/build.sh, plus their recommended timing
BOOT_ANIMS = {
    "fkeys": {"ihx": "effects/anim/build/boot_fkeys.ihx", "step": 8, "fade": 1,
              "about": "full-white light sweeping F1..F12"},
    "wipe": {"ihx": "effects/anim/build/wipe.ihx", "step": 6, "fade": 2,
             "about": "white wipe across the whole keyboard, column by column"},
    "rainbow_frow": {"ihx": "effects/anim/build/rainbow_frow.ihx", "step": 8, "fade": 1,
                     "about": "F1..F12 one by one, a different colour per key"},
    "tmtco": {"ihx": "effects/anim/build/tmtco.ihx", "step": 4, "fade": 2,
              "about": "T, M, T, C, O light up in turn, then a ripple spreads out from O"},
}


def load_ihx(path):
    data = {}
    for line in open(path):
        line = line.strip()
        if not line.startswith(":"):
            continue
        rec = bytes.fromhex(line[1:])
        n, addr, typ = rec[0], rec[1] << 8 | rec[2], rec[3]
        if (sum(rec) & 0xFF) != 0:
            sys.exit(f"{path}: bad checksum")
        if typ == 0:
            for i in range(n):
                data[addr + i] = rec[4 + i]
        elif typ == 1:
            break
        else:
            sys.exit(f"{path}: unsupported record type {typ}")
    return data


def usb_string_descriptor(s):
    raw = s.encode("utf-16le")
    if len(raw) + 2 > 254:
        sys.exit(f"USB string too long: {s!r}")
    return bytes([len(raw) + 2, 0x03]) + raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--manufacturer")
    ap.add_argument("--product")
    ap.add_argument("--bt-name", help="sets both Bluetooth names")
    ap.add_argument("--bt3-name")
    ap.add_argument("--bt5-name")
    ap.add_argument("--no-boot-anim", action="store_true", help="skip the power-on snake animation")
    ap.add_argument("--boot-step", type=int, metavar="N",
                    help="ticks between snake steps, 1-255 (original 1; bigger = slower)")
    ap.add_argument("--boot-fade", type=int, metavar="N",
                    help="ticks between fade steps, 1-255 (original 5; bigger = longer trail)")
    ap.add_argument("--boot-anim", choices=sorted(BOOT_ANIMS),
                    help="replace the snake with a custom animation: "
                         + "; ".join(f"{k} = {v['about']}" for k, v in BOOT_ANIMS.items()))
    ap.add_argument("--boot-code", metavar="IHX",
                    help="replace the snake step with your own code (Intel HEX built by effects/anim/build.sh, entry 0xEC80)")
    ap.add_argument("--effect", action="append", default=[], metavar="IHX",
                    help="add a custom lighting effect (repeatable), see docs/CUSTOM_EFFECTS.md")
    ap.add_argument("--badapple", action="store_true",
                    help=f"add the Bad Apple effect (6): --effect {EFFECT_PRESETS['badapple']}")
    ap.add_argument("--life", action="store_true",
                    help=f"add the Game of Life effect (9): --effect {EFFECT_PRESETS['life']}")
    ap.add_argument("--force", action="store_true", help="skip the input image hash check")
    a = ap.parse_args()

    orig = open(a.inp, "rb").read()
    fw = bytearray(orig)
    if hashlib.md5(fw).hexdigest() != KNOWN_MD5 and not a.force:
        sys.exit("input is not the known base_f87_decrypted.bin (use --force to try anyway)")
    if len(fw) != 61440:
        sys.exit("expected a 61440-byte image")

    # verify the code still looks like what we analysed
    for sites in USB_SITES.values():
        for hi, lo, ln, addr, olen in sites:
            assert fw[hi - 1] == 0x74 and fw[lo - 1] == 0x74 and fw[ln - 1] == 0x74, "unexpected opcode"
            assert (fw[hi] << 8 | fw[lo]) == addr and fw[ln] == olen, "unexpected operand"
    for addr, plen, bound in BT_SITES.values():
        assert fw[plen - 1] == 0x76 and fw[plen] == 0x0D, "unexpected BT length opcode"
        assert fw[bound - 1] == 0xB4 and fw[bound] == 0x0D, "unexpected BT loop opcode"
        assert fw[addr:addr + 4] == b"AULA", "unexpected BT name"
    assert fw[BOOT_STEP_CALL:BOOT_STEP_CALL + 3] == b"\x12\x8b\x26", "unexpected boot step call"
    assert fw[BOOT_FLAG_SET:BOOT_FLAG_SET + 2] == b"\xd2\x33", "unexpected boot flag instruction"
    assert fw[BOOT_FADE_IMM - 1:BOOT_FADE_IMM + 1] == b"\x94\x05", "unexpected boot fade instruction"
    assert fw[BOOT_STEP_IMM - 1:BOOT_STEP_IMM + 1] == b"\x94\x01", "unexpected boot step instruction"
    assert fw[EFFECT_INIT:EFFECT_INIT + 2] == bytes([EFFECT_INIT_NEXT >> 8, EFFECT_INIT_NEXT & 0xFF]), \
        "unexpected effect-init default"
    for mode, skip in EFFECT_SLOTS.items():
        entry = FRAME_TABLE + 3 * mode
        assert fw[entry:entry + 3] == b"\x02\x1d\xc8", f"unexpected frame entry for mode {mode}"
        assert fw[skip:skip + 2] == bytes([0xB4, mode]), f"unexpected Fn skip for mode {mode}"
    if any(fw[STR_AREA:STR_AREA_END]) or fw[0xEFFB:0xEFFE] != b"\0\0\0":
        sys.exit("string area / reset-vector slot not empty")

    # custom lighting effects: load and check them first (the USB strings must stay below them)
    paths = list(a.effect) + [os.path.join(ROOT, EFFECT_PRESETS[k]) for k in EFFECT_PRESETS if getattr(a, k)]
    effects = []
    for path in paths:
        if not os.path.exists(path):
            build = {"badapple": "effects/badapple/build.py VIDEO", "life": "effects/life/build.py"}
            hint = next((build[k] for k, v in EFFECT_PRESETS.items() if path.endswith(v)), "its build script")
            sys.exit(f"{os.path.relpath(path)} not found: run {hint} first")
        code = load_ihx(path)
        lo, hi = min(code), max(code)
        if not any(s <= lo and hi < e for s, e in EFFECT_AREAS):
            sys.exit(f"{path}: must lie in one of " + ", ".join(f"{s:#06x}-{e - 1:#06x}" for s, e in EFFECT_AREAS)
                     + f" (got {lo:#06x}-{hi:#06x})")
        hdr = [code.get(lo + i) for i in range(10)]
        if hdr[0] != 0x02 or hdr[3] != 0x02 or hdr[6] != 0x02 or (hdr[7] << 8 | hdr[8]) != EFFECT_INIT_NEXT:
            sys.exit(f"{path}: doesn't start with the effect header (LJMP init, LJMP frame, LJMP 0x1B0E, mode)")
        mode = hdr[9]
        if mode not in EFFECT_SLOTS:
            sys.exit(f"{path}: effect slot {mode} isn't free (free slots: {sorted(EFFECT_SLOTS)})")
        if any(mode == m for _, _, m, _ in effects):
            sys.exit(f"two effects for slot {mode}")
        for other_lo, other_hi, _, other in effects:
            if lo <= other_hi and other_lo <= hi:
                sys.exit(f"{path} overlaps {other}")
        if any(fw[lo:hi + 1]):
            sys.exit(f"{path}: flash at {lo:#06x}-{hi:#06x} not empty")
        effects.append((lo, hi, mode, path))
    str_end = min([STR_AREA_END] + [lo for lo, _, _, _ in effects if lo >= STR_AREA])

    # USB strings
    cursor = STR_AREA
    for key, text in (("manufacturer", a.manufacturer), ("product", a.product)):
        if text is None:
            continue
        desc = usb_string_descriptor(text)
        if cursor + len(desc) > str_end:
            sys.exit(f"USB strings don't fit in the string area ({str_end - STR_AREA} bytes"
                     + (", the rest holds a custom effect)" if str_end < STR_AREA_END else ")"))
        fw[cursor:cursor + len(desc)] = desc
        for hi, lo, ln, _, _ in USB_SITES[key]:
            fw[hi], fw[lo], fw[ln] = cursor >> 8, cursor & 0xFF, len(desc)
        print(f"USB {key:12s} -> {text!r} at {cursor:#06x} ({len(desc)} bytes)")
        cursor += len(desc)
        cursor += cursor & 1

    # Bluetooth names
    for key in ("bt3", "bt5"):
        text = getattr(a, f"{key}_name") or a.bt_name
        if text is None:
            continue
        raw = text.encode("ascii")
        if not 1 <= len(raw) <= BT_MAX:
            sys.exit(f"Bluetooth name must be 1..{BT_MAX} ASCII characters: {text!r}")
        addr, plen, bound = BT_SITES[key]
        fw[addr:addr + BT_MAX] = raw.ljust(BT_MAX, b"\0")
        fw[plen] = fw[bound] = len(raw)
        print(f"BT  {key:12s} -> {text!r}")

    # Boot animation
    if a.boot_anim and a.boot_code:
        sys.exit("use either --boot-anim or --boot-code")
    code_path = a.boot_code
    if a.boot_anim:
        preset = BOOT_ANIMS[a.boot_anim]
        code_path = os.path.join(ROOT, preset["ihx"])
        if not os.path.exists(code_path):
            src = os.path.basename(preset["ihx"])[:-4]
            sys.exit(f"{preset['ihx']} not built yet: run effects/anim/build.sh {src} first")
        if a.boot_step is None:
            a.boot_step = preset["step"]
        if a.boot_fade is None:
            a.boot_fade = preset["fade"]
    if code_path:
        if a.no_boot_anim:
            sys.exit("--no-boot-anim can't be combined with a custom animation")
        code = load_ihx(code_path)
        lo, hi = min(code), max(code)
        if lo != CODE_AREA[0] or hi >= CODE_AREA[1]:
            sys.exit(f"animation code must start at {CODE_AREA[0]:#06x} and end before {CODE_AREA[1]:#06x} "
                     f"(got {lo:#06x}-{hi:#06x})")
        if any(fw[CODE_AREA[0]:CODE_AREA[1]]):
            sys.exit("code area not empty")
        for addr, b in code.items():
            fw[addr] = b
        fw[BOOT_STEP_CALL + 1], fw[BOOT_STEP_CALL + 2] = lo >> 8, lo & 0xFF
        print(f"boot animation -> {os.path.relpath(code_path)} ({len(code)} bytes at {lo:#06x}), "
              f"called from {BOOT_STEP_CALL:#06x}")
    if a.no_boot_anim:
        if a.boot_step is not None or a.boot_fade is not None:
            print("note: --boot-step/--boot-fade have no effect with --no-boot-anim")
        fw[BOOT_FLAG_SET] = 0xC2   # CLR 0x33
        print("boot animation -> disabled")
    for name, val, addr in (("step", a.boot_step, BOOT_STEP_IMM), ("fade", a.boot_fade, BOOT_FADE_IMM)):
        if val is None:
            continue
        if not 1 <= val <= 255:
            sys.exit(f"--boot-{name} must be 1..255")
        fw[addr] = val
        print(f"boot animation {name} period -> {val} ticks (was {orig[addr]})")

    # install the custom effects, each one's init chained to the next one's
    for i, (lo, hi, mode, path) in enumerate(effects):
        code = load_ihx(path)
        for addr, b in code.items():
            fw[addr] = b
        if i + 1 < len(effects):
            nxt = effects[i + 1][0]
            fw[lo + 7], fw[lo + 8] = nxt >> 8, nxt & 0xFF
        entry = FRAME_TABLE + 3 * mode
        fw[entry + 1], fw[entry + 2] = (lo + 3) >> 8, (lo + 3) & 0xFF
        fw[EFFECT_SLOTS[mode] + 1] = 0xFF
        print(f"effect {mode:2d}      -> {os.path.relpath(path)} ({len(code)} bytes at {lo:#06x}-{hi:#06x})")
    if effects:
        fw[EFFECT_INIT], fw[EFFECT_INIT + 1] = effects[0][0] >> 8, effects[0][0] & 0xFF

    if fw == bytearray(orig):
        sys.exit("nothing to change (give at least one option)")
    open(a.out, "wb").write(fw)
    diff = [i for i in range(len(fw)) if fw[i] != orig[i]]
    print(f"wrote {a.out}: {len(diff)} bytes changed, all in "
          f"{sorted({f'{i & ~0xff:#06x}' for i in diff})}")


if __name__ == "__main__":
    main()
