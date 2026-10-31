# Live lighting: video on the AULA F87's keys

`live/stream_video.py` plays any video on the keyboard's backlight, in real time over USB. It can
open the same video in a window on your PC, with sound, in sync with the keys.

It works on the **stock firmware**, with nothing flashed. The keyboard already has a live
per-key display mode, the one the AULA app uses for its music equaliser. This tool sends its own
frames to it. The same channel works for anything else you want to draw on the keys from your PC
(see [Your own live effects](#your-own-live-effects)).

---

## Contents

- [Quick start](#quick-start)
- [Requirements](#requirements)
- [Options](#options)
- [Checking the key layout (`--test`)](#checking-the-key-layout---test)
- [Fitting the picture](#fitting-the-picture)
- [Sync with the PC (`--lag`)](#sync-with-the-pc---lag)
- [How it works](#how-it-works)
- [The live frame format](#the-live-frame-format)
- [Your own live effects](#your-own-live-effects)
- [Troubleshooting](#troubleshooting)
- [Reference](#reference)

---

## Quick start

Connect the keyboard **by cable**, with the switch on the back at **USB**, then:

```sh
python3 live/stream_video.py --test                         # once: check the key layout
python3 live/stream_video.py your_video.mp4 --show --audio  # keys + window + sound
```

Press Ctrl-C to stop. The keys go dark, and shortly afterwards the keyboard returns to its normal
lighting by itself.

The video is decoded on your machine with `ffmpeg` and streamed straight to the keyboard. Nothing
is saved to disk, so no part of the video ends up in this repository.

---

## Requirements

- **Linux** and **Python 3** (standard library only)
- **`ffmpeg`**, and **`ffplay`** for `--audio` / `--show`. Both come in the `ffmpeg` package of
  most distributions.
- **Access to the keyboard's hidraw device.** The udev rule from the
  [f87fw README](https://github.com/tmtco1/f87fw#step-2-give-your-user-access-to-the-keyboard)
  covers it:

  ```sh
  printf '%s\n' 'SUBSYSTEMS=="usb|hidraw", ATTRS{idVendor}=="258a", MODE="0666", TAG+="uaccess"' \
    | sudo tee /etc/udev/rules.d/99-aula-f87.rules
  sudo udevadm control --reload            # then replug the keyboard
  ```

- **Cable connection.** The firmware ignores live frames in 2.4 GHz and Bluetooth mode.

---

## Options

```
stream_video.py VIDEO [--fps 30] [--fit stretch|crop|pad] [--audio] [--show] [--lag auto|MS]
                      [--invert] [--gamma 1.0] [--brightness 1.0] [--device /dev/hidrawN]
stream_video.py --test [--test-delay 0.4]
```

| Option | Default | What it does |
|---|---|---|
| `VIDEO` | | Any file `ffmpeg` can read |
| `--fps N` | 30 | Frames per second sent to the keyboard |
| `--fit stretch\|crop\|pad` | `stretch` | How the picture is fitted onto the keyboard, see [Fitting the picture](#fitting-the-picture) |
| `--audio` | off | Play the sound with `ffplay` |
| `--show` | off | Open the video in an `ffplay` window on the PC. Combine with `--audio` for picture and sound. |
| `--lag auto\|MS` | `auto` | Send keyboard frames early to make up for the USB write time, see [Sync](#sync-with-the-pc---lag) |
| `--invert` | off | Swap light and dark |
| `--gamma G` | 1.0 | Brightness curve. Above 1 darkens mid-tones, below 1 brightens them. |
| `--brightness B` | 1.0 | Overall brightness, 0–1 |
| `--test` | | Light every key in turn, with its name printed, instead of playing a video |
| `--test-delay S` | 0.4 | Seconds per key in `--test` |
| `--device PATH` | auto | Use this hidraw node instead of finding the keyboard automatically |

`--audio` and `--show` together start a single `ffplay` with picture and sound. `--show` alone
opens a muted window, and `--audio` alone plays only the sound.

When playback ends, the tool prints a summary, for example:

```
6570 frames shown, 12 dropped (0.2%), USB write avg 21.4 ms / slowest 38.0 ms, keyboard sent 22 ms early (auto)
```

- **Dropped frames** are skipped on purpose when the keyboard falls behind, so it stays in sync
  with the sound instead of drifting. If more than 5 % are dropped, the tool suggests a lower
  `--fps`.
- **USB write** is how long the keyboard takes to accept one frame.
- **Sent … early** is the lag compensation that was used.

---

## Checking the key layout (`--test`)

```sh
python3 live/stream_video.py --test
```

The tool lights the 87 keys one at a time, left to right and row by row, and prints each key's
name. If the key that lights up always matches the printed name, the layout is right. This has
been verified on a real AULA F87.

Run it again if you use a different F87 variant: an ISO model, or the F87 Pro with a different
firmware. Those may have keys in other positions.

---

## Fitting the picture

The keyboard is about 18.25 × 6.25 key widths, close to 3:1. Most videos are 16:9 or 4:3, so the
picture has to be fitted:

| `--fit` | Result | Good for |
|---|---|---|
| `stretch` | Whole picture, squashed to the keyboard's shape | Most things. Silhouettes stay readable. |
| `crop` | Correct proportions, the top and bottom are cut off | Subjects in the middle of the frame |
| `pad` | Whole picture with correct proportions, black bars left and right | Keeping shapes exact. Only the middle third of the keyboard is used. |

**How keys sample the picture.** The video is scaled to 73 × 25 pixels: 4 pixels per key width,
with the F-row gap included. Each key shows the average of the pixels it physically covers. The
tool knows the position and width of every key on the F87 (ANSI tenkeyless), so a wide key
averages a wider strip:

| Key | Width | | Key | Width |
|---|---|---|---|---|
| Tab, `\` | 1.5 | | Backspace | 2 |
| Caps | 1.75 | | Enter, left Shift | 2.25 |
| Right Shift | 2.75 | | Space | 6.25 |
| Ctrl, Win, Alt, Fn, Code | 1.25 | | everything else | 1 |

The rows are staggered like the real keyboard, so diagonal edges in the video stay diagonal on the
keys. The layout lives in `_LAYOUT` / `KEYS` at the top of `stream_video.py`.

Each key shows the brightness as white (R = G = B). The firmware applies its own per-channel
correction, so greys can look slightly tinted. `--gamma` helps when mid-tones look too bright.

---

## Sync with the PC (`--lag`)

A frame becomes visible on the keys only once its USB write has finished. The keyboard receives
the 520-byte report in 8-byte pieces, so one write can take tens of milliseconds. If frames were
sent exactly when they're due, the keys would trail the window and sound by that write time.

With `--lag auto` (the default), the tool times every write while it plays, keeps a smoothed
average, and starts each frame's write that much early. The frame then lands on the keys on
schedule. In an offline test with a simulated 40 ms write, the keys trailed by 40 ms with
`--lag 0`, and were on time with `--lag auto`.

To fine-tune by eye, give a value in milliseconds:

| What you see | Try |
|---|---|
| Keys still a little behind the window / sound | a value above the auto value from the summary, e.g. `--lag 80` |
| Keys ahead of the window | a smaller value, e.g. `--lag 20` (or even negative, since `ffplay` takes a moment to open its window) |

---

## How it works

All of this was found by decompiling the base F87 firmware (`base_f87_decrypted.bin`). The
addresses refer to that image.

1. **The command.** The AULA app talks to the keyboard with 520-byte HID feature reports (report
   ID 6, an 8-byte header plus up to 512 bytes of data). Command `0x08`, which the app sends in music
   mode, is handled specially by the USB receive code (`0x0200`): its data goes straight into the
   **LED frame buffer at XRAM `0x0152`**, the same buffer the normal effects draw into, instead
   of the staging buffer that other commands use before being saved to flash.

2. **Live mode on.** When the report is complete, the handler for command 8 (`0x056E`) runs:

   ```
   if (connection == USB) {     // XRAM 0x0317 == 0
       SETB 0x52                // "new frame": the lighting engine pushes the buffer to the LEDs
       SETB 0x53                // live mode: normal effects are paused
       0x0D96 = 0               // reset the live-mode timeout
   } else {                     // 2.4 GHz or Bluetooth: live mode off
       CLR 0x52; CLR 0x53
   }
   ```

3. **Display.** The lighting engine (`0x1212`) sees the "new frame" bit and converts the buffer
   into the LED driver's PWM values at XRAM `0x059E` (value × 4 plus a per-channel correction
   from a table at `0x257F`). While live mode is on, the normal effects don't run.

4. **Timeout.** A counter (`0x0D96`, checked at `0x8D67`) counts up while no frames arrive. Past
   200 it switches live mode off and restarts the normal lighting. Every new frame resets it. The
   tick length hasn't been measured, so the exact time isn't known, but in practice it's short.

**No flash is involved.** The per-key colour command the AULA app uses for static colours
(`0x06`) is saved to flash, which makes the keyboard blink and wears the flash on every update.
Command `0x08` only touches RAM, so it can run at video frame rates indefinitely.

---

## The live frame format

One frame is one feature report, 520 bytes including the report ID:

| Offset | Value | Meaning |
|---|---|---|
| 0 | `0x06` | Report ID |
| 1 | `0x08` | Command: live frame |
| 2 | `0x00` | Argument. Keep it 0: other values select other uses of the buffer (2 fills it with one colour, 1 is frame-based). |
| 3 | `0x00` | |
| 4 | `0x01` | Packet count |
| 5 | `0x00` | Packet index |
| 6–7 | `0x7A 0x01` | Data length, little endian: 378 |
| 8–385 | | Frame: 378 bytes |
| 386–519 | `0x00` | Padding |

**Frame layout.** 21 LED columns × 6 rows × 3 bytes (R, G, B), column by column:

```
byte = (led_col * 6 + row) * 3 + channel        channel 0 = R, 1 = G, 2 = B
```

Only LED columns 0–16 exist on the F87. Columns 17–20 are accepted but unused.

**LED positions** match the keyboard's grid (see `docs/BOOT_ANIMATIONS.md`, "Key positions"),
except on the Shift row, which the firmware wires in a different order:

| LED col | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **row 4** | LShift | X | C | V | B | N | M | , | . | / | – | – | Z | RShift | – | Up | – |

`stream_video.py` handles this with `phys_col()`. Verified on the keyboard with `--test`.

**Sending it on Linux** is one ioctl on the hidraw node of the keyboard's vendor interface:
`HIDIOCSFEATURE(520)`. The tool finds that node by VID/PID `258a:010c` and a report descriptor
containing report ID 6. Send frames continuously. If you stop for longer than the timeout, the
keyboard goes back to its normal lighting.

---

## Your own live effects

`stream_video.py` can be imported, so a few lines of Python are enough to draw anything on the
keys. This example runs a rainbow wave across the keyboard for 10 seconds:

```python
import colorsys, sys, time
sys.path.insert(0, "live")
from stream_video import LiveLights, KEYS, phys_col

lights = LiveLights()                       # finds the keyboard automatically
try:
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10:       # run for 10 seconds
        t = time.monotonic() - t0
        def colour(led_col, row):
            key = KEYS.get((phys_col(led_col, row), row))
            if key is None:                 # no key at this position
                return (0, 0, 0)
            name, x, y, w = key             # x = key's left edge, in key widths
            r, g, b = colorsys.hsv_to_rgb((x / 18.25 - t * 0.3) % 1.0, 1, 1)
            return (int(r * 255), int(g * 255), int(b * 255))
        lights.send(colour)
        time.sleep(1 / 30)
finally:
    lights.black()                          # normal lighting returns after the timeout
    lights.close()
```

Run it from the repository root: `python3 my_effect.py`.

| Name | What it is |
|---|---|
| `LiveLights(path=None)` | Opens the keyboard (autodetected, or a given `/dev/hidrawN`) |
| `LiveLights.send(fn)` | Shows one frame. `fn(led_col, row)` returns `(r, g, b)`, each 0–255. It's called for every LED position. |
| `LiveLights.black()` | Shows an all-black frame |
| `LiveLights.close()` | Closes the device |
| `KEYS[(col, row)]` | `(name, x, y, width)` of the key at keyboard-grid position `(col, row)`, in key widths. Missing means no key. |
| `phys_col(led_col, row)` | LED column → keyboard-grid column (differs only on the Shift row) |
| `led_of(col, row)` | Keyboard-grid column → LED column |

Ideas: a CPU or RAM load bar on the number row, a notification flash, music-reactive lighting,
a clock on the F-keys, an on-screen keyboard mirror, Conway's Game of Life.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `vendor interface not found` | keyboard not connected by cable, or no permission for `/dev/hidraw*` | plug in by cable with the switch on USB; add the udev rule (see [Requirements](#requirements)) and replug |
| Nothing lights up | keyboard in 2.4 GHz / Bluetooth mode | switch to USB; live frames only work wired |
| `PermissionError` | udev rule missing or not applied yet | add the rule, run `sudo udevadm control --reload`, replug |
| Many dropped frames | the keyboard can't take the frame rate | use the `--fps` value the summary suggests |
| Keys behind or ahead of the window / sound | lag compensation off for your system | adjust `--lag`, see [Sync](#sync-with-the-pc---lag) |
| Mid-tones too bright | LED brightness isn't linear | `--gamma 2` |
| The picture looks squashed | 16:9 video stretched onto the keyboard | `--fit crop` |
| Normal lighting doesn't come back right away after stopping | expected: it waits for the live-mode timeout | wait a moment |
| The AULA app is open at the same time | both send lighting commands | close the app while streaming |

---

## Reference

| Address | Space | Role |
|---|---|---|
| `0x0200` | code | USB report receive handler: command 8 data → `0x0152`, other commands → staging buffer `0x09B8` |
| `0x0495` | code | Report-6 command jump table (commands 3–10) |
| `0x056E` | code | Command 8 handler: enables live mode (USB only), resets the timeout |
| `0x1212` | code | Lighting engine: pushes `0x0152` to the PWM buffer when a new frame is flagged |
| `0x8D67` | code | Live-mode timeout check (counter > 200 → back to normal lighting) |
| `0x257F` | code | Per-channel PWM correction table |
| `0x0152` | XRAM | LED frame buffer, 21 × 6 × RGB, `(led_col * 6 + row) * 3` |
| `0x059E` | XRAM | PWM output buffer, 10-bit values, 36 bytes per column |
| `0x0D96` | XRAM | Live-mode timeout counter (16-bit) |
| `0x0317` | XRAM | Connection mode (0 = USB) |
| `0x52`, `0x53` | bits | "New frame" and "live mode active" flags |
| `0x2B5F` | code | Keyboard grid → LED column table (Shift-row remap) |

---

*Written with Claude Opus 5.5*
