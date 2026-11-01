# Firmware patcher: `patch_firmware.py`

Patches the AULA F87 base firmware (`base_f87_decrypted.bin`) to change.
You can get the firmwares from [f87fw/firmware](https://github.com/tmtco1/f87fw/blob/main/firmware/base_f87_decrypted.bin).

- the **USB names** (manufacturer and product, as shown by `lsusb`, Windows device manager, etc.)
- the **Bluetooth names** (BT 3.0 and BT 5.0 slots)
- the **boot animation** (the power-on snake): disable it, change its speed, or replace it with
  one of the bundled animations or your own code
- new **lighting effects**: Bad Apple (a video stored in flash) and Conway's Game of Life
  ([CUSTOM_EFFECTS.md](CUSTOM_EFFECTS.md))

It changes only a few bytes, checks each one first, and doesn't touch the bootloader or the ISP
entry, so you can always flash the original back.

---

## Quick start

```sh
python3 tools/patch_firmware.py base_f87_decrypted.bin out.bin \
    --product "My Keyboard" --bt-name "MyKB" --boot-anim fkeys
./sinowisp write -d aula-f87 --format bin out.bin
```

Then replug the keyboard (or switch it off and on).

> Flash **`out.bin`**, not `base_f87_decrypted.bin`. Flashing the input file gives you the stock
> firmware again.

---

## Input image

The patcher only works on one image: the decrypted base F87 firmware, 61440 bytes,
MD5 `acc16504615d3808d646915ddb95856e`.

```sh
md5sum base_f87_decrypted.bin
```

A different image (another model, another firmware version) is refused, because the patch offsets
belong to this exact build. `--force` skips the hash check, but every patched byte is still checked
against its expected original value. If any of them differs, the patcher stops before writing
anything. The firmware image isn't part of this repo.

---

## Options

```
tools/patch_firmware.py IN.bin OUT.bin [options]
```

At least one option is needed; with none, the patcher exits with "nothing to change".

### USB names

| Option | Original | Limit |
|---|---|---|
| `--manufacturer S` | `BY Tech` | any Unicode text |
| `--product S` | `Gaming Keyboard` | any Unicode text |

Both strings together must fit in 256 bytes (each takes 2 + 2 × length bytes, so roughly 60
characters each is fine).

```sh
python3 tools/patch_firmware.py base_f87_decrypted.bin out.bin --manufacturer "AULA" --product "F87 Custom"
lsusb | grep 258a     # after flashing and replugging
```

The USB IDs (`258a:010c`) don't change, so the vendor app and the other tools in this repo still
find the keyboard.

### Bluetooth names

| Option | Original | Limit |
|---|---|---|
| `--bt-name S` | sets both names | 1–13 ASCII characters |
| `--bt3-name S` | `AULA-F87 3.0 ` | 1–13 ASCII characters |
| `--bt5-name S` | `AULA-F87 5.0 ` | 1–13 ASCII characters |

`--bt3-name` and `--bt5-name` override `--bt-name` for their slot. The keyboard sends the name to
its radio module, so after flashing:

- remove the old pairing on your PC / phone
- pair again (the new name shows up in the device list)

### Boot animation

| Option | Effect |
|---|---|
| `--no-boot-anim` | no power-on animation at all; normal lighting starts right away |
| `--boot-step N` | ticks between animation steps, 1–255 (stock 1; bigger = slower) |
| `--boot-fade N` | ticks between fade steps, 1–255 (stock 5; bigger = longer trail) |
| `--boot-anim NAME` | replace the snake with a bundled animation |
| `--boot-code IHX` | replace the snake with your own code (built with `effects/anim/build.sh`) |

`--boot-step` / `--boot-fade` work with the stock snake as well as with custom animations. For
example, a slower snake with a longer trail:

```sh
python3 tools/patch_firmware.py base_f87_decrypted.bin out.bin --boot-step 3 --boot-fade 10
```

Bundled animations (build them first):

| Name | Looks like | step | fade |
|---|---|---|---|
| `fkeys` | full-white light sweeping F1..F12 | 8 | 1 |
| `wipe` | white wipe across the whole keyboard, column by column | 6 | 2 |
| `rainbow_frow` | F1..F12 one by one, a different colour per key | 8 | 1 |
| `tmtco` | T, M, T, C, O light up in turn, then a ripple spreads out from O | 4 | 2 |

```sh
effects/anim/build.sh tmtco
python3 tools/patch_firmware.py base_f87_decrypted.bin out.bin --boot-anim tmtco
```

Each preset sets its own step / fade; give `--boot-step` / `--boot-fade` to override them.

Rules:

- `--boot-anim` and `--boot-code` can't be used together.
- `--no-boot-anim` can't be combined with a custom animation; with it, `--boot-step` /
  `--boot-fade` have no effect.

Writing your own animation is covered in [BOOT_ANIMATIONS.md](BOOT_ANIMATIONS.md).

### Custom lighting effects

| Option | Effect |
|---|---|
| `--badapple` | add the Bad Apple effect as effect 6 (`effects/badapple/build/badapple.ihx`, built by `effects/badapple/build.py VIDEO`) |
| `--life` | add the Game of Life effect as effect 9 (`effects/life/build/life.ihx`, built by `effects/life/build.py`) |
| `--effect IHX` | add your own effect (repeatable) |

They can all be used together; each one goes into its own empty effect slot (6, 9, 14). With `--life`,
the USB names share their area with it and get 64 bytes (2 + 2 × length per name). See
[CUSTOM_EFFECTS.md](CUSTOM_EFFECTS.md) and [BADAPPLE.md](BADAPPLE.md).

### Other

| Option | Effect |
|---|---|
| `--force` | skip the input MD5 check (the per-byte checks still run) |

---

## Examples

Everything at once:

```sh
effects/anim/build.sh fkeys
python3 tools/patch_firmware.py base_f87_decrypted.bin out.bin \
    --manufacturer "AULA" --product "F87 White" \
    --bt3-name "F87 BT3" --bt5-name "F87 BT5" \
    --boot-anim fkeys --boot-step 6
```

Output looks like:

```
USB manufacturer -> 'AULA' at 0xee00 (10 bytes)
USB product      -> 'F87 White' at 0xee0a (20 bytes)
BT  bt3          -> 'F87 BT3'
BT  bt5          -> 'F87 BT5'
boot animation -> effects/anim/build/boot_fkeys.ihx (93 bytes at 0xec80), called from 0x1d52
boot animation step period -> 6 ticks (was 1)
boot animation fade period -> 1 ticks (was 5)
wrote out.bin: 149 bytes changed, all in ['0x1d00', '0x4000', '0x4100', '0xa000', '0xad00', '0xec00', '0xee00']
```

The last line lists every 256-byte page that changed, so you can see that nothing else was touched.

Always patch from the original image. Patching an already-patched `out.bin` is refused by the hash
check (and by the "area not empty" checks with `--force`).

---

## Flashing

By cable, with the keyboard's mode switch on USB:

```sh
./sinowisp write -d aula-f87 --format bin out.bin
```

Then replug. The boot animation only runs at power-on, so replug to see it again.

To go back to stock, flash the original image the same way:

```sh
./sinowisp write -d aula-f87 --format bin base_f87_decrypted.bin
```

---

## What it changes

All offsets are in `base_f87_decrypted.bin` (flash address = file offset).

### USB strings

The USB `GET_DESCRIPTOR` handler (`0x3FEB`) loads each string descriptor's address and length as
`MOV A,#imm` immediates. The patcher writes the new descriptors into unused flash at
`0xEE00–0xEEFF` and points the immediates there:

| String | Address hi / lo / length immediates | Original descriptor |
|---|---|---|
| manufacturer (index 1) | `0x40D2`, `0x40D6`, `0x40DF` | `0x5B14`, 17 bytes |
| manufacturer (index 0xFF, same text) | `0x41A4`, `0x41A8`, `0x41B1` | `0x5B2F`, 17 bytes |
| product (index 2) | `0x411A`, `0x411E`, `0x4127` | `0x5CD6`, 32 bytes |

The original strings stay in place, unused.

### Bluetooth names

The routine at `0xA063` copies a 13-byte name into the packet it sends to the radio module. The
patcher overwrites the name in place (zero-padded) and sets the packet length and the copy-loop
bound to the new length:

| Slot | Name | Length immediate | Loop bound |
|---|---|---|---|
| BT 3.0 | `0xAD9B` | `0xA072` | `0xA090` |
| BT 5.0 | `0xADA8` | `0xA09A` | `0xA0B7` |

### Boot animation

The power-on snake is lighting mode `0x26`, driven by the frame handler at `0x1D0B`:

| Address | Original | Patch |
|---|---|---|
| `0x8C22` | `SETB 0x33` (boot flag) | `CLR 0x33` for `--no-boot-anim` |
| `0x1D11` | `SUBB A,#5` (fade period) | `--boot-fade N` |
| `0x1D25` | `SUBB A,#1` (step period) | `--boot-step N` |
| `0x1D52` | `LCALL 0x8B26` (snake step) | `LCALL 0xEC80` for a custom animation |

Custom animation code goes into `0xEC80–0xEDFF` (384 bytes, unused by the firmware). It must start
at `0xEC80`; `effects/anim/build.sh` takes care of that.

### Checks before writing

- input MD5 matches (unless `--force`)
- input is 61440 bytes
- every patched instruction still has its original opcode and operand
- the string area `0xEE00–0xEEFF`, the code area `0xEC80–0xEDFF` and the relocated reset-vector
  slot `0xEFFB` are empty
- strings and code fit in their areas, names are within their limits

If anything fails, nothing is written.

---

## Troubleshooting

| Message / symptom | Cause | Fix |
|---|---|---|
| `input is not the known base_f87_decrypted.bin` | wrong or already patched image | use the original decrypted image |
| `effects/anim/build/<name>.ihx not built yet` | the preset isn't compiled | run `effects/anim/build.sh <name>` (needs SDCC) |
| `nothing to change` | no option given | add at least one option |
| `Bluetooth name must be 1..13 ASCII characters` | name too long or non-ASCII | shorten it |
| `AssertionError: unexpected ...` | image differs from the analysed build (with `--force`) | this image isn't supported |
| Still the stock snake / names after flashing | flashed the input file, or didn't replug | flash `out.bin`, replug |
| Old Bluetooth name still shown | the host cached the pairing | remove the device and pair again |

---

## Safety

- The bootloader (`0xF000–0xFFFF`) and the firmware's ISP entry (feature report `05 75` →
  `0xEC18`) are never touched, so a patched keyboard can always be flashed again over USB.
- If a firmware ever can't run far enough to answer the ISP command, recovery needs a hardware
  programmer on the chip's P0.0/P0.1 pins. The patches here can't cause that on their own, but
  keep it in mind before patching other parts of the firmware.

---

*Written with Claude Opus 5.5*
