#!/usr/bin/env python3
"""Play a video on the AULA F87's key lights, live over USB. Stock firmware, no flashing needed.

How it works (found in the base F87 firmware):
  - Report 6 command 0x08 ("real data", used by the AULA app's music mode) is copied straight into
    the LED frame buffer at XRAM 0x0152 (handler 0x056E): 21 columns x 6 rows x RGB = 378 bytes,
    indexed (led_col * 6 + row) * 3. Nothing is written to flash.
  - While frames keep arriving, the firmware pauses its normal effects and shows the buffer
    (lighting engine 0x1212). About 200 timer counts after the last frame (counter 0x0D96, checked
    at 0x8D67) it goes back to the normal lighting by itself.
  - Only works with the cable connected (the handler ignores it in 2.4 GHz / Bluetooth mode).

The video is decoded on this machine with ffmpeg and never stored. Each key shows the average of
the part of the picture it physically covers (key positions and widths are in KEYS below).

usage:
  stream_video.py VIDEO [--fps 30] [--fit stretch|crop|pad] [--audio] [--show] [--lag auto|MS] [--invert] [--gamma 1.0]
  stream_video.py --test        # lights the keys one by one so you can check the layout
"""
import argparse
import fcntl
import glob
import os
import shutil
import subprocess
import sys
import time

VID, PID = 0x258A, 0x010C
REPORT_ID, REPORT_LEN = 0x06, 0x208
CMD_LIVE = 0x08
COLS, ROWS = 17, 6
FRAME_LEN = 21 * ROWS * 3          # the firmware accepts 21 columns x 6 rows x RGB

# Shift row (row 4): LED column -> physical (keymap) column, inverse of the firmware table at 0x2B5F.
# Every other row maps 1:1. Verified on the keyboard with --test.
SHIFT_ROW_PHYS = {0: 0, 12: 1, **{led: led + 1 for led in range(1, 12)}, 13: 13, 14: 14, 15: 15, 16: 16}

# Physical layout of the AULA F87 (ANSI tenkeyless, 87 keys), from a photo of the keyboard.
# Keyed by firmware matrix position (col, row) -- the keymap / AULA-app numbering -- with each key's
# left edge x, top y and width in key units (1u = one normal key). Matrix positions that have no
# key on this layout (the ISO "#" and "\\" keys, Int1, gaps) are simply absent.
_ROW_Y = (0.0, 1.25, 2.25, 3.25, 4.25, 5.25)          # F-row sits 0.25u above the number row
_LAYOUT = [
    # row 0: Esc, F1-F4, F5-F8, F9-F12, PrtSc ScrLk Pause
    [(0, "Esc", 0, 1)] + [(2 + i, f"F{1 + i}", 2 + i, 1) for i in range(4)]
    + [(6 + i, f"F{5 + i}", 6.5 + i, 1) for i in range(4)]
    + [(10 + i, f"F{9 + i}", 11 + i, 1) for i in range(4)]
    + [(14, "PrtSc", 15.25, 1), (15, "ScrLk", 16.25, 1), (16, "Pause", 17.25, 1)],
    # row 1: ` 1..0 - = Backspace, Ins Home PgUp
    [(i, k, i, 1) for i, k in enumerate("` 1 2 3 4 5 6 7 8 9 0 - =".split())]
    + [(13, "Bksp", 13, 2), (14, "Ins", 15.25, 1), (15, "Home", 16.25, 1), (16, "PgUp", 17.25, 1)],
    # row 2: Tab Q..] \, Del End PgDn
    [(0, "Tab", 0, 1.5)] + [(1 + i, k, 1.5 + i, 1) for i, k in enumerate("Q W E R T Y U I O P [ ]".split())]
    + [(13, "\\", 13.5, 1.5), (14, "Del", 15.25, 1), (15, "End", 16.25, 1), (16, "PgDn", 17.25, 1)],
    # row 3: Caps A..' Enter (ANSI: no # key at matrix col 12)
    [(0, "Caps", 0, 1.75)] + [(1 + i, k, 1.75 + i, 1) for i, k in enumerate("A S D F G H J K L ; '".split())]
    + [(13, "Enter", 12.75, 2.25)],
    # row 4: LShift Z../ RShift, Up (ANSI: no Int1 / ISO-backslash at matrix cols 11, 12)
    [(0, "LShift", 0, 2.25)] + [(1 + i, k, 2.25 + i, 1) for i, k in enumerate("Z X C V B N M , . /".split())]
    + [(13, "RShift", 12.25, 2.75), (15, "Up", 16.25, 1)],
    # row 5: LCtrl Win LAlt Space RAlt Fn Code(Menu) RCtrl, Left Down Right
    [(0, "LCtrl", 0, 1.25), (1, "Win", 1.25, 1.25), (2, "LAlt", 2.5, 1.25), (5, "Space", 3.75, 6.25),
     (8, "RAlt", 10, 1.25), (9, "Fn", 11.25, 1.25), (10, "Code", 12.5, 1.25), (13, "RCtrl", 13.75, 1.25),
     (14, "Left", 15.25, 1), (15, "Down", 16.25, 1), (16, "Right", 17.25, 1)],
]
KEYS = {(col, row): (name, x, _ROW_Y[row], w)
        for row, keys in enumerate(_LAYOUT) for col, name, x, w in keys}
BOARD_W, BOARD_H = 18.25, 6.25                         # key units
PX_PER_U = 4                                           # video is sampled at 4 pixels per key unit
GRID_W, GRID_H = round(BOARD_W * PX_PER_U), round(BOARD_H * PX_PER_U)


def _ioc(nr, size):
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


HIDIOCSFEATURE = _ioc(0x06, REPORT_LEN)


def find_device():
    """hidraw node of the vendor interface (the one with feature report 6)."""
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(f"{node}/device/uevent").read()
            desc = open(f"{node}/device/report_descriptor", "rb").read()
        except OSError:
            continue
        if f"HID_ID=0003:{VID:08X}:{PID:08X}" in uevent and b"\x85\x06" in desc:
            return "/dev/" + os.path.basename(node)
    sys.exit("AULA F87 (258a:010c) vendor interface not found. Is it connected by cable, "
             "and do you have access to /dev/hidraw* (see the udev rule in the f87fw README)?")


class LiveLights:
    def __init__(self, path=None):
        self.fd = os.open(path or find_device(), os.O_RDWR)

    def send(self, rgb_by_led):
        """Show one frame. rgb_by_led: function (led_col, row) -> (r, g, b), each 0-255."""
        buf = bytearray(REPORT_LEN)
        buf[0:8] = bytes([REPORT_ID, CMD_LIVE, 0, 0, 1, 0, FRAME_LEN & 0xFF, FRAME_LEN >> 8])
        for col in range(COLS):
            for row in range(ROWS):
                r, g, b = rgb_by_led(col, row)
                i = 8 + (col * ROWS + row) * 3
                buf[i:i + 3] = bytes((r, g, b))
        fcntl.ioctl(self.fd, HIDIOCSFEATURE, bytes(buf))

    def black(self):
        self.send(lambda c, r: (0, 0, 0))

    def close(self):
        os.close(self.fd)


def phys_col(led_col, row):
    return SHIFT_ROW_PHYS.get(led_col, led_col) if row == 4 else led_col


def led_of(col, row):
    """LED buffer column of the key at matrix (col, row)."""
    return next(c for c in range(COLS) if phys_col(c, row) == col)


def run_test(lights, delay):
    print(f"Lighting all {len(KEYS)} keys in turn, left to right, row by row. "
          "Check that the named key lights up.\n")
    try:
        for (col, row), (name, x, y, w) in sorted(KEYS.items(), key=lambda k: (k[0][1], k[1][1])):
            led = led_of(col, row)
            print(f"  row {row}: {name}", flush=True)
            for _ in range(max(1, int(delay / 0.05))):     # keep sending so live mode stays on
                lights.send(lambda c, r: (255, 255, 255) if (c, r) == (led, row) else (0, 0, 0))
                time.sleep(0.05)
    finally:
        lights.black()


def key_regions():
    """For every LED (col, row): the list of pixel indexes of its key in the GRID_W x GRID_H frame."""
    regions = {}
    for c in range(COLS):
        for r in range(ROWS):
            key = KEYS.get((phys_col(c, r), r))
            if key is None:
                continue
            _, x, y, w = key
            x0, x1 = round(x * PX_PER_U), max(round(x * PX_PER_U) + 1, round((x + w) * PX_PER_U))
            y0, y1 = round(y * PX_PER_U), round((y + 1) * PX_PER_U)
            regions[(c, r)] = [py * GRID_W + px for py in range(y0, y1) for px in range(x0, x1)]
    return regions


def run_video(lights, a):
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found")
    fit = {
        "stretch": f"scale={GRID_W}:{GRID_H}:flags=area",
        "crop": f"crop=iw:'min(ih,iw*{GRID_H}/{GRID_W})',scale={GRID_W}:{GRID_H}:flags=area",
        "pad": f"scale={GRID_W}:{GRID_H}:flags=area:force_original_aspect_ratio=decrease,"
               f"pad={GRID_W}:{GRID_H}:(ow-iw)/2:(oh-ih)/2",
    }[a.fit]
    vf = f"fps={a.fps},{fit},format=gray"
    dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", a.video, "-vf", vf,
                            "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    lut = bytes(min(255, round(255 * ((v / 255) ** a.gamma) * a.brightness)) for v in range(256))
    if a.invert:
        lut = bytes(lut[255 - v] for v in range(256))

    audio = None
    frame_bytes = GRID_W * GRID_H
    regions = key_regions()
    period = 1.0 / a.fps
    sent = skipped = 0
    worst = total_write = 0.0
    auto_lag = a.lag == "auto"
    lag = 0.0 if auto_lag else float(a.lag) / 1000     # send frames this much early
    start = None
    try:
        while True:
            px = dec.stdout.read(frame_bytes)
            if len(px) < frame_bytes:
                break
            if start is None:
                if (a.audio or a.show) and shutil.which("ffplay"):
                    cmd = ["ffplay", "-autoexit", "-loglevel", "quiet"]
                    if a.show:
                        cmd += ["-window_title", os.path.basename(a.video)]
                    else:
                        cmd.append("-nodisp")              # sound only
                    if not a.audio:
                        cmd.append("-an")                  # window only, muted
                    audio = subprocess.Popen(cmd + [a.video])
                elif a.audio or a.show:
                    print("ffplay not found: playing on the keyboard only")
                start = time.monotonic()
            # A frame becomes visible when its USB write finishes, so start the write `lag` early.
            due = start + (sent + skipped) * period - lag
            now = time.monotonic()
            if now > due + period:                 # running late: drop this frame to stay in sync
                skipped += 1
                continue
            level = {led: lut[sum(px[i] for i in idx) // len(idx)] for led, idx in regions.items()}
            now = time.monotonic()
            if now < due:
                time.sleep(due - now)
            t0 = time.monotonic()
            lights.send(lambda c, r: (level.get((c, r), 0),) * 3)
            took = time.monotonic() - t0
            worst = max(worst, took)
            total_write += took
            sent += 1
            if auto_lag:                           # follow the measured write time (smoothed)
                lag = took if sent == 1 else lag * 0.9 + took * 0.1
    except KeyboardInterrupt:
        pass
    finally:
        lights.black()
        dec.kill()
        if audio:
            audio.terminate()
    total = sent + skipped
    if total:
        print(f"{sent} frames shown, {skipped} dropped ({100 * skipped / total:.1f}%), "
              f"USB write avg {total_write / max(sent, 1) * 1000:.1f} ms / slowest {worst * 1000:.1f} ms, "
              f"keyboard sent {lag * 1000:.0f} ms early" + (" (auto)" if auto_lag else ""))
        if skipped > total * 0.05:
            print(f"tip: the keyboard can't keep up with {a.fps} fps; try --fps "
                  f"{max(5, int(1 / max(worst, 1e-3) * 0.8))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?", help="any video file ffmpeg can read")
    ap.add_argument("--fps", type=float, default=30, help="frames per second to send (default 30)")
    ap.add_argument("--fit", choices=("stretch", "crop", "pad"), default="stretch",
                    help="how to fit the picture onto the keyboard (default stretch)")
    ap.add_argument("--audio", action="store_true", help="play the sound with ffplay")
    ap.add_argument("--lag", default="auto", metavar="MS|auto",
                    help="send keyboard frames this many ms early to make up for the USB write time. "
                         "auto (default) measures it; raise it if the keys are still behind the "
                         "window/sound, lower it (or go negative) if they're ahead")
    ap.add_argument("--show", action="store_true",
                    help="also show the video in an ffplay window on the PC (add --audio for sound)")
    ap.add_argument("--invert", action="store_true", help="swap light and dark")
    ap.add_argument("--gamma", type=float, default=1.0, help="brightness curve, >1 = darker mid-tones")
    ap.add_argument("--brightness", type=float, default=1.0, help="0..1 scale (default 1)")
    ap.add_argument("--test", action="store_true", help="light each key in turn to check the layout")
    ap.add_argument("--test-delay", type=float, default=0.4, help="seconds per key in --test")
    ap.add_argument("--device", help="hidraw node (default: autodetect)")
    a = ap.parse_args()
    if not a.test and not a.video:
        ap.error("give a video file, or --test")

    lights = LiveLights(a.device)
    try:
        if a.test:
            run_test(lights, a.test_delay)
        else:
            run_video(lights, a)
    finally:
        lights.close()


if __name__ == "__main__":
    main()
