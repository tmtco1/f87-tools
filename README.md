# f87-tools
This repo has various tools for Aula F87 keyboard. 
# Tools
- [patch-firmware.py](parch_firmware.py)
- [aulaf87.py](aulaf87.py)
- [live/stream_video.py](live/stream_video.py)
- A WebHID controller for keyboard

## patch-firmware.py
You can do cool things with patching the firmware of this keyboard. Things like
- Changing keyboards name and BT name
- Applying custom boot animation or even making your own

You can get the firmwares from [f87fw/firmware](https://github.com/tmtco1/f87fw/blob/main/firmware/base_f87_decrypted.bin). For more detail see [PATCHING.md](docs/PATCHING.md) and [BOOT_ANIMATIONS.md](docs/BOOT_ANIMATIONS.md).

## aulaf87.py
A python script to manage your keyboards lightning effects. Refer to [ai slop document](docs/RGB_CONTROL.md) for how to use.

## live/stream_video.py
This script uses AULA's live music equaliser protocol to send live per-key lightning data so it can play video. Refer to [LIVE_LIGHTING.md](docs/LIVE_LIGHTING.md) for how to use and more in-depth explanation.

## WebHID controller for keyboard
It is a cross-platform keyboard RGB controller unlike original app you can only use on Windows. You can use it [here](https://github.com/tmtco1/f87tools).

#
> [!WARNING]
> Disclaimer: Unofficial community project, not affiliated with or endorsed by AULA or BY Tech. Provided as is, without warranty. Sending commands to your keyboard or flashing firmware is at your own risk and can leave it unusable. See [DISCLAIMER.md](DISCLAIMER.md) for details.