#!/usr/bin/env python3
"""AULA F87 / F87 PRO (USB 258a:010c) RGB control for Linux via hidraw.

Protocol reimplemented from the vendor's OemDrv.exe (class CDevG5KB):

  Every transfer is a 520-byte HID *feature* report on interface 1:
    [0] report id   0x06 (firmware 24; older firmware used 0x09)
    [1] command     write = 0x0N, read = 0x8N
    [2] argument    layer / colour-group index, else 0
    [3] 0
    [4] packet count  (payload split into 512-byte chunks)
    [5] packet index
    [6..7] chunk length, little endian
    [8..519] chunk data
  Reads: send the request with SetFeature, then GetFeature returns the same
  header with the data filled in.

  Commands:
    0x03 key matrix (arg = layer)     0x04 LED config, 128 bytes
    0x05 macros                       0x06 per-key colours (arg = group), 384 bytes
    0x0a effect colour palette, 512 bytes
    0x82 read password / device id (6 bytes)

  LED config (cmd 0x04), as built by the app's FUN_0048abf0:
    [9]   1 if the custom (per-key) effect is selected
    [10]  effect id
    [0x3a + 2*(id-1)]  brightness 0..4
    [0x3b + 2*(id-1)]  speed 0..4 (slow..fast) << 4 | colour (0..6 = palette slot, 7 = rainbow)
    [0x7e..0x7f] 5a a5 trailer (kept from the device)

  Palette (cmd 0x0a): 21 bytes (7 x RGB) per effect at offset 21*id,
  5a a5 at offset 0x1fa.

  Per-key colours (cmd 0x06): three 126-byte planes R, G, B indexed by the
  key's matrix position (last column of [KEY] in Dev/kb/F87PRO/KB.ini).
"""
import argparse
import fcntl
import glob
import os
import sys
import time

VID, PID = 0x258A, 0x010C
REPORT_ID = 0x06
REPORT_LEN = 0x208
CHUNK = 0x200
DELAY = 0.02  # the app waits 20 ms before each packet

CMD_MATRIX, CMD_LED, CMD_MACRO, CMD_KEYCOLOR, CMD_PALETTE = 0x03, 0x04, 0x05, 0x06, 0x0A
CFG_LEN, PALETTE_LEN, PLANE = 128, 512, 126

# id: (name, has_speed, has_brightness, has_colour)   from KB.ini LedOptN + text.xml
EFFECTS = {
    0: ("off", 0, 0, 0),
    1: ("static", 0, 1, 1),
    2: ("breathing", 1, 1, 1),
    3: ("rainbow", 1, 1, 0),
    4: ("flash-away", 1, 1, 1),
    5: ("raindrops", 1, 1, 1),
    6: ("rainbow-wheel", 1, 1, 1),
    7: ("ripples", 1, 1, 1),
    8: ("stars", 1, 1, 1),
    9: ("shadow-disappear", 1, 1, 1),
    10: ("retro-snake", 1, 1, 1),
    11: ("neon-stream", 1, 1, 1),
    12: ("reaction", 1, 1, 1),
    13: ("sine-wave", 1, 1, 1),
    14: ("scanning", 1, 1, 1),
    15: ("windmill", 1, 1, 0),
    16: ("waterfall", 1, 1, 0),
    17: ("blossoming", 1, 1, 0),
    18: ("storm", 1, 1, 1),
    21: ("custom", 0, 0, 0),
}
CUSTOM_EFFECT = 21

# Extra light zones in the LED config (mapped on the keyboard with the Fn shortcuts).
# Front zone brightness/speed are inferred from the bar's layout.
ZONES = {"bar": 0x12, "front": 0x1C}
ZONE_MODES = {"off": 0, "rainbow": 1, "cycle": 2, "static": 3, "breathing": 4}
ZONE_COLORS = {"red": 0, "green": 1, "blue": 2, "yellow": 3, "magenta": 4,
               "cyan": 5, "white": 6, "multi": 7}

# key name -> matrix index, from [KEY] in Dev/kb/F87PRO/KB.ini
KEYS = {
    "esc": 0, "f1": 12, "f2": 18, "f3": 24, "f4": 30, "f5": 36, "f6": 42, "f7": 48,
    "f8": 54, "f9": 60, "f10": 66, "f11": 72, "f12": 78, "prtsc": 84, "scrlk": 90,
    "pause": 96, "grave": 1, "1": 7, "2": 13, "3": 19, "4": 25, "5": 31, "6": 37,
    "7": 43, "8": 49, "9": 55, "0": 61, "minus": 67, "equal": 73, "backspace": 79,
    "insert": 85, "home": 91, "pgup": 97, "tab": 2, "q": 8, "w": 14, "e": 20, "r": 26,
    "t": 32, "y": 38, "u": 44, "i": 50, "o": 56, "p": 62, "lbracket": 68,
    "rbracket": 74, "backslash": 80, "delete": 86, "end": 92, "pgdn": 98, "caps": 3,
    "a": 9, "s": 15, "d": 21, "f": 27, "g": 33, "h": 39, "j": 45, "k": 51, "l": 57,
    "semicolon": 63, "quote": 69, "enter": 81, "lshift": 4, "z": 10, "x": 16, "c": 22,
    "v": 28, "b": 34, "n": 40, "m": 46, "comma": 52, "period": 58, "slash": 64,
    "rshift": 82, "up": 94, "lctrl": 5, "lwin": 11, "lalt": 17, "space": 35,
    "ralt": 53, "fn": 59, "menu": 65, "rctrl": 83, "left": 89, "down": 95, "right": 101,
}


def _ioc(nr, size):
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


HIDIOCSFEATURE = _ioc(0x06, REPORT_LEN)
HIDIOCGFEATURE = _ioc(0x07, REPORT_LEN)


def find_device():
    """Return the hidraw node of the vendor interface (the one with feature report 6)."""
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(f"{node}/device/uevent") as f:
                uevent = f.read()
            with open(f"{node}/device/report_descriptor", "rb") as f:
                desc = f.read()
        except OSError:
            continue
        if f"HID_ID=0003:{VID:08X}:{PID:08X}" in uevent and b"\x85\x06" in desc:
            return "/dev/" + os.path.basename(node)
    sys.exit("AULA F87 (258a:010c) vendor interface not found; is it plugged in by USB?")


class Keyboard:
    def __init__(self, path=None):
        self.path = path or find_device()
        self.fd = os.open(self.path, os.O_RDWR)

    def close(self):
        os.close(self.fd)

    def _packets(self, cmd, arg, data, size):
        count = (size + CHUNK - 1) // CHUNK
        for i in range(count):
            n = min(CHUNK, size - i * CHUNK)
            buf = bytearray(REPORT_LEN)
            buf[0:8] = bytes([REPORT_ID, cmd, arg, 0, count, i, n & 0xFF, n >> 8])
            if data is not None:
                buf[8:8 + n] = data[i * CHUNK:i * CHUNK + n]
            yield buf, n

    def write(self, cmd, data, arg=0):
        for buf, _ in self._packets(cmd, arg, data, len(data)):
            time.sleep(DELAY)
            fcntl.ioctl(self.fd, HIDIOCSFEATURE, bytes(buf))

    def read(self, cmd, size, arg=0):
        out = bytearray()
        for buf, n in self._packets(cmd | 0x80, arg, None, size):
            time.sleep(DELAY)
            fcntl.ioctl(self.fd, HIDIOCSFEATURE, bytes(buf))
            time.sleep(DELAY)
            resp = bytearray(REPORT_LEN)
            resp[0] = REPORT_ID
            fcntl.ioctl(self.fd, HIDIOCGFEATURE, resp)
            out += resp[8:8 + n]
        return out

    def get_config(self):
        return self.read(CMD_LED, CFG_LEN)

    def set_config(self, cfg):
        # The firmware only restarts its LEDs when the effect id changes; writing a
        # config with the same effect leaves every light off until replug. So bounce
        # through a different effect first.
        if self.get_config()[10] == cfg[10]:
            tmp = bytearray(cfg)
            tmp[10] = 0 if cfg[10] else 1
            self.write(CMD_LED, bytes(tmp))
            time.sleep(0.05)
        self.write(CMD_LED, bytes(cfg))

    def set_zone(self, zone, mode=None, color=None, brightness=None, speed=None):
        """zone: 'bar' or 'front'. Each zone is 4 bytes: mode, colour, brightness, speed."""
        base = ZONES[zone]
        cfg = self.get_config()
        for i, v in enumerate((mode, color, brightness, speed)):
            if v is not None:
                cfg[base + i] = v
        self.set_config(cfg)

    def get_palette(self):
        return self.read(CMD_PALETTE, PALETTE_LEN)

    def set_palette(self, pal):
        pal = bytearray(pal)
        pal[0x1FA:0x1FC] = b"\x5a\xa5"
        self.write(CMD_PALETTE, bytes(pal))

    def get_key_colors(self, group=0):
        data = self.read(CMD_KEYCOLOR, PLANE * 3 + 6, group)
        return [(data[i], data[PLANE + i], data[2 * PLANE + i]) for i in range(PLANE)]

    def set_key_colors(self, colors, group=0):
        """colors: dict matrix_index -> (r, g, b); keys not given are off."""
        data = bytearray(PLANE * 3 + 6)
        for idx, (r, g, b) in colors.items():
            data[idx], data[PLANE + idx], data[2 * PLANE + idx] = r, g, b
        self.write(CMD_KEYCOLOR, bytes(data), group)

    def set_effect(self, effect, brightness=None, speed=None, color=None, rainbow=False):
        """color: (r, g, b) written into palette slot 0 of this effect."""
        cfg = self.get_config()
        cfg[9] = 1 if effect == CUSTOM_EFFECT else 0
        cfg[10] = effect
        if 1 <= effect <= 18:
            slot = 0x3A + 2 * (effect - 1)
            if brightness is not None:
                cfg[slot] = brightness
            spd, col = cfg[slot + 1] >> 4, cfg[slot + 1] & 0x0F
            if speed is not None:
                spd = speed
            if rainbow:
                col = 7
            elif color is not None:
                col = 0
                pal = self.get_palette()
                pal[21 * effect:21 * effect + 3] = bytes(color)
                self.set_palette(pal)
                time.sleep(0.05)
            cfg[slot + 1] = (spd << 4) | col
        self.set_config(cfg)


def parse_color(s):
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError("colour must be RRGGBB")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def parse_effect(s):
    if s.isdigit() and int(s) in EFFECTS:
        return int(s)
    for k, (name, *_) in EFFECTS.items():
        if name == s.lower():
            return k
    raise argparse.ArgumentTypeError(f"unknown effect {s!r}; see 'list'")


def level(s):
    v = int(s)
    if not 0 <= v <= 4:
        raise argparse.ArgumentTypeError("must be 0..4")
    return v


def hexdump(data):
    for i in range(0, len(data), 16):
        print(f"  {i:03x}: {data[i:i + 16].hex(' ')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--device", help="hidraw node (default: auto-detect)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list effects")
    sub.add_parser("info", help="show model id and firmware version")
    sub.add_parser("dump", help="print LED config and palette")

    p = sub.add_parser("effect", help="select a built-in effect")
    p.add_argument("effect", type=parse_effect)
    p.add_argument("-b", "--brightness", type=level)
    p.add_argument("-s", "--speed", type=level, help="0 (slow) .. 4 (fast)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("-c", "--color", type=parse_color, help="RRGGBB")
    g.add_argument("-r", "--rainbow", action="store_true", help="multicolour")

    p = sub.add_parser("custom", help="per-key colours (custom effect)")
    p.add_argument("--all", type=parse_color, help="base colour for every key")
    p.add_argument("--group", type=int, default=0, help="custom colour group (default 0)")
    p.add_argument("keys", nargs="*", metavar="KEY=RRGGBB",
                   help=f"key names: {' '.join(KEYS)}")

    p = sub.add_parser("light", help="the light bar or the front light")
    p.add_argument("zone", choices=ZONES)
    p.add_argument("-m", "--mode", choices=ZONE_MODES)
    p.add_argument("-c", "--color", choices=ZONE_COLORS)
    p.add_argument("-b", "--brightness", type=level)
    p.add_argument("-s", "--speed", type=level)

    p = sub.add_parser("raw", help="send a raw write command")
    p.add_argument("command", type=lambda s: int(s, 0))
    p.add_argument("hexdata")
    p.add_argument("--arg", type=lambda s: int(s, 0), default=0)

    a = ap.parse_args()
    if a.cmd == "list":
        for k, (name, spd, bri, col) in EFFECTS.items():
            opts = [o for o, f in (("speed", spd), ("brightness", bri), ("color", col)) if f]
            print(f"{k:3} {name:18} {' '.join(opts)}")
        return

    kb = Keyboard(a.device)
    try:
        if a.cmd == "info":
            model = kb.read(0x02, 6, arg=1)[5]
            usb = os.path.realpath(f"/sys/class/hidraw/{os.path.basename(kb.path)}/device/../..")
            with open(f"{usb}/bcdDevice") as f:
                fw = f.read().strip()
            names = {0x8F: "AULA F87", 0x0B: "AULA F87 PRO", 0xA9: "AULA F87 PRO Wired"}
            print(f"model id 0x{model:02X} ({names.get(model, 'unknown')}), firmware {fw[:2]}.{fw[2:]}")
        elif a.cmd == "dump":
            print("LED config (0x84):")
            hexdump(kb.get_config())
            print("Palette (0x8a):")
            hexdump(kb.get_palette())
        elif a.cmd == "effect":
            kb.set_effect(a.effect, a.brightness, a.speed, a.color, a.rainbow)
        elif a.cmd == "custom":
            colors = {i: a.all for i in KEYS.values()} if a.all else {}
            for spec in a.keys:
                name, _, col = spec.partition("=")
                if name.lower() not in KEYS:
                    sys.exit(f"unknown key {name!r}")
                colors[KEYS[name.lower()]] = parse_color(col)
            kb.set_key_colors(colors, a.group)
            time.sleep(0.05)
            kb.set_effect(CUSTOM_EFFECT)
        elif a.cmd == "light":
            kb.set_zone(a.zone, ZONE_MODES.get(a.mode), ZONE_COLORS.get(a.color),
                        a.brightness, a.speed)
        elif a.cmd == "raw":
            kb.write(a.command, bytes.fromhex(a.hexdata), a.arg)
    finally:
        kb.close()


if __name__ == "__main__":
    main()
