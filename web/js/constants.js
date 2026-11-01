// Device identity and protocol constants. Values from the vendor app's protocol
// (see aulaf87.py in this repo).
export const VID = 0x258a;
export const PID = 0x010c;
export const USAGE_PAGE = 0xff00;
export const REPORT_ID = 6;
export const BODY = 0x207;
export const CHUNK = 0x200;
export const HEADER = 7;
export const DELAY_MS = 20;

export const CMD_LED = 0x04;
export const CMD_KEYCOLOR = 0x06;
export const CMD_PALETTE = 0x0a;

export const CFG_LEN = 128;
export const PAL_LEN = 512;
export const PLANE = 126;
export const KEYDATA_LEN = PLANE * 3 + 6;

export const CUSTOM_EFFECT = 21;

// Factory defaults from the base F87 firmware (what holding Fn+Esc for 3 s restores): LED config =
// flash 0xC400, palette = flash 0xC800, per-key colours = blue on Esc, WASD and the arrows in all 5
// groups. Keymaps and macros are not covered.
const fromHexStr = (h) => Uint8Array.from(h.match(/../g).map((x) => parseInt(x, 16)));
export const DEFAULT_CONFIG = fromHexStr(
  "000303020000040407000b200100000000000100020100ff0200000001000401000000000000000000000000000000000000000000000000ffff04370437043704370437043704370437043704370437043704370437043704370437043704370437074707470744074407440744074407440744040404040404040404045aa5");
export const DEFAULT_PALETTE = fromHexStr(
  "ff000000ff000000ffffff00ff00ff00ffffffffff".repeat(23) + "03000000009200001000000000000000000000000000005aa500100000");
export const DEFAULT_BLUE_KEYS = [0, 9, 14, 15, 21, 89, 94, 95, 101];
export const KEEP_ON_RESET = [0x0c, 0x0e];   // the firmware's own reset keeps these config bytes

// id, name, speed, brightness, colour  (capabilities from aulaf87.py / KB.ini)
export const EFFECTS = [
  [0, "Off", 0, 0, 0],
  [1, "Static", 0, 1, 1],
  [2, "Breathing", 1, 1, 1],
  [3, "Rainbow", 1, 1, 0],
  [4, "Flash away", 1, 1, 1],
  [5, "Raindrops", 1, 1, 1],
  [6, "Empty (Bad Apple if patched)", 1, 1, 1],
  [7, "Ripples", 1, 1, 1],
  [8, "Stars twinkle", 1, 1, 1],
  [9, "Empty (Life if patched)", 1, 1, 1],
  [10, "Retro snake", 1, 1, 1],
  [11, "Neon stream", 1, 1, 1],
  [12, "Reaction", 1, 1, 1],
  [13, "Sine wave", 1, 1, 1],
  [14, "Empty", 0, 0, 0],
  [15, "Rotating windmill", 1, 1, 0],
  [16, "Colorful waterfall", 1, 1, 0],
  [17, "Blossoming", 1, 1, 0],
  [18, "Empty", 0, 0, 0],
  [21, "Custom (per-key)", 0, 0, 0],
].map(([id, name, speed, brightness, colour]) => ({ id, name, speed, brightness, colour }));

export const ZONES = { bar: 0x12, front: 0x1c };
export const ZONE_MODES = ["Off", "Rainbow", "Color cycle", "Static", "Breathing"];
export const ZONE_COLORS = ["Red", "Green", "Blue", "Yellow", "Magenta", "Cyan", "White", "Multicolor"];

// key name -> matrix index, from [KEY] in Dev/kb/F87PRO/KB.ini
export const KEYS = {
  esc: 0, f1: 12, f2: 18, f3: 24, f4: 30, f5: 36, f6: 42, f7: 48,
  f8: 54, f9: 60, f10: 66, f11: 72, f12: 78, prtsc: 84, scrlk: 90,
  pause: 96, grave: 1, 1: 7, 2: 13, 3: 19, 4: 25, 5: 31, 6: 37,
  7: 43, 8: 49, 9: 55, 0: 61, minus: 67, equal: 73, backspace: 79,
  insert: 85, home: 91, pgup: 97, tab: 2, q: 8, w: 14, e: 20, r: 26,
  t: 32, y: 38, u: 44, i: 50, o: 56, p: 62, lbracket: 68,
  rbracket: 74, backslash: 80, delete: 86, end: 92, pgdn: 98, caps: 3,
  a: 9, s: 15, d: 21, f: 27, g: 33, h: 39, j: 45, k: 51, l: 57,
  semicolon: 63, quote: 69, enter: 81, lshift: 4, z: 10, x: 16, c: 22,
  v: 28, b: 34, n: 40, m: 46, comma: 52, period: 58, slash: 64,
  rshift: 82, up: 94, lctrl: 5, lwin: 11, lalt: 17, space: 35,
  ralt: 53, fn: 59, menu: 65, rctrl: 83, left: 89, down: 95, right: 101,
};

// Rows of [keyName, label, width] ; a bare number is a gap (in key units).
const k = (n, label, w = 1) => [n, label ?? n.toUpperCase(), w];
const letters = (s) => [...s].map((c) => k(c));
export const LAYOUT = [
  [k("esc", "Esc"), 1, k("f1", "F1"), k("f2", "F2"), k("f3", "F3"), k("f4", "F4"), 0.5,
   k("f5", "F5"), k("f6", "F6"), k("f7", "F7"), k("f8", "F8"), 0.5,
   k("f9", "F9"), k("f10", "F10"), k("f11", "F11"), k("f12", "F12"), 0.25,
   k("prtsc", "Prt"), k("scrlk", "Scr"), k("pause", "Pau")],
  [k("grave", "`"), ...[..."1234567890"].map((c) => k(c, c)), k("minus", "-"), k("equal", "="),
   k("backspace", "Bksp", 2), 0.25, k("insert", "Ins"), k("home", "Home"), k("pgup", "PgUp")],
  [k("tab", "Tab", 1.5), ...letters("qwertyuiop"), k("lbracket", "["), k("rbracket", "]"),
   k("backslash", "\\", 1.5), 0.25, k("delete", "Del"), k("end", "End"), k("pgdn", "PgDn")],
  [k("caps", "Caps", 1.75), ...letters("asdfghjkl"), k("semicolon", ";"), k("quote", "'"),
   k("enter", "Enter", 2.25)],
  [k("lshift", "Shift", 2.25), ...letters("zxcvbnm"), k("comma", ","), k("period", "."),
   k("slash", "/"), k("rshift", "Shift", 2.75), 1.25, k("up", "↑")],
  [k("lctrl", "Ctrl", 1.25), k("lwin", "Win", 1.25), k("lalt", "Alt", 1.25), k("space", "", 6.25),
   k("ralt", "Alt", 1.25), k("fn", "Fn", 1.25), k("menu", "Menu", 1.25), k("rctrl", "Ctrl", 1.25),
   0.25, k("left", "←"), k("down", "↓"), k("right", "→")],
];
