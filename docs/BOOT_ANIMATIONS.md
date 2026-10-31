# Writing your own boot animation for the AULA F87

This guide explains how the AULA F87's power-on animation works inside the stock firmware, and how
to replace it with your own animation written in C. You don't need to know 8051 assembly. You
write one small C function, build it with SDCC, test it in a simulator, and patch it into the
firmware with `patch_firmware.py`.

> [!WARNING]
> Flashing modified firmware is at your own risk. Keep a backup of your keyboard
> (`sinowisp read -d aula-f87 --section full --format bin backup_full.bin`) and the original
> `base_f87_decrypted.bin`. Your animation only changes the boot animation, so the ISP entry
> code stays intact and you can always reflash over USB. See [Recovery](#recovery).

All addresses in this document refer to the base F87 firmware (`base_f87_decrypted.bin`,
MD5 `acc16504615d3808d646915ddb95856e`). `patch_firmware.py` refuses any other image. You can get the firmwares from [f87fw/firmware](https://github.com/tmtco1/f87fw/blob/main/firmware/base_f87_decrypted.bin).

---

## Contents

- [Quick start](#quick-start)
- [How the stock boot animation works](#how-the-stock-boot-animation-works)
- [How a custom animation is hooked in](#how-a-custom-animation-is-hooked-in)
- [The `boot_step()` contract](#the-boot_step-contract)
- [The LED buffers](#the-led-buffers)
- [Key positions](#key-positions)
- [Timing: step period and fade period](#timing-step-period-and-fade-period)
- [Rules for animation code](#rules-for-animation-code)
- [Walkthrough: `boot_fkeys.c`](#walkthrough-boot_fkeysc)
- [The other animations](#the-other-animations)
- [Building](#building)
- [Testing in the simulator](#testing-in-the-simulator)
- [Patching and flashing](#patching-and-flashing)
- [Adding your animation as a preset](#adding-your-animation-as-a-preset)
- [Pitfalls](#pitfalls)
- [Recovery](#recovery)
- [Reference](#reference)

---

## Quick start

You need Python 3, SDCC (`sudo dnf install sdcc`, `sudo apt install sdcc`, …), `sinowisp`, and the
decrypted base firmware.

```sh
cp anim/boot_fkeys.c anim/my_anim.c          # start from a working animation
$EDITOR anim/my_anim.c

anim/build.sh my_anim                        # -> anim/build/my_anim.ihx
python3 -I anim/test/sim_boot.py anim/build/my_anim.ihx 30     # check it frame by frame

python3 patch_firmware.py base_f87_decrypted.bin out.bin \
    --boot-code anim/build/my_anim.ihx --boot-step 8 --boot-fade 1
./sinowisp write -d aula-f87 --format bin out.bin
```

Then unplug and replug the keyboard to see the animation.

---

## How the stock boot animation works

The boot animation is a lighting mode of its own, **mode `0x26`**, which the firmware only uses
right after power-on.

1. **`main()` (`0x8C0B`)** sets the "booting" bit (`SETB 0x33` at `0x8C22`).
2. **On its first pass, the main loop (`0x8C80`)** sees that bit, saves your current lighting mode
   (XRAM `0x009D`) into XRAM `0x0E1B`, and switches to mode `0x26`.
3. **When mode `0x26` starts**, the lighting engine (switch at `0x175B`, case `0x26` → `0x1A16`)
   calls `0xB1B3`, which initialises four state bytes:

   | XRAM | Initial value | Stock use |
   |---|---|---|
   | `0x0EC1` | `0x00` | snake row |
   | `0x0EC2` | `0x00` | snake column |
   | `0x0EC3` | `0xFF` | snake direction |
   | `0x0EC4` | `0xFF` | "running" flag: the animation ends when it becomes `0` |

4. **Every main-loop pass**, the lighting engine runs the frame handler for the current mode
   (dispatcher at `0x1B0E`). For mode `0x26` that's **`0x1D0B`**, which does:

   ```
   if (fade_ticks >= FADE_PERIOD) {        // byte at 0x1D11, stock 5
       fade_ticks = 0;
       render_and_fade();                  // 0x63E5
   }
   if (step_ticks >= STEP_PERIOD) {        // byte at 0x1D25, stock 1
       if (RUN == 0) {                     // XRAM 0x0EC4
           restore saved mode; clear the booting bit;   // boot is over
       }
       snake_step();                       // LCALL 0x8B26 at 0x1D52  <-- the hook
       step_ticks = 0;
   }
   ```

   `fade_ticks` and `step_ticks` are counters a timer interrupt increments (`0x0978` and
   `0x0300/0x0301`).

5. **`render_and_fade()` (`0x63E5`)** walks every LED, sends `colour × level / 32` to the
   hardware, and lowers each nonzero level by 1. It's shared with other lighting modes.

6. **`snake_step()` (`0x8B26`)** lights the next key of a serpentine sweep (row 0 left to right,
   row 1 right to left, …). When the snake leaves the bottom row it sets `0x0EC4` to `0`, which
   ends the animation on the next step.

So the stock animation is a snake that lights one key per step, with a trail that fades because
`render_and_fade()` keeps dimming every key that was lit.

---

## How a custom animation is hooked in

`patch_firmware.py --boot-code` (or `--boot-anim <preset>`) makes exactly these changes:

| Address | Original | Patched | Meaning |
|---|---|---|---|
| `0x1D52` | `12 8B 26` (`LCALL 0x8B26`) | `12 EC 80` (`LCALL 0xEC80`) | call your `boot_step()` instead of the snake |
| `0xEC80–0xEDFF` | all zero | your code | 384 bytes, in the flash sector that holds the firmware's own code (`0xEC00–0xEC64`), so the firmware never erases it |
| `0x1D25` | `01` | `--boot-step` | step period |
| `0x1D11` | `05` | `--boot-fade` | fade period |

Everything else stays original:
- the timing loop
- the fading and LED output
- the end of boot mode
- the restore of your normal lighting mode

The other lighting mode that uses the snake (mode `0x0D`) still calls `0x8B26` from another place
and isn't affected.

---

## The `boot_step()` contract

Your file must define:

```c
void boot_step(void);
```

as the **first function** in the file. It's linked at `0xEC80`, and `build.sh` checks this.

**When it's called:** once every *step period* timer ticks while the keyboard is in boot mode,
plus **once more after the animation has ended**. The firmware calls the step function right
after restoring your lighting mode. Your function must do nothing when `RUN == 0`.

**What it should do:**

1. If `RUN` (`0x0EC4`) is `0`, return immediately.
2. Otherwise, update the LED buffers for this step: set colours, and set levels to light keys.
3. When the animation is finished, set `RUN = 0`. On the next step the firmware ends boot mode and
   restores the user's lighting.

> [!IMPORTANT]
> Your animation **must** set `RUN = 0` eventually. If it never does, the keyboard stays in boot
> mode until the next power cycle. Your normal lighting never comes back, and the parts of the
> firmware that check the booting bit (several lighting routines and the battery-level logic) keep
> behaving as if the keyboard had just been switched on.

**State you can use:** the four snake bytes belong to you during boot. They're initialised before
your first call. In the stock firmware they're only used by the boot frame handler (`0x1D0B`),
its init (`0xB1B3`) and the snake step (`0x8B26`), so nothing else touches them while boot mode
runs.

| XRAM | Initial value | Suggested use |
|---|---|---|
| `0x0EC1` | `0x00` | free (e.g. second counter, direction, phase) |
| `0x0EC2` | `0x00` | `POS`: step counter |
| `0x0EC3` | `0xFF` | free |
| `0x0EC4` | `0xFF` | `RUN`: set to `0` to finish |

Use them through a macro that dereferences a fixed XRAM address:

```c
#define XB(a)  (*(volatile __xdata unsigned char *)(a))
#define POS    XB(0x0EC2)
#define RUN    XB(0x0EC4)
```

You get no other RAM. See [Rules](#rules-for-animation-code).

---

## The LED buffers

Two buffers in XRAM describe every LED. The renderer reads them every *fade period*. LED
positions are a grid of **17 columns × 6 rows**, stored column-major (`[column][row]`):

| Buffer | Address of LED (col, row) | Size | Contents |
|---|---|---|---|
| Colour | `0x0424 + col*18 + row*3` | 3 bytes | R, G, B (0–255 each) |
| Level | `0x0017 + col*6 + row` | 1 byte | brightness 0–32 (`0x20` = full) |

The renderer does this each time it runs:

```
for every LED (col 0..16, row 0..5):
    output = colour * level / 32      (per channel)
    send output to the LED
    if level > 0: level -= 1
```

What that means for your animation:
- **To light a key**, write its colour, then set its level to `0x20`.
- **A lit key fades out by itself.** It goes from full to off in 32 renderer runs, i.e. 32 × fade
  period ticks.
- **To keep a key steady**, set its level back to `0x20` every step. It loses some brightness
  between steps, so this only looks steady if the step period is short compared to the fade.
- **To turn a key off immediately**, set its level to `0`.
- **Unlit keys stay dark.** The firmware clears XRAM at reset, so every level starts at 0.

> [!NOTE]
> The final output may also be scaled by the user's brightness setting, so "full white" means the
> brightest the renderer will produce.

---

## Key positions

The AULA F87 is an **ANSI** tenkeyless board with 87 keys (checked against a photo of the
keyboard). The firmware's grid also has positions for ISO keys (`#`, the extra `\` next to left
Shift, Int1) that don't exist on this board. For rows 0–3 and 5, LED positions match the keymap
grid:

| Row \ Col | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **0** | Esc | – | F1 | F2 | F3 | F4 | F5 | F6 | F7 | F8 | F9 | F10 | F11 | F12 | PrtSc | ScrLk | Pause |
| **1** | `` ` `` | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 0 | - | = | Bksp | Ins | Home | PgUp |
| **2** | Tab | Q | W | E | R | T | Y | U | I | O | P | [ | ] | \ | Del | End | PgDn |
| **3** | Caps | A | S | D | F | G | H | J | K | L | ; | ' | – | Enter | – | – | – |
| **4** | LShift | *see below* | | | | | | | | | | | | | – | Up | – |
| **5** | LCtrl | Win | LAlt | – | – | Space | – | – | RAlt | Fn | Code (Menu) | – | – | RCtrl | Left | Down | Right |

**Row 4 (Shift row) is remapped.** The stock snake converts keymap positions to LED positions
with two tables in flash:
- `0x2B5F + row*21 + col`: LED column
- `0x2BDD + row*21 + col`: LED row

Both are identity for every row except row 4, where the keymap columns 1–13
(Z X C V B N M , . / Int1 ISO\ RShift) map to LED columns
`12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13`. Int1 and ISO\ don't exist on the F87, so in LED
columns the Shift row reads:

| LED col | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **row 4** | LShift | X | C | V | B | N | M | , | . | / | – | – | Z | RShift | – | Up | – |

This is the firmware's own mapping, and it's verified on a real F87: `live/stream_video.py --test`
lights every key in LED order and each one matched its name. If you
light Shift-row keys individually, look up the LED column the way the stock firmware does, with a
macro that reads the firmware's own table:

```c
/* keymap (row, col) -> LED column. row * 21 is at most 105, so it fits in a byte. */
#define LED_COL(row, col)  (*((__code const unsigned char *)0x2B5F + (unsigned char)((row) * 21) + (col)))

c   = LED_COL(4, pos + 1);          /* Shift-row key number pos+1 */
off = c * 6 + 4;
XB(LEVEL_BUF + off) = 0x20;
```

Use a macro rather than a helper function. In SDCC's default model, a function's second and later
parameters are passed in RAM, which `build.sh` rejects. Helper functions with no parameters, or
one, are fine, but they must be defined **after** `boot_step()` (with a prototype above it),
because `boot_step()` has to stay the first function in the file.

When you test code like this in the simulator, pass `--firmware base_f87_decrypted.bin` so the
table reads return the real data. See [Testing](#testing-in-the-simulator).

Positions marked `–` have no key, but writing to them is harmless.

---

## Timing: step period and fade period

Both are in timer ticks, set by `patch_firmware.py`:

| Option | Byte | Stock | Meaning |
|---|---|---|---|
| `--boot-step N` | `0x1D25` | 1 | `boot_step()` is called every N ticks |
| `--boot-fade N` | `0x1D11` | 5 | the renderer runs (and dims every lit key by 1/32) every N ticks |

Useful relationships:

- **Fade-out time** of a key lit at full: `32 × fade` ticks.
- **Trail length** (a moving light, one new key per step): about `32 × fade ÷ step` keys.
- **Total duration**: `(number of steps) × step` ticks.
- **Tail**: after your last key, keep counting for at least `32 × fade ÷ step` more steps before
  setting `RUN = 0`, or the trail is cut off when the user's normal lighting takes over.

| Look | step | fade |
|---|---|---|
| Fast running light, short trail (`fkeys` preset) | 8 | 1 |
| 2× slower, same trail | 16 | 2 |
| Comet with a long trail | 4 | 2 |
| Keys pop on and fade slowly | 8 | 4 |

The real tick length hasn't been measured. Start from these values and adjust by eye. Both
options accept 1–255.

> [!TIP]
> Fade 1 makes the renderer run on every tick. That's fine for a short boot animation, but if the
> keyboard ever feels sluggish at power-on, double both values (same look, half the renderer work).

---

## Rules for animation code

Your code runs inside firmware built with a different compiler (Keil C51), so it has to stay out
of its way. `build.sh` enforces the first two rules and refuses to build otherwise.

1. **No RAM of your own.** No global variables, no `static` variables, and no local variables
   that SDCC spills to memory. Locals must fit in registers: keep functions small, with a handful
   of `unsigned char` locals. The firmware already uses all internal RAM, and any SDCC data
   segment would overwrite its variables. Use the XRAM state bytes above for anything that must
   survive between calls.
2. **No library calls.** SDCC implements `int` multiplication, division and `%`, plus `long` and
   float maths, with runtime routines (`__mulint`, `__divuchar`, …), which aren't linked in. Stick
   to `unsigned char` arithmetic, and **always store a byte product in an `unsigned char` variable
   before adding it to an address**:

   ```c
   off = col * 6 + row;             /* OK: byte maths, a single MUL AB */
   XB(LEVEL_BUF + off) = 0x20;

   XB(LEVEL_BUF + col * 6) = 0x20;  /* NO: mixed with the int constant -> __mulint */
   ```

   Calls to functions defined in your own file are fine.
3. **Constant tables are fine.** Mark them `__code const` and they're stored in flash right after
   your code. You can also *read* the firmware's own tables, such as the colour wheel at `0x279C`
   (192 RGB entries).
4. **Don't call firmware functions.** Their register conventions are Keil's and undocumented, so
   only write to the LED buffers and the state bytes.
5. **Return quickly.** The same main loop scans the keys and services USB. No delay loops: use the
   step period and a step counter instead.
6. **Stay in 384 bytes** (`0xEC80–0xEDFF`, code plus tables). `build.sh` prints how much is left.
7. **Registers:** SDCC may use A, B, DPTR, R0–R7 and the flags freely. The stock snake step
   clobbers the same registers, so the caller expects it. Don't change the register bank or
   enable or disable interrupts.

---

## Walkthrough: `boot_fkeys.c`

`anim/boot_fkeys.c` is the shipped animation: a full-white light running across F1–F12.

```c
void boot_step(void)
{
    unsigned char pos, col, off;
    volatile __xdata unsigned char *p;

    if (RUN == 0)                       /* 1. also called once after the end: do nothing */
        return;

    pos = POS;
    if (pos >= NKEYS + TAIL_STEPS) {    /* 2. after the tail: tell the firmware we're done */
        RUN = 0;
        return;
    }
    POS = pos + 1;
    if (pos >= NKEYS)                   /* 3. tail steps: let the last keys fade out */
        return;

    col = FIRST_COL + pos;              /* 4. F1 is column 2, so F1..F12 = columns 2..13 */

    off = col * 18 + ROW * 3;           /*    col <= 13 -> at most 234, fits in a byte */
    p = (volatile __xdata unsigned char *)(COLOUR_BUF + off);
    p[0] = R_VAL;  p[1] = G_VAL;  p[2] = B_VAL;   /* 5. colour: white */

    off = col * 6 + ROW;
    XB(LEVEL_BUF + off) = FULL;         /* 6. level 32: lit at full brightness */
}
```

**One run, step by step:**

1. **Steps 0–11:** each step lights the next F-key at full white.
2. **Fading:** between steps, the renderer dims every lit key, which forms the trail.
3. **Steps 12–17:** tail steps (`TAIL_STEPS = 6`). Nothing new is lit, so the trail can fade.
4. **Step 18:** sets `RUN = 0`, and on the next step the firmware restores the user's lighting.

The constants (`FIRST_COL`, `NKEYS`, `TAIL_STEPS`, `ROW`, `R_VAL`, `G_VAL`, `B_VAL`) are wrapped in
`#ifndef`, so you can change them at build time without editing the file:

```sh
anim/build.sh boot_fkeys -DR_VAL=0 -DG_VAL=0x80 -DB_VAL=0xFF     # light blue instead of white
anim/build.sh boot_fkeys -DROW=1 -DFIRST_COL=1 -DNKEYS=12        # run across 1 .. = instead
```

---

## The other animations

Every file in `anim/` is a complete animation you can build, flash or copy as a starting point.
Besides `boot_fkeys.c` there are three more, and all of them pass the build checks and the simulator.

### `wipe.c`: whole-keyboard wipe

Lights a full column (all 6 rows) white per step, from the Esc column to the Pause column. It also
shows how to handle columns ≥ 15, where `col * 18` no longer fits in a byte. It builds the
pointer in two byte-sized steps:

```c
off = pos * 9;                       /* <= 144: byte-sized, single MUL */
col_colours = (volatile __xdata unsigned char *)COLOUR_BUF;
col_colours += off;
col_colours += off;                  /* = COLOUR_BUF + pos * 18, done in 16 bits */
```

Preset: `--boot-anim wipe` (step 6, fade 2).

### `rainbow_frow.c`: a different colour per key

Same sweep as `boot_fkeys.c`, with colours taken from a `__code const` table, red through magenta:

```c
static __code const unsigned char colours[NKEYS * 3] = { 0xFF,0x00,0x00,  0xFF,0x40,0x00, ... };
...
c = pos * 3;
XB(COLOUR_BUF + off + 0) = colours[c + 0];
```

Preset: `--boot-anim rainbow_frow` (step 8, fade 1).

### `tmtco.c`: letters, then a ripple

T, M, T, C and O light up one after another, each fading out by itself (so the second T flashes
again). Then a ripple of rings spreads out from O across the whole keyboard. It shows three
techniques that keep a bigger animation inside the code area and the 8051's eight registers:

- **Paint the colours once.** On the first call the whole colour buffer gets the colour; after
  that only levels change.
- **Use the level buffer as one array.** It's 102 bytes in a row, so a single byte index
  `col * 6 + row` reaches every LED. No pointers, no multiplies.
- **Precompute instead of calculating.** Each LED's distance from O is in a 102-byte `__code`
  table, so drawing a ring is one compare per LED. Edit the table to change the ripple's shape or
  centre. On the Shift row, distances are measured from each key's real (keymap) position, not
  its remapped LED column.

It also shows three timing tricks:

- **A countdown for different speeds.** A second state byte (`0x0EC1`) counts down calls, so
  letters and rings can be spaced by a different number of steps (`LETTER_GAP`, `RING_GAP`)
  while the step period stays the same.
- **Your own extra fading.** The firmware's fade is one setting for the whole animation. To make
  the ripple fade faster than the letters, every ring step halves the level of everything inside
  the current ring (`LEVEL_BUF[i] >>= 1`). The wave front stays bright and the inside dies away
  within a few rings.
- **A clean ending.** After the last ring, every level is set to 0, so the renderer sends black.
  The animation stays dark for `BLACK_GAP` calls, and only then sets `RUN = 0`, so the user's
  lighting starts from a dark keyboard.

Build-time settings: `LETTER_GAP` (10), `RING_GAP` (3), `TAIL_RINGS` (4), `BLACK_GAP` (20) and
`COLOUR_R/G/B` (white), e.g. `anim/build.sh tmtco -DRING_GAP=2 -DBLACK_GAP=30`.

Preset: `--boot-anim tmtco` (step 4, fade 2): about four times as long as the stock snake.

### Ideas

- **Bounce:** run F1 → F12 → F1, using `0x0EC1` as the direction.
- **Fill and hold:** light keys without letting them fade by setting their levels back to `0x20`
  each step, then release them all at the end.
- **Ripple:** light keys by their distance from a centre key, one ring per step.
- **Text:** a `__code` table of (col, row) pairs, one entry per step.
- **Rainbow:** read colours from the firmware's colour wheel (192 RGB entries at `0x279C`) through
  a `__code` pointer. `3 * index` only fits in a byte for index ≤ 85, so either stay in that range
  or add it to the pointer in byte-sized steps, as `wipe.c` does.

---

## Building

```sh
anim/build.sh                          # builds anim/boot_fkeys.c
anim/build.sh my_anim                  # builds anim/my_anim.c
anim/build.sh wipe                     # builds anim/wipe.c
anim/build.sh path/to/other.c          # paths are relative to anim/
anim/build.sh my_anim -DNKEYS=6        # extra arguments go to sdcc
```

Output goes to `anim/build/<name>.ihx` (plus `.asm`, `.lst`, `.map` and `.sym` for inspection).
`build.sh`:

1. compiles with `sdcc -mmcs51 --model-small --opt-code-size`
2. rejects code that uses RAM (`DSEG/OSEG/ISEG/BSEG/XSEG/...` symbols)
3. rejects calls to library or runtime routines
4. links without SDCC's startup code, with code at `0xEC80` and constants right after it
5. checks that `boot_step` is at `0xEC80` and that everything ends before `0xEE00`

On Fedora the tools are installed as `sdcc-sdcc` / `sdcc-sdld`; `build.sh` finds either name.

To see what the compiler produced, read `anim/build/<name>.asm`.

---

## Testing in the simulator

`anim/test/sim_boot.py` runs your blob in uCsim (the 8051 simulator that comes with SDCC). For
every frame count N it:

1. clears XRAM
2. sets the state bytes the way `0xB1B3` does
3. calls `boot_step()` N times
4. prints which LEDs are lit, in which colour, and the values of `POS` / `RUN`

```sh
python3 -I anim/test/sim_boot.py anim/build/my_anim.ihx 30

# if your code reads firmware tables (LED_COL, the colour wheel, ...), load the firmware underneath:
python3 -I anim/test/sim_boot.py anim/build/my_anim.ihx 30 --firmware base_f87_decrypted.bin
```

Keys are printed by name. Positions with no key name, and the remapped Shift row, are printed as
`(col,row)`.

```
after  0 frames: POS= 0 RUN=0xff  lit: -
after  1 frames: POS= 1 RUN=0xff  lit: F1
after  2 frames: POS= 2 RUN=0xff  lit: F1, F2
...
after 19 frames: POS=18 RUN=0x00  lit: F1, F2, ..., F12
```

What to check:
- **The right keys light up**, in the right order.
- **Colours:** keys that aren't white show their `rgb (...)` value.
- **`RUN` reaches `0x00`** after the number of frames you expect.
- **No `STRAY WRITES`:** that warning means your code wrote XRAM outside the LED buffers and its
  state bytes.

What the simulator doesn't show:
- **Fading:** the renderer is part of the firmware, not your blob, so lit keys stay lit in the
  output.
- **Real timing.** Judge speed and trail on the keyboard itself.

---

## Patching and flashing

```sh
python3 patch_firmware.py base_f87_decrypted.bin out.bin \
    --boot-code anim/build/my_anim.ihx --boot-step 8 --boot-fade 1
```

You can combine this with the other options (`--product`, `--manufacturer`, `--bt-name`, …).

Before patching, the patcher checks that:
- the input is the known image
- every byte it changes still has its expected original value
- the code area is empty and your code fits in `0xEC80–0xEDFF`

It prints exactly what it changed.

Flash the **patched** file, by cable, with the keyboard's switch on USB:

```sh
./sinowisp write -d aula-f87 --format bin out.bin
```

Then unplug and replug the keyboard (or switch it off and on) to run the boot animation.

---

## Adding your animation as a preset

Every animation in `anim/` is available as a preset with its own default timing:

| Preset | File | step | fade |
|---|---|---|---|
| `fkeys` | `anim/boot_fkeys.c` | 8 | 1 |
| `wipe` | `anim/wipe.c` | 6 | 2 |
| `rainbow_frow` | `anim/rainbow_frow.c` | 8 | 1 |
| `tmtco` | `anim/tmtco.c` | 4 | 2 |

```sh
anim/build.sh wipe
python3 patch_firmware.py base_f87_decrypted.bin out.bin --boot-anim wipe
```

To add your own, put an entry in `BOOT_ANIMS` in `patch_firmware.py`:

```python
BOOT_ANIMS = {
    ...
    "my_anim": {"ihx": "anim/build/my_anim.ihx", "step": 8, "fade": 1,
                "about": "what it looks like, shown in --help"},
}
```

`--boot-step` and `--boot-fade` given on the command line still override the preset.

---

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `error: ... uses RAM variables` | a global/static variable, or too many locals | use the XRAM state bytes, and reduce or reuse locals |
| `error: ... calls library/runtime routines it can't use: __mulint` | `int` arithmetic: a product used directly in an address expression is promoted to `int` | store the product in an `unsigned char` first: `off = pos * 9; p += off;` |
| `error: ... uses RAM variables` right after adding a helper function | the helper has two or more parameters (passed in RAM) | use a macro, or pass at most one parameter |
| Simulator shows `STRAY WRITES` after reading a firmware table | the simulator's flash is empty without `--firmware` | add `--firmware base_f87_decrypted.bin` |
| Some keys stay black (often PrtSc/ScrLk/Pause) | `col * 18` overflowed a byte (col ≥ 15) | build the pointer in byte-sized steps (see `wipe.c`) |
| `boot_step must be the first function` | a helper is defined above `boot_step()` | put a prototype above, define helpers below |
| Animation cut off at the end | `RUN = 0` set too early | add tail steps: at least `32 × fade ÷ step` |
| Animation never ends, lighting stuck | `RUN` never set to 0 | always end with `RUN = 0` |
| Still the stock snake after flashing | flashed `base_f87_decrypted.bin` instead of `out.bin`, or didn't power-cycle | flash `out.bin`, replug |
| Keyboard sluggish at power-on | fade period 1 runs the renderer every tick | double both step and fade |

---

## Recovery

- **The ISP entry stays intact.** The bootloader (`0xF000–0xFFFF`) runs on every reset, and the
  firmware's "enter ISP" handler (feature report `05 75` → `0xEC18`) isn't touched by any of these
  patches. If an animation looks wrong, flash the original back:

  ```sh
  ./sinowisp write -d aula-f87 --format bin base_f87_decrypted.bin
  ```

- **If the firmware can't run at all** (it can't reach the ISP command over USB), recovery needs a
  hardware programmer on the chip's P0.0/P0.1 debug pins. A boot animation that follows the rules
  above can't cause that, but keep it in mind before patching other parts of the firmware.

---

## Reference

### Patched locations

| Address | Bytes | Description |
|---|---|---|
| `0x1D11` | `94 05` (`SUBB A,#5`) | fade period immediate |
| `0x1D25` | `94 01` (`SUBB A,#1`) | step period immediate |
| `0x1D52` | `12 8B 26` (`LCALL 0x8B26`) | step call, retargeted to `0xEC80` |
| `0x8C22` | `D2 33` (`SETB 0x33`) | booting bit (`--no-boot-anim` turns it into `CLR 0x33`) |
| `0xEC80–0xEDFF` | zero | custom animation code and tables |

### Firmware routines involved

| Address | Role |
|---|---|
| `0x8C0B` | `main()`: sets the booting bit |
| `0x8C80` | main loop: saves the user's mode, switches to mode `0x26` |
| `0x175B` | lighting-mode switch (start of a mode) |
| `0xB1B3` | boot-mode init: sets `0x0EC1–0x0EC4` |
| `0x1B0E` | per-frame dispatcher by running mode (`0x0892`) |
| `0x1D0B` | boot-mode frame handler: timing, fade, end condition, step call |
| `0x63E5` | renderer: output `colour × level / 32`, then fade by 1 |
| `0x8B26` | stock snake step (also used by lighting mode `0x0D`) |
| `0x465E` | stock "light one key" routine (uses the mode's colour settings) |

### Data

| Address | Space | Description |
|---|---|---|
| `0x0017` | XRAM | level buffer, 17 × 6 bytes, `[col][row]`, 0–32 |
| `0x0424` | XRAM | colour buffer, 17 × 6 × RGB, `[col][row]` |
| `0x0EC1–0x0EC4` | XRAM | boot animation state (see [contract](#the-boot_step-contract)) |
| `0x009D` | XRAM | current lighting mode (`0x26` during boot) |
| `0x0E1B` | XRAM | the user's mode, restored when boot ends |
| `0x2B5F` | flash | keymap (row, col) → LED column, 6 × 21 |
| `0x2BDD` | flash | keymap (row, col) → LED row, 6 × 21 |
| `0x279C` | flash | colour wheel, 192 × RGB |

---

*Written with Claude Opus 5.5*
