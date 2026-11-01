# Bad Apple lighting effect

Adds a new lighting effect to the AULA F87 firmware that plays a video (Bad Apple!!, or any other)
on the keys, stored in the keyboard itself. No PC needed: select the effect and it loops forever.
All stock effects, keys and settings stay as they are.

- 1 bit (each key on or off), any colour, 10 fps by default
- about **63 s** of Bad Apple fits (4 KB of free flash), then it starts over
- effect **6**: selectable with the Fn effect key, `aulaf87.py effect badapple`, or effect id 6 in the
  vendor app (it calls it "rainbow-wheel", which this keyboard never had)

For the full video with sound, stream it from the PC instead (see [LIVE_LIGHTING.md](LIVE_LIGHTING.md)).

---

## Quick start

Requires SDCC (for its assembler `sdas8051`, also used for boot animations) and ffmpeg.

```sh
python3 effects/badapple/build.py tools/live/badapple.mp4
python3 tools/patch_firmware.py base_f87_decrypted.bin out.bin --badapple
./sinowisp write -d aula-f87 --format bin out.bin
```

Replug, then select the effect:

```sh
python3 tools/aulaf87.py effect badapple
```

or press the Fn effect key until it shows up (it sits between effect 5 and 7).

`--badapple` can be combined with every other patcher option (names, boot animation, `--life`, ...); see
[PATCHING.md](PATCHING.md). The story of how this was found and built is in [CUSTOM_EFFECTS.md](CUSTOM_EFFECTS.md).

---

## Speed and timing

The firmware counts time in timer ticks. Their exact length hasn't been measured; the build assumes
**1 ms** (`--tick-ms 1.0`), which fits the stock effects' timing tables. If the video runs too fast or
too slow:

1. **Fine tuning without reflashing:** the effect's speed setting (Fn speed keys, or
   `aulaf87.py effect badapple -s N`) changes the frame period:

   | Speed | 0 | 1 | 2 | 3 | 4 |
   |---|---|---|---|---|---|
   | Frame period | 120% | 110% | 100% | 90% | 80% |

2. **Calibrating:** play it at speed 2 and time one loop with a stopwatch, from the first lit
   frame to the next loop's first lit frame. The build prints the expected length
   (`627 frames = 62.7 s`). Rebuild with

   ```
   --tick-ms = old tick-ms × measured seconds / expected seconds
   ```

   e.g. a loop that takes 31 s instead of 62.7 s means `--tick-ms 0.5`. (A start that stays black for a
   while is the video itself: Bad Apple starts on a black screen.)

---

## Build options

```
effects/badapple/build.py VIDEO [options]
```

| Option | Default | Effect |
|---|---|---|
| `--fps N` | 10 | frames per second stored. More fps = smoother but a shorter clip |
| `--start SEC` | 0 | start this many seconds into the video (e.g. to pick the best part) |
| `--tick-ms MS` | 1.0 | timer tick length, see above |
| `--fit stretch\|crop\|pad` | stretch | how the video is fitted to the keyboard (same as the live player) |
| `--threshold N` | 128 | grey level (0–255) from which a key is on |
| `--invert` | | light the dark parts instead |
| `--color RRGGBB` | ffffff | fallback colour, only used when the effect is set to rainbow (otherwise the colour set in the app/WebHID is used) |

How long a clip fits depends on how much the picture changes. Bad Apple, measured:

| fps | Length that fits |
|---|---|
| 10 | 62.7 s |
| 15 | 56.1 s |
| 20 | 50.8 s |

Most of the data is the moments where the picture changes, so more fps costs surprisingly little:
`--fps 20` is a lot smoother for 12 s less.

The build output tells you the exact length. Any video works; busy videos fit fewer seconds.

---

## Testing without the keyboard

```sh
python3 tests/test_badapple.py
```

Runs the player in the uCsim 8051 simulator (comes with SDCC), frame by frame through a whole loop,
and checks that the keys it lights match what build.py encoded, that colours are right and that it
doesn't write anywhere it shouldn't. Pass frame numbers to check specific frames:
`test_player.py 1 100 500`.

---

## How it works

### Where it lives

| Flash | Contents |
|---|---|
| `0xDC00` | effect header: entry jumps for init and frame handler, the chain jump, the slot number |
| `0xDC0A`– | player code (248 bytes with the header, `effects/badapple/player.asm`) |
| after the code – `0xEBFF` | the video |

`0xDC00–0xEBFF` is unused by the stock firmware (nothing reads or writes it).

### Hooks (3 patched spots)

These are the general custom-effect hooks described in [CUSTOM_EFFECTS.md](CUSTOM_EFFECTS.md); for Bad Apple:

| Address | Stock | Patched |
|---|---|---|
| `0x179C` | default of the effect-init switch (`0x175B`, `?C?CCASE` table) → `0x1B0E` | → `0xDC00` (player init; only acts for mode 6, otherwise continues to the next custom effect or `0x1B0E`) |
| `0x1B49` | frame table entry for mode 6: `LJMP 0x1DC8` (a `RET`) | `LJMP 0xDC03` (frame handler) |
| `0x4F78` | Fn "next effect": `CJNE A,#6` skips mode 6 | `CJNE A,#0xFF`, so the Fn key reaches it |

Mode 6 is a hole in the stock firmware: it has no init case, an empty frame table entry, and the Fn
key skips it (as it does 9 and 14; 18 has no code either). So the new effect doesn't replace anything.

### The player

- **Init** (when the effect is selected): sets the firmware's "run frame handler" flag (bit `0x22`, like
  every stock effect's init), resets the frame clock, makes all keys the chosen colour at level 0.
- **Frame handler** (called by the lighting engine continuously): when the tick counter
  (`0x0300/0x0301`, incremented by the timer interrupt at `0x81EF`) reaches the frame period, it
  subtracts the period and shows the next frame: it toggles the keys listed for that frame in the
  level buffer (`0x0017 + col × 6 + row`, 32 = on) and calls the firmware's own renderer `0x63E5`,
  the same one the boot animation uses.
- State: `0x0EC1` hold count, `0x0EC2/0x0EC3` read pointer (borrowed from the boot snake, which only runs
  at power-on).

### Video format

One item per frame:

| Byte(s) | Meaning |
|---|---|
| `n` (1–87), then `n` key indexes | these keys toggle (index = LED column × 6 + row) |
| `0x80 \| n` (n = 1–126) | the picture stays the same for `n` frames |
| `0xFF` | end: back to black, start over |

A frame where nothing changes costs nothing extra (it's part of a hold run); a frame costs one byte
plus one per changed key. That's why 63 s of Bad Apple fit in under 4 KB.

---

## Things to know

- **Brightness** is always full; the effect has no colour or brightness setting (set the colour at build
  time with `--color`). The speed setting is the frame-rate fine tune.
- **Tested on the keyboard:** works (wired). **Wireless / battery:** not tested yet. The effect runs in the same lighting engine as the stock
  effects, so it should run in 2.4 GHz / Bluetooth mode too.
- **Other effects** work exactly as before. The Fn effect cycle now includes effect 6.
- **Removing it:** flash the stock image (or a patch without `--badapple`).
- **Recovery:** the bootloader and the ISP entry aren't touched, so you can always flash again over USB.

---

## Files

| File | What |
|---|---|
| `effects/badapple/player.asm` | the player (8051 assembly, sdas8051 syntax) |
| `effects/badapple/build.py` | encodes the video and assembles it with the player → `effects/badapple/build/badapple.ihx` |
| `tests/test_badapple.py` | simulator test |
| `patch_firmware.py --badapple` | installs it into the firmware image (`--effect IHX` for another build) |

---

*Written with Claude Opus 5.5*
