# f87-tools
Tools for the AULA F87 keyboard: RGB control, firmware patching, custom lighting effects and a WebHID controller.

## Layout
| Folder | Contents |
|---|---|
| [tools/](tools/) | `patch_firmware.py`, `aulaf87.py`, `build_web_data.py`, and `live/` (live lighting streams) |
| [effects/](effects/) | Code that runs inside the keyboard: `anim/` (boot animations), `badapple/`, `life/` |
| [web/](web/) | The WebHID controller and in-browser firmware patcher (published to GitHub Pages) |
| [tests/](tests/) | Simulator tests for the effects and animations; `tests/run_all.sh` runs them |
| [docs/](docs/) | Documentation, see [docs/README.md](docs/README.md) |

## tools/patch_firmware.py
You can do cool things with patching the firmware of this keyboard. Things like
- Changing keyboards name and BT name
- Applying custom boot animation or even making your own
- Adding new lighting effects that run on the keyboard itself: Bad Apple and Game of Life, in the colour set in the controller

You can get the firmwares from [f87fw/firmware](https://github.com/tmtco1/f87fw/blob/main/firmware/base_f87_decrypted.bin). For more detail see [PATCHING.md](docs/PATCHING.md) and [BOOT_ANIMATIONS.md](docs/BOOT_ANIMATIONS.md). The effects are explained in [CUSTOM_EFFECTS.md](docs/CUSTOM_EFFECTS.md) and [BADAPPLE.md](docs/BADAPPLE.md).

## tools/aulaf87.py
A python script to manage your keyboard's lighting effects. See [RGB_CONTROL.md](docs/RGB_CONTROL.md) for how to use it.

## tools/live/stream_video.py
This script uses AULA's live music equaliser protocol to send live per-key lighting data so it can play video. See [LIVE_LIGHTING.md](docs/LIVE_LIGHTING.md) for how to use it and a more in-depth explanation.

## Web UI (`web/`)
A cross-platform keyboard RGB controller, unlike the original app that only runs on Windows. It also has a firmware patcher that does the same as `patch_firmware.py` in the browser: custom names, boot animations, and the Bad Apple and Game of Life effects. You can use it [here](https://tmtco1.github.io/f87-tools).

`web/js/fw-data.js` is generated. After rebuilding an animation or effect, run `python3 tools/build_web_data.py` (without `--badapple` the site's Bad Apple option disappears) to refresh it.

> [!WARNING]
> Disclaimer: Unofficial community project, not affiliated with or endorsed by AULA or BY Tech. Provided as is, without warranty. Sending commands to your keyboard or flashing firmware is at your own risk and can leave it unusable. See [DISCLAIMER.md](DISCLAIMER.md) for details.
