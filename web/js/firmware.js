// Firmware image handling for the web patcher: recognise the AULA F87 base firmware, undo earlier
// patches, and apply ours. A port of patch_firmware.py (same sites, same checks, same output bytes).
import { BASE_CODE_SHA256, CODE_RANGES, BOOT_ANIMS, EFFECT_BLOBS } from "./fw-data.js";

export const FW_SIZE = 61440;

const STR_AREA = 0xee00, STR_AREA_END = 0xef00;
// [hi imm, lo imm, len imm, original address, original length]
const USB_SITES = {
  manufacturer: [[0x40d2, 0x40d6, 0x40df, 0x5b14, 0x11], [0x41a4, 0x41a8, 0x41b1, 0x5b2f, 0x11]],
  product: [[0x411a, 0x411e, 0x4127, 0x5cd6, 0x20]],
};
// [name address, packet length imm, loop bound imm, original name]
const BT_SITES = {
  bt3: [0xad9b, 0xa072, 0xa090, "AULA-F87 3.0 "],
  bt5: [0xada8, 0xa09a, 0xa0b7, "AULA-F87 5.0 "],
};
const BT_MAX = 13;
const BOOT_FLAG_SET = 0x8c22, BOOT_FADE_IMM = 0x1d11, BOOT_STEP_IMM = 0x1d25, BOOT_STEP_CALL = 0x1d52;
const CODE_AREA = [0xec80, 0xee00];
const EFFECT_AREAS = [[0xdc00, 0xec00], [0xee00, 0xeffb]];
const EFFECT_INIT = 0x179c, EFFECT_INIT_NEXT = 0x1b0e, FRAME_TABLE = 0x1b37;
const EFFECT_SLOTS = { 6: 0x4f78, 9: 0x4f82, 14: 0x4f8c };
// Free flash our patches write into; empty (zero) in the stock firmware.
const FREE_AREAS = [[0xdc00, 0xec00], [0xec80, 0xee00], [0xee00, 0xeffb]];

export { BOOT_ANIMS, EFFECT_BLOBS };

const hex = (n, w = 4) => "0x" + n.toString(16).padStart(w, "0");
const fromHex = (h) => Uint8Array.from(h.match(/../g) || [], (x) => parseInt(x, 16));

/** Intel HEX -> {lo, hi, bytes: Map(addr -> byte)} */
export function parseIhx(text) {
  const bytes = new Map();
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line.startsWith(":")) continue;
    const rec = fromHex(line.slice(1));
    if (rec.reduce((s, b) => s + b, 0) & 0xff) throw new Error("bad Intel HEX checksum");
    const [n, ah, al, type] = rec;
    if (type === 1) break;
    if (type !== 0) throw new Error(`unsupported Intel HEX record type ${type}`);
    for (let i = 0; i < n; i++) bytes.set(((ah << 8) | al) + i, rec[4 + i]);
  }
  if (!bytes.size) throw new Error("Intel HEX file has no data");
  const addrs = [...bytes.keys()];
  return { lo: Math.min(...addrs), hi: Math.max(...addrs), bytes };
}

export function blobToIhx({ addr, hex: h }) {
  const data = fromHex(h);
  const bytes = new Map();
  data.forEach((b, i) => bytes.set(addr + i, b));
  return { lo: addr, hi: addr + data.length - 1, bytes };
}

async function sha256(parts) {
  const len = parts.reduce((s, p) => s + p.length, 0);
  const all = new Uint8Array(len);
  let o = 0;
  for (const p of parts) { all.set(p, o); o += p.length; }
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", all));
  return [...d].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Put every site our patches touch back to its stock value and clear the free areas. */
export function unpatch(img) {
  const fw = Uint8Array.from(img);
  for (const sites of Object.values(USB_SITES)) {
    for (const [hi, lo, ln, addr, olen] of sites) {
      fw[hi] = addr >> 8; fw[lo] = addr & 0xff; fw[ln] = olen;
    }
  }
  for (const [addr, plen, bound, name] of Object.values(BT_SITES)) {
    for (let i = 0; i < BT_MAX; i++) fw[addr + i] = name.charCodeAt(i);
    fw[plen] = fw[bound] = 0x0d;
  }
  fw.set([0x12, 0x8b, 0x26], BOOT_STEP_CALL);
  fw.set([0xd2, 0x33], BOOT_FLAG_SET);
  fw[BOOT_FADE_IMM] = 0x05;
  fw[BOOT_STEP_IMM] = 0x01;
  fw.set([EFFECT_INIT_NEXT >> 8, EFFECT_INIT_NEXT & 0xff], EFFECT_INIT);
  for (const [mode, skip] of Object.entries(EFFECT_SLOTS)) {
    fw.set([0x02, 0x1d, 0xc8], FRAME_TABLE + 3 * mode);
    fw[skip + 1] = Number(mode);
  }
  for (const [s, e] of FREE_AREAS) fw.fill(0, s, e);
  return fw;
}

/** What the image is: {kind: "stock" | "patched" | "unknown", image (the unpatched one), changes} */
export async function identify(img) {
  if (img.length !== FW_SIZE) return { kind: "unknown", reason: `expected ${FW_SIZE} bytes, got ${img.length}` };
  const clean = unpatch(img);
  const h = await sha256(CODE_RANGES.map(([s, e]) => clean.subarray(s, e)));
  if (h !== BASE_CODE_SHA256) {
    return { kind: "unknown", reason: "not the AULA F87 base firmware this patcher knows (other model or version)" };
  }
  let changes = 0;
  for (let i = 0; i < FW_SIZE; i++) if (clean[i] !== img[i]) changes++;
  return { kind: changes ? "patched" : "stock", image: clean, changes };
}

function utf16Descriptor(s) {
  const raw = [];
  for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); raw.push(c & 0xff, c >> 8); }
  if (raw.length + 2 > 254) throw new Error(`USB string too long: ${s}`);
  return Uint8Array.from([raw.length + 2, 0x03, ...raw]);
}

/**
 * Apply patches to a stock image (identify(...).image). Options (all optional):
 *   manufacturer, product, bt3, bt5: strings
 *   bootAnim: "off" | key of BOOT_ANIMS; bootStep, bootFade: 1..255
 *   effects: [{lo, hi, bytes, name}] (parseIhx / blobToIhx results)
 * Returns {image, log}.
 */
export function applyPatches(stock, o) {
  const fw = Uint8Array.from(stock);
  const log = [];
  const any = (s, e) => fw.subarray(s, e).some((b) => b);

  // the same checks as patch_firmware.py: the code must look like what we analysed
  for (const sites of Object.values(USB_SITES)) {
    for (const [hi, lo, ln, addr, olen] of sites) {
      if (fw[hi - 1] !== 0x74 || fw[lo - 1] !== 0x74 || fw[ln - 1] !== 0x74) throw new Error("unexpected opcode");
      if (((fw[hi] << 8) | fw[lo]) !== addr || fw[ln] !== olen) throw new Error("unexpected operand");
    }
  }
  for (const [addr, plen, bound] of Object.values(BT_SITES)) {
    if (fw[plen - 1] !== 0x76 || fw[plen] !== 0x0d || fw[bound - 1] !== 0xb4 || fw[bound] !== 0x0d) {
      throw new Error("unexpected Bluetooth name code");
    }
    if (String.fromCharCode(...fw.subarray(addr, addr + 4)) !== "AULA") throw new Error("unexpected BT name");
  }
  if (any(STR_AREA, STR_AREA_END) || any(0xeffb, 0xeffe)) throw new Error("string area / reset-vector slot not empty");

  // custom effects first: the USB strings must stay below them
  const effects = [];
  for (const fx of o.effects || []) {
    const { lo, hi, bytes, name } = fx;
    if (!EFFECT_AREAS.some(([s, e]) => s <= lo && hi < e)) {
      throw new Error(`${name}: must lie in ${EFFECT_AREAS.map(([s, e]) => `${hex(s)}-${hex(e - 1)}`).join(" or ")}`);
    }
    const h = Array.from({ length: 10 }, (_, i) => bytes.get(lo + i));
    if (h[0] !== 0x02 || h[3] !== 0x02 || h[6] !== 0x02 || ((h[7] << 8) | h[8]) !== EFFECT_INIT_NEXT) {
      throw new Error(`${name}: doesn't start with the custom effect header`);
    }
    const mode = h[9];
    if (!(mode in EFFECT_SLOTS)) throw new Error(`${name}: effect slot ${mode} isn't free (free: 6, 9, 14)`);
    if (effects.some((e) => e.mode === mode)) throw new Error(`two effects for slot ${mode}`);
    for (const e of effects) if (lo <= e.hi && e.lo <= hi) throw new Error(`${name} overlaps ${e.name}`);
    if (any(lo, hi + 1)) throw new Error(`${name}: flash at ${hex(lo)}-${hex(hi)} not empty`);
    effects.push({ lo, hi, bytes, mode, name });
  }
  const strEnd = Math.min(STR_AREA_END, ...effects.filter((e) => e.lo >= STR_AREA).map((e) => e.lo));

  // USB strings
  let cursor = STR_AREA;
  for (const key of ["manufacturer", "product"]) {
    const text = o[key];
    if (!text) continue;
    const desc = utf16Descriptor(text);
    if (cursor + desc.length > strEnd) {
      throw new Error(`USB names don't fit (${strEnd - STR_AREA} bytes${strEnd < STR_AREA_END ? ", the rest holds Game of Life" : ""})`);
    }
    fw.set(desc, cursor);
    for (const [hi, lo, ln] of USB_SITES[key]) { fw[hi] = cursor >> 8; fw[lo] = cursor & 0xff; fw[ln] = desc.length; }
    log.push(`USB ${key} → "${text}"`);
    cursor += desc.length;
    cursor += cursor & 1;
  }

  // Bluetooth names
  for (const key of ["bt3", "bt5"]) {
    const text = o[key];
    if (!text) continue;
    if (!/^[\x20-\x7e]{1,13}$/.test(text)) throw new Error(`Bluetooth name must be 1–${BT_MAX} plain ASCII characters`);
    const [addr, plen, bound] = BT_SITES[key];
    fw.fill(0, addr, addr + BT_MAX);
    for (let i = 0; i < text.length; i++) fw[addr + i] = text.charCodeAt(i);
    fw[plen] = fw[bound] = text.length;
    log.push(`Bluetooth ${key === "bt3" ? "3.0" : "5.0"} name → "${text}"`);
  }

  // boot animation
  let { bootStep, bootFade } = o;
  if (o.bootAnim === "off") {
    fw[BOOT_FLAG_SET] = 0xc2;
    log.push("boot animation → off");
  } else if (o.bootAnim) {
    const preset = BOOT_ANIMS[o.bootAnim];
    if (!preset) throw new Error(`unknown boot animation ${o.bootAnim}`);
    const code = blobToIhx(preset);
    if (code.lo !== CODE_AREA[0] || code.hi >= CODE_AREA[1]) throw new Error("animation code outside its area");
    if (any(CODE_AREA[0], CODE_AREA[1])) throw new Error("code area not empty");
    for (const [a, b] of code.bytes) fw[a] = b;
    fw[BOOT_STEP_CALL + 1] = code.lo >> 8;
    fw[BOOT_STEP_CALL + 2] = code.lo & 0xff;
    bootStep ??= preset.step;
    bootFade ??= preset.fade;
    log.push(`boot animation → ${o.bootAnim}`);
  }
  for (const [name, val, addr] of [["step", bootStep, BOOT_STEP_IMM], ["fade", bootFade, BOOT_FADE_IMM]]) {
    if (val === undefined || val === null || val === "") continue;
    const v = Number(val);
    if (!Number.isInteger(v) || v < 1 || v > 255) throw new Error(`boot ${name} must be 1–255`);
    fw[addr] = v;
  }

  // custom effects, each one's init chained to the next one's
  effects.forEach((e, i) => {
    for (const [a, b] of e.bytes) fw[a] = b;
    if (i + 1 < effects.length) { fw[e.lo + 7] = effects[i + 1].lo >> 8; fw[e.lo + 8] = effects[i + 1].lo & 0xff; }
    const entry = FRAME_TABLE + 3 * e.mode;
    fw[entry + 1] = (e.lo + 3) >> 8;
    fw[entry + 2] = (e.lo + 3) & 0xff;
    fw[EFFECT_SLOTS[e.mode] + 1] = 0xff;
    log.push(`effect ${e.mode} → ${e.name}`);
  });
  if (effects.length) { fw[EFFECT_INIT] = effects[0].lo >> 8; fw[EFFECT_INIT + 1] = effects[0].lo & 0xff; }

  let changed = 0;
  for (let i = 0; i < FW_SIZE; i++) if (fw[i] !== stock[i]) changed++;
  return { image: fw, log, changed };
}
