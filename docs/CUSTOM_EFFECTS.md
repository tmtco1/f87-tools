# Custom lighting effects: how Bad Apple and Game of Life got into the firmware

The AULA F87 firmware has a fixed set of lighting effects. This document explains how two new ones
were added to the stock firmware without removing anything:

- **Bad Apple** (effect 6): a video stored in the keyboard's flash, played on the keys
  ([BADAPPLE.md](BADAPPLE.md) for usage)
- **Game of Life** (effect 9): Conway's Game of Life with the keys as cells

It covers what had to be found out about the firmware, the design decisions, how both were tested
before touching the keyboard, and how to write your own effect in the same way.

```sh
python3 effects/badapple/build.py tools/live/badapple.mp4
python3 effects/life/build.py
python3 tools/patch_firmware.py base_f87_decrypted.bin out.bin --badapple --life
./sinowisp write -d aula-f87 --format bin out.bin
python3 tools/aulaf87.py effect badapple      # or: effect life, or the Fn effect key
```

---

## 1. Starting point

From earlier work (boot animations, live lighting) we already knew:

- the firmware is Keil C51 code for an 8051-type Sinowealth chip, decompiled with Ghidra (`decomp/`)
- the key LEDs are driven from two XRAM buffers: **colour** at `0x0424 + (col × 6 + row) × 3` (R, G, B)
  and **level** at `0x0017 + col × 6 + row` (0–32), in LED coordinates, 17 columns × 6 rows
- the renderer at `0x63E5` shows `colour × level / 32` for every key and then decrements every
  non-zero level (that's what makes boot-animation trails fade)
- the Shift row is wired in a different order (Z sits at LED column 12)
- `0xDC00–0xEBFF` (4 KB) and `0xEE00–0xEFFA` are unused flash

Streaming Bad Apple from the PC already worked ([LIVE_LIGHTING.md](LIVE_LIGHTING.md)). The goal now:
play it with no PC, as an effect you can select like any other.

## 2. Does a video even fit?

Before writing any firmware code, we measured. Each key of the 87 is sampled from the video
(the same sampling as the live player) and reduced to on/off. Then each frame is stored as only the
keys that changed since the previous frame, and runs of unchanged frames as one byte.

| | Full Bad Apple (3:39) |
|---|---|
| 30 fps | 18.6 KB |
| 10 fps | 11.9 KB |

So 1-bit is the way to go (4 grey levels would need 34–67 KB), and the free 4 KB holds about a
minute. That was "option 1": keep every stock effect, and play a 63 s loop. (The full video would
need deleting stock effects to make room.)

## 3. Finding how effects run

Following the boot animation's frame handler (`0x1D0B`) backwards to its caller led to the lighting
engine's two-stage dispatch:

**Stage 1, init** (`0x175B`): a `?C?CCASE` switch (Keil's inline switch table) on the current mode
`0x0EC7`. When the mode has just changed (bit `0x21` set), each case runs that effect's setup and sets
bit `0x22`, "run the frame handler". Modes without a case go to the table's **default, `0x1B0E`**,
which is a 2-byte address stored in the table at `0x179C`.

**Stage 2, frame** (`0x1B14`): if bit `0x22` is set, jump through a table of `LJMP`s at **`0x1B37`**,
one per mode 0–17 (`0x1B37 + 3 × mode`). Every frame handler looks the same: compare the tick counter
(`0x0300`/`0x0301`, incremented by the timer interrupt at `0x81EF`) with the effect's period, and when
it's reached, reset it and draw the next step.

Then the interesting part. The table entries for **modes 6, 9 and 14 are `LJMP 0x1DC8`, which is just
a `RET`**, and the init switch has no case for them either. And the Fn "next effect" code at `0x4F71`
explicitly skips them:

```
4f78: CJNE A,#0x6,...   ; if mode == 6: mode++
4f82: CJNE A,#0x9,...   ; if mode == 9: mode++
4f8c: CJNE A,#0xe,...   ; if mode == 14: mode++
```

So the vendor's app lists 19 effects, but on the F87 three of them (and 18) are empty slots, which
you confirmed on the keyboard. That gave us **free effect slots that need no new dispatch code**.

## 4. The hooks

Three small patches per effect, all of them replacing a "do nothing" path:

| Where | Stock | Patched |
|---|---|---|
| `0x179C` | init switch default → `0x1B0E` | → the custom effect's init. It checks the mode; if it isn't its own, it continues to the next custom effect's init, and the last one continues to `0x1B0E`. So stock modes behave exactly as before |
| `0x1B37 + 3 × mode` | `LJMP 0x1DC8` (RET) | `LJMP` to the effect's frame handler |
| Fn skip for the mode | `CJNE A,#mode` | `CJNE A,#0xFF`, so the Fn key no longer skips it |

Each custom effect starts with the same **10-byte header**, so the patcher can install any number of them
and chain them:

| Offset | Contents |
|---|---|
| +0 | `LJMP init` |
| +3 | `LJMP frame` |
| +6 | `LJMP 0x1B0E`: "next", which the patcher points at the next effect's init |
| +9 | the slot (mode) it's for: 6, 9 or 14 |

The init does what every stock init case does: `CLR 0x21`, `SETB 0x22`, `CLR 0x32`, `CLR 0x55`, plus its
own setup. The frame handler uses the same timing pattern as the stock handlers, but **subtracts** the
period instead of zeroing the counter, so late calls don't make playback drift.

Drawing reuses the firmware itself: write levels (and colours), call `0x63E5`. The effect's speed
setting (`0x0D94`, 0–4, from the Fn speed keys or the app) selects one of five periods, so the speed
keys work as you'd expect.

## 5. Bad Apple

**Player** (`effects/badapple/player.asm`, 248 bytes including the header, flash `0xDC00`), then the video up to
`0xEBFF`:

| Video byte(s) | Meaning |
|---|---|
| `n` (1–87) + `n` key indexes | toggle those keys (index = LED col × 6 + row) |
| `0x80 \| n` | show the same picture for `n` frames |
| `0xFF` | end: back to black, start over |

Each frame toggles levels between 0 and 32, then sets every lit key back to 32 (the renderer
decremented them to 31), then renders. The keys themselves are the frame buffer, so no extra RAM is
needed. The only state is 3 bytes (`0x0EC1` hold count, `0x0EC2/3` read pointer), borrowed from the
boot snake, which only runs at power-on.

**Encoder** (`effects/badapple/build.py`): ffmpeg decodes the video, each key averages its own area (physical
layout, Shift-row remap included), then threshold and diff, and it stops when the flash is full. It
assembles the player with SDCC's `sdas8051` and appends the data.

Result: 627 frames = 62.7 s at 10 fps in 3837 bytes (50.8 s at 20 fps). **Confirmed working on the
keyboard.**

## 6. Game of Life

`effects/life/life.asm`, 437 bytes at `0xEE40–0xEFF4`.

**Cells are the keys in their physical positions** (firmware matrix columns 0–16 × rows 0–5). Positions
without a key are always dead, from a 13-byte key mask generated from the photo-verified layout.
Neighbours are computed physically, so a glider crossing the Shift row moves correctly even though
the LEDs there are wired in a different order: the `lookup` routine maps physical position → LED
level byte (physical 1 → LED 12, 2–12 → LED 1–11 on the Shift row).

**No extra RAM: the board is the level buffer.** A generation is two passes:

1. For every key cell, count the live cells in its 3×3 block, itself included. A total of 3 means
   alive next, 4 means it keeps its state, anything else means dead. (This is the same as Conway's
   B3/S23 rule, without having to exclude the cell itself.) "Alive next" is stored in **bit 7** of the
   level byte. The counts mask bit 7 off, so pass 1 still reads the current generation.
2. Commit: bit 7 → level 32, else 0. Note whether anything changed. Render.

**Restarts:** a new random board after 200 generations (`--max-gens`), or 8 generations (`--still`)
after the board stopped changing (still life or all dead). The random generator is a 16-bit Galois
LFSR seeded from the tick counter when you select the effect, kept in `0x0EC2/3`. The default density
is 38 % of keys alive.

**Colour:** read at run time from the effect's palette slot (config byte low nibble, palette in flash `0xC800 + 21 × id`), the same colour the app/WebHID sets. It is applied when the effect starts and at each restart; rainbow uses slot 0.

**Speed:** 250 ms per generation at the middle speed. Speed 0–4 = 500, 375, 250, 175 and 125 ms.

**Fitting it:** the first version was 402 bytes, 23 more than `0xEE80–0xEFFA` (379 bytes) holds. Rather than
cutting features, it starts at `0xEE40`. The patcher keeps the USB names (`0xEE00–`) below whichever
effect is there and refuses names that don't fit (64 bytes with `--life`).

## 7. Testing before flashing

Neither effect was flashed before it passed in the **uCsim** 8051 simulator (comes with SDCC). The test
scripts build a small program that does what the firmware does: set the mode, set bit `0x21`, call the
init, then repeatedly set the tick counter and call the frame handler. The renderer is replaced by
a stub that only decrements lit levels, like the real one.

- `tests/test_badapple.py`: after frame N, the lit keys must equal what the encoder says frame N
  shows. Checked at every 7th frame through a full loop and the wrap back to black. Colours right,
  no writes outside the buffers and the 3 state bytes.
- `tests/test_life.py`: a Python model of the same rules (same LFSR, same restarts) runs next to
  the simulator. After generation N the board, the generation counter and the random state must
  match exactly. Checked with three seeds, past several restarts.
- The chained init was simulated on a complete patched image: mode 6 starts Bad Apple, mode 9 passes
  through Bad Apple's init and starts Life, and a stock mode (7) passes through both untouched.

Two bugs found this way were in the test harnesses, not the effects. Life uses R0/R1, which the
first harness used as its loop counter. And uCsim echoes `set memory`, which looked like stray
writes. Keil code doesn't keep values in registers across calls, so an effect may use R0–R7 freely.

## 8. Writing your own effect

1. Copy `effects/life/life.asm` (the shorter template) and keep the 10-byte header. Set `OURMODE` to a free
   slot (6, 9 or 14) and `.org` to free flash: `0xDC00–0xEBFF` (unless Bad Apple is installed),
   `0xEE00–0xEFFA` (shared with the USB names; not under Life).
2. **Init**: act only when `MODE == OURMODE` and bit `0x21` is set; do the four bit operations; set up
   colours and levels; always end with `LJMP next`.
3. **Frame**: wait for the tick counter to reach your period, subtract it, change levels/colours,
   `LJMP 0x63E5`.
4. **Rules**: the code is called from inside the stock firmware, so:
   - no RAM of your own; borrow XRAM `0x0EC1–0x0EC4` (boot-snake state) or use the buffers themselves
   - registers R0–R7, A, B, DPTR are free; leave the stack balanced; no interrupts
   - keep each frame short (the boot animation guide's timing notes apply; the renderer is the
     expensive part)
5. Assemble (`sdcc-sdas8051 -plosgff x.asm` and `sdcc-sdld -n -i x.ihx x.rel`, or adapt `effects/life/build.py`),
   test in uCsim like `tests/test_life.py`, then install with `patch_firmware.py --effect x.ihx`.

Effect slot 14 is still free.

## 9. Reference

| Address | What |
|---|---|
| `0x0017 + col*6 + row` | key level 0–32 (LED coordinates) |
| `0x0424 + (col*6+row)*3` | key colour R, G, B |
| `0x0300/0x0301` | tick counter hi/lo (timer interrupt `0x81EF`, vector `0x63`); tick ≈ 1 ms, assumed from the stock effects' timing tables, not measured |
| `0x0D94` | current effect speed 0–4 (0 = slow) |
| `0x0EC7`, `0x0892` | current mode (init switch / frame dispatch) |
| bits `0x21` / `0x22` | "mode just changed" / "run the frame handler" |
| `0x175B` | effect init switch (`?C?CCASE`), default address at `0x179C` |
| `0x1B37` | frame jump table, 3 bytes per mode 0–17 |
| `0x1DC8` | `RET` (what the empty slots jump to) |
| `0x4F71` | Fn "next effect", skips 6 / 9 / 14 at `0x4F78` / `0x4F82` / `0x4F8C` |
| `0x63E5` | renderer: colour × level / 32 for every key, then decrements levels |

| File | What |
|---|---|
| `effects/badapple/player.asm`, `build.py`, `test_player.py` | Bad Apple player, encoder/builder, simulator test |
| `effects/life/life.asm`, `build.py`, `test_life.py` | Game of Life, builder, simulator test against a Python model |
| `patch_firmware.py --badapple --life --effect IHX` | installs and chains effects |

---

*Written with Claude Opus 5.5*
