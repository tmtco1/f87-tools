import {
  CMD_LED, CMD_KEYCOLOR, CMD_PALETTE, CFG_LEN, PAL_LEN, PLANE, KEYDATA_LEN, CUSTOM_EFFECT, KEYS,
  DEFAULT_CONFIG, DEFAULT_PALETTE, DEFAULT_BLUE_KEYS, KEEP_ON_RESET,
} from "./constants.js";
import { Transport, sleep } from "./hid-transport.js";

export function validateConfig(cfg) {
  if (cfg.length !== CFG_LEN || cfg[0x38] !== 0xff || cfg[0x39] !== 0xff || cfg[0x7e] !== 0x5a || cfg[0x7f] !== 0xa5) {
    throw new Error(
      "Config markers are wrong (expected FF FF at 0x38 and 5A A5 at 0x7E). Refusing to continue: " +
      "writing a misaligned config can reset the keyboard to defaults."
    );
  }
}

export const slotOffset = (effectId) => 0x3a + 2 * (effectId - 1);
export const palOffset = (effectId, slot) => 21 * effectId + 3 * slot;

/** All keyboard I/O goes through one promise queue so report sequences never interleave. */
export class Device {
  constructor(hid) {
    this.hid = hid;
    this.t = new Transport(hid);
    this.queue = Promise.resolve();
  }

  exclusive(op) {
    const result = this.queue.then(op);
    this.queue = result.catch(() => {});
    return result;
  }

  // ---- unqueued helpers: only call from inside exclusive() ----
  async #getConfig() {
    const cfg = await this.t.read(CMD_LED, CFG_LEN);
    validateConfig(cfg);
    return cfg;
  }

  async #putConfig(next) {
    validateConfig(next);
    const cur = await this.#getConfig();
    if (cur[0x0a] === next[0x0a]) {
      // The firmware only restarts its LEDs when the effect id changes.
      const tmp = Uint8Array.from(next);
      tmp[0x0a] = next[0x0a] ? 0 : 1;
      await this.t.write(CMD_LED, tmp);
      await sleep(50);
    }
    await this.t.write(CMD_LED, next);
    await sleep(20);
    return this.#getConfig();
  }

  // ---- queued operations ----
  readConfig() {
    return this.exclusive(() => this.#getConfig());
  }

  readPalette() {
    return this.exclusive(() => this.t.read(CMD_PALETTE, PAL_LEN));
  }

  /** Read the latest config, let `mutate` change a copy, write it, return what the keyboard now holds. */
  updateConfig(mutate) {
    return this.exclusive(async () => {
      const next = Uint8Array.from(await this.#getConfig());
      mutate(next);
      return this.#putConfig(next);
    });
  }

  setEffect(id) {
    return this.updateConfig((c) => {
      c[0x0a] = id;
      c[0x09] = id === CUSTOM_EFFECT ? 1 : 0;
    });
  }

  setParam(effectId, { brightness, speed, slot }) {
    return this.updateConfig((c) => {
      const o = slotOffset(effectId);
      if (brightness !== undefined) c[o] = brightness;
      if (speed !== undefined) c[o + 1] = (speed << 4) | (c[o + 1] & 0x0f);
      if (slot !== undefined) c[o + 1] = (c[o + 1] & 0xf0) | slot;
    });
  }

  setZone(base, field, value) {
    return this.updateConfig((c) => { c[base + field] = value; });
  }

  setPaletteColor(effectId, slot, [r, g, b]) {
    return this.exclusive(async () => {
      const pal = Uint8Array.from(await this.t.read(CMD_PALETTE, PAL_LEN));
      const o = palOffset(effectId, slot);
      pal.set([r, g, b], o);
      pal[0x1fa] = 0x5a;
      pal[0x1fb] = 0xa5;
      await this.t.write(CMD_PALETTE, pal);
      await sleep(50);
      return this.t.read(CMD_PALETTE, PAL_LEN);
    });
  }

  /** @returns Map<matrixIndex,[r,g,b]> for every known key */
  readKeyColors(group) {
    return this.exclusive(async () => {
      const d = await this.t.read(CMD_KEYCOLOR, KEYDATA_LEN, group);
      const map = new Map();
      for (const i of Object.values(KEYS)) map.set(i, [d[i], d[PLANE + i], d[2 * PLANE + i]]);
      return map;
    });
  }

  /** Write the profile, then switch the keyboard to custom mode. */
  writeKeyColorsAndShow(group, map) {
    return this.exclusive(async () => {
      const d = new Uint8Array(KEYDATA_LEN);
      for (const [i, [r, g, b]] of map) {
        d[i] = r; d[PLANE + i] = g; d[2 * PLANE + i] = b;
      }
      await this.t.write(CMD_KEYCOLOR, d, group);
      await sleep(50);
      const next = Uint8Array.from(await this.#getConfig());
      next[0x09] = 1;
      next[0x0a] = CUSTOM_EFFECT;
      return this.#putConfig(next);
    });
  }

  /** Factory lighting: palette, all 5 per-key colour groups, then the LED config. Returns the new config. */
  factoryReset() {
    return this.exclusive(async () => {
      await this.t.write(CMD_PALETTE, Uint8Array.from(DEFAULT_PALETTE));
      await sleep(50);
      const keys = new Uint8Array(KEYDATA_LEN);
      for (const i of DEFAULT_BLUE_KEYS) keys[2 * PLANE + i] = 0xff;
      for (let group = 0; group < 5; group++) {
        await this.t.write(CMD_KEYCOLOR, keys, group);
        await sleep(50);
      }
      const cur = await this.#getConfig();
      const next = Uint8Array.from(DEFAULT_CONFIG);
      for (const i of KEEP_ON_RESET) next[i] = cur[i];
      return this.#putConfig(next);
    });
  }

  rawRead(cmd, arg, size) {
    return this.exclusive(() => this.t.read(cmd & 0x7f, size, arg));
  }

  rawWrite(cmd, arg, bytes) {
    return this.exclusive(() => this.t.write(cmd, bytes, arg));
  }
}
