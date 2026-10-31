# RGB control: `aulaf87.py`

Control the AULA F87's lighting from Linux without the vendor app: built-in effects, per-key
colours, effect colours, and the light bar / front light. It talks to the stock firmware over USB
using the same protocol as AULA's Windows software (`OemDrv.exe`, class `CDevG5KB`), reverse
engineered and checked on the keyboard.

For video or animations streamed live to the keys, use `live/stream_video.py` instead
(see [LIVE_LIGHTING.md](LIVE_LIGHTING.md)).

---

## Requirements

- Linux, Python 3 (standard library only)
- The keyboard connected **by cable** (USB `258a:010c`)
- Access to `/dev/hidraw*`, e.g. with this udev rule (then replug the keyboard):

  ```sh
  printf '%s\n' 'SUBSYSTEMS=="usb|hidraw", ATTRS{idVendor}=="258a", MODE="0666", TAG+="uaccess"' \
    | sudo tee /etc/udev/rules.d/99-aula-f87.rules
  sudo udevadm control --reload
  ```

The tool finds the keyboard automatically. Use `--device /dev/hidrawN` to pick a node yourself.

---

## Commands

```
aulaf87.py [--device /dev/hidrawN] {list,info,dump,effect,custom,light,raw} ...
```

| Command | What it does |
|---|---|
| `list` | List the built-in effects and which options each one takes |
| `info` | Show the model ID and firmware version |
| `dump` | Print the LED config and the effect colour palette (hex) |
| `effect` | Select a built-in effect, with brightness, speed and colour |
| `custom` | Set per-key colours and switch to the custom effect |
| `light` | Control the light bar or the front light |
| `raw` | Send a raw write command (for experiments) |

### `effect`

```sh
python3 aulaf87.py effect breathing -b 4 -s 2 -c 00aaff   # blue breathing, full brightness
python3 aulaf87.py effect ripples -r                      # ripples in multicolour
python3 aulaf87.py effect off
```

| Option | Values |
|---|---|
| `EFFECT` | name or id from the table below |
| `-b`, `--brightness` | 0–4 |
| `-s`, `--speed` | 0 (slow) – 4 (fast) |
| `-c`, `--color RRGGBB` | any colour (written into the effect's first palette slot) |
| `-r`, `--rainbow` | multicolour instead of one colour |

| Id | Name | Speed | Brightness | Colour |
|---|---|---|---|---|
| 0 | `off` | | | |
| 1 | `static` | | ✓ | ✓ |
| 2 | `breathing` | ✓ | ✓ | ✓ |
| 3 | `rainbow` | ✓ | ✓ | |
| 4 | `flash-away` | ✓ | ✓ | ✓ |
| 5 | `raindrops` | ✓ | ✓ | ✓ |
| 6 | `rainbow-wheel` | ✓ | ✓ | ✓ |
| 7 | `ripples` | ✓ | ✓ | ✓ |
| 8 | `stars` | ✓ | ✓ | ✓ |
| 9 | `shadow-disappear` | ✓ | ✓ | ✓ |
| 10 | `retro-snake` | ✓ | ✓ | ✓ |
| 11 | `neon-stream` (factory default) | ✓ | ✓ | ✓ |
| 12 | `reaction` | ✓ | ✓ | ✓ |
| 13 | `sine-wave` | ✓ | ✓ | ✓ |
| 14 | `scanning` | ✓ | ✓ | ✓ |
| 15 | `windmill` | ✓ | ✓ | |
| 16 | `waterfall` | ✓ | ✓ | |
| 17 | `blossoming` | ✓ | ✓ | |
| 18 | `storm` | ✓ | ✓ | ✓ |
| 21 | `custom` (per-key colours) | | | |

### `custom`

```sh
python3 aulaf87.py custom --all 202020 w=ff0000 a=ff0000 s=ff0000 d=ff0000 esc=00ff00
```

- `--all RRGGBB` sets every key first; `KEY=RRGGBB` pairs then override single keys.
  Keys not given are off.
- `--group N` selects the colour profile (0–4, default 0). Only profile 0 has been tested.

Key names: `esc f1`…`f12 prtsc scrlk pause grave 1`…`0 minus equal backspace insert home pgup
tab q w e r t y u i o p lbracket rbracket backslash delete end pgdn caps a s d f g h j k l
semicolon quote enter lshift z x c v b n m comma period slash rshift up lctrl lwin lalt space ralt
fn menu rctrl left down right`

### `light`

```sh
python3 aulaf87.py light bar -m breathing -c cyan -b 3 -s 2
python3 aulaf87.py light front -m off
```

| Option | Values |
|---|---|
| `bar` / `front` | the light bar or the front light |
| `-m`, `--mode` | `off`, `rainbow`, `cycle`, `static`, `breathing` |
| `-c`, `--color` | `red green blue yellow magenta cyan white multi` |
| `-b`, `--brightness` | 0–4 |
| `-s`, `--speed` | 0–4 |

### `info`, `dump`, `raw`

```sh
python3 aulaf87.py info        # e.g. "model id 0x8F (AULA F87), firmware 12.00"
python3 aulaf87.py dump        # LED config + palette as hex
python3 aulaf87.py raw 0x04 "<hex bytes>" --arg 0
```

`raw` writes the given bytes with any command. Use it only if you know what the command does
(see [Protocol](#protocol)).

---

## Things to know

- **Changes are stored on the keyboard.** Effects, colours and per-key colours survive a replug.
  Each write makes the keys blink briefly while the firmware saves and restarts its lighting, so
  don't use these commands for animations (use the live mode in `live/stream_video.py`).
- **Firmware quirk: the effect id must change.** After a config write, the firmware only
  restarts its lighting if the effect id changed. A write that only changes brightness, speed or
  the extra zones would turn every light off until replug. The tool handles this by briefly
  switching to another effect first.
- **Cable only.** In 2.4 GHz / Bluetooth mode the keyboard doesn't take these commands from USB.
- **Python use:** `from aulaf87 import Keyboard` gives `get_config()`, `set_config()`,
  `set_effect()`, `get_palette()`, `set_palette()`, `get_key_colors()`, `set_key_colors()`,
  `set_zone()`, `read()` and `write()`.

---

## Protocol

Every transfer is one or more **520-byte HID feature reports** (report ID 6) on the keyboard's
vendor interface (interface 1, usage page `0xFF00`). On Linux: `HIDIOCSFEATURE(520)` /
`HIDIOCGFEATURE(520)` on its hidraw node.

| Offset | Meaning |
|---|---|
| 0 | Report ID `0x06` |
| 1 | Command: write `0x0N`, read `0x8N` |
| 2 | Argument (layer / colour group), else 0 |
| 3 | 0 |
| 4 | Packet count |
| 5 | Packet index |
| 6–7 | Chunk length, little endian (max 512) |
| 8–519 | Data |

**Write:** send each chunk with SetFeature. **Read:** SetFeature the request header, wait, then
GetFeature; the reply echoes the header with the data at offset 8. The vendor app waits 20 ms
before each packet; so does this tool.

| Write | Read | Size | Contents |
|---|---|---|---|
| `0x03` | `0x83` | 4 × 128 | Key matrix for layer `arg` (not decoded) |
| `0x04` | `0x84` | 128 | LED config |
| `0x05` | `0x85` | variable | Macros (not decoded) |
| `0x06` | `0x86` | 384 | Per-key colours for colour group `arg` |
| `0x08` | – | 378 | **Live frame**, RAM only, see [LIVE_LIGHTING.md](LIVE_LIGHTING.md) |
| `0x0a` | `0x8a` | 512 | Effect colour palette |
| `0x0d` | – | 5 | GIF animation parameters (not decoded) |
| – | `0x82` | 6 | Device ID; byte 5 = model (`0x8F` F87, `0x0B` F87 PRO, `0xA9` F87 PRO Wired) |

### LED config (`0x04`, 128 bytes)

Always read-modify-write: read with `0x84`, change bytes, write with `0x04`.

| Offset | Meaning |
|---|---|
| `0x09` | 1 when the custom per-key effect is selected |
| `0x0a` | Main effect id |
| `0x12`–`0x15` | Light bar: mode, colour, brightness, speed |
| `0x1c`–`0x1f` | Front light: mode, colour, brightness, speed |
| `0x38`–`0x39` | Always `ff ff` |
| `0x3a + 2·(id−1)` | Brightness 0–4 of effect `id` (1–18) |
| `0x3b + 2·(id−1)` | `speed << 4 \| colour` of effect `id`; colour 0–6 = palette slot, 7 = multicolour |
| `0x7e`–`0x7f` | Trailer `5a a5`. If it's missing, the firmware resets the whole config to defaults. |

Other bytes hold settings such as debounce, Win lock and OS mode. They're kept as read.

### Palette (`0x0a`, 512 bytes)

7 RGB colours (21 bytes) per effect at offset `21 × id`; entry 0 is unused. Bytes
`0x1fa`–`0x1fb` must be `5a a5`. To use a colour: write it into one of the effect's slots, then
set the colour nibble of that effect's config byte to the slot number.

### Per-key colours (`0x06`, 384 bytes)

Three 126-byte planes, **R, then G, then B**, plus 6 padding bytes. Each key's index is its
matrix position, `col × 6 + row` in the keyboard grid (e.g. Esc 0, F1 12, Z 10, Space 35). After
uploading, select effect 21 with config byte `0x09` = 1 to show them.

---

*Written with Claude Opus 5.5*
