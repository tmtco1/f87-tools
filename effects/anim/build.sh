#!/bin/sh
# Build a boot animation into an Intel HEX blob located at 0xEC80 (no C runtime, no startup code).
#
# usage: effects/anim/build.sh [file.c | name] [extra sdcc options...]
#   effects/anim/build.sh                          -> effects/anim/boot_fkeys.c
#   effects/anim/build.sh wipe                     -> effects/anim/build/wipe.ihx
#   effects/anim/build.sh boot_fkeys -DTAIL_STEPS=10
set -e
cd "$(dirname "$0")"
src=${1:-boot_fkeys}; [ $# -gt 0 ] && shift
case "$src" in *.c) ;; *) src="$src.c" ;; esac
[ -f "$src" ] || { echo "error: $src not found (paths are relative to anim/)" >&2; exit 1; }
name=$(basename "$src" .c)

SDCC=$(command -v sdcc || command -v sdcc-sdcc) || { echo "error: sdcc not found" >&2; exit 1; }
SDLD=$(command -v sdld || command -v sdcc-sdld) || { echo "error: sdld not found" >&2; exit 1; }
mkdir -p build
"$SDCC" -mmcs51 --model-small --opt-code-size "$@" -c "$src" -o "build/$name.rel"

# The code runs inside the Keil-built firmware: it must not own any RAM or call SDCC's runtime library.
# (SDCC separates ".area" and the segment name with a space or a tab)
ram=$(awk '/\.area[ \t]+(DSEG|OSEG|ISEG|BSEG|XSEG|XISEG|PSEG)[ \t]/{f=1;next} /\.area/{f=0} f && /^[A-Za-z_][A-Za-z0-9_]*:/{gsub(":","");print}' "build/$name.asm")
if [ -n "$ram" ]; then
    echo "error: $name uses RAM variables (globals, statics or spilled locals): $(echo $ram)" >&2
    echo "       use fewer locals, or the XRAM state bytes -- see docs/BOOT_ANIMATIONS.md" >&2; exit 1
fi
ext=$(grep -oE '^\s+(lcall|ljmp|acall|ajmp)\s+_[A-Za-z0-9_]+' "build/$name.asm" | awk '{print $2}' | sort -u |
      while read -r sym; do grep -q "^$sym:" "build/$name.asm" || echo "$sym"; done)
if [ -n "$ext" ]; then
    echo "error: $name calls library/runtime routines it can't use: $(echo $ext)" >&2
    echo "       (usually int arithmetic -- store byte products in an unsigned char first)" >&2; exit 1
fi

"$SDLD" -n -m -i "build/$name.ihx" -b CSEG=0xEC80 -b HOME=0xEC80 "build/$name.rel"

# boot_step must be the entry point at 0xEC80 and everything must fit below 0xEE00
off=$(awk '$2 == "_boot_step" {print $3}' "build/$name.sym")
[ -n "$off" ] || { echo "error: no boot_step() function in $src" >&2; exit 1; }
[ "$off" = "000000" ] || { echo "error: boot_step must be the first function in $src (it must sit at 0xEC80)" >&2; exit 1; }
python3 - "build/$name.ihx" <<'EOF'
import sys
addrs = []
for line in open(sys.argv[1]):
    r = bytes.fromhex(line.strip()[1:])
    if r[3] == 0:
        a = r[1] << 8 | r[2]; addrs += range(a, a + r[0])
if not addrs or min(addrs) != 0xEC80 or max(addrs) >= 0xEE00:
    sys.exit(f"error: code must lie in 0xEC80-0xEDFF (384 bytes) (got {min(addrs):#06x}-{max(addrs):#06x})")
print(f"built effects/anim/{sys.argv[1]} ({len(addrs)} bytes at 0xEC80-{max(addrs):#06x}, {0xEE00 - 1 - max(addrs)} bytes left)")
EOF
