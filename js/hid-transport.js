import { REPORT_ID, BODY, CHUNK, HEADER, DELAY_MS } from "./constants.js";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function hex(bytes) {
  const rows = [];
  for (let i = 0; i < bytes.length; i += 16) {
    const row = [...bytes.slice(i, i + 16)].map((b) => b.toString(16).padStart(2, "0")).join(" ");
    rows.push(i.toString(16).padStart(4, "0") + "  " + row);
  }
  return rows.join("\n");
}

/** Feature-report framing for the vendor interface. Never call outside Device.exclusive(). */
export class Transport {
  constructor(hid) {
    this.hid = hid;
  }

  #frame(cmd, arg, count, idx, n) {
    const body = new Uint8Array(BODY);
    body.set([cmd, arg, 0, count, idx, n & 0xff, n >> 8]);
    return body;
  }

  async write(cmd, data, arg = 0) {
    const count = Math.ceil(data.length / CHUNK);
    for (let i = 0; i < count; i++) {
      const part = data.subarray(i * CHUNK, i * CHUNK + CHUNK);
      const body = this.#frame(cmd, arg, count, i, part.length);
      body.set(part, HEADER);
      await sleep(DELAY_MS);
      await this.hid.sendFeatureReport(REPORT_ID, body);
    }
  }

  async read(cmd, size, arg = 0) {
    const out = new Uint8Array(size);
    const count = Math.ceil(size / CHUNK);
    for (let i = 0; i < count; i++) {
      const n = Math.min(CHUNK, size - i * CHUNK);
      await sleep(DELAY_MS);
      await this.hid.sendFeatureReport(REPORT_ID, this.#frame(cmd | 0x80, arg, count, i, n));
      await sleep(DELAY_MS);
      const view = await this.hid.receiveFeatureReport(REPORT_ID);
      const raw = new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
      // Some browsers prepend the report ID, some don't.
      let off;
      if (raw.length > BODY) off = 1;
      else if (raw[0] === (cmd | 0x80)) off = 0;
      else if (raw[0] === REPORT_ID && raw[1] === (cmd | 0x80)) off = 1;
      else {
        throw new Error(
          `Unexpected reply to command 0x${(cmd | 0x80).toString(16)}: ${hex(raw.slice(0, 8))}`
        );
      }
      if (raw[off] !== (cmd | 0x80)) {
        throw new Error(`Reply command 0x${raw[off].toString(16)} does not match 0x${(cmd | 0x80).toString(16)}`);
      }
      out.set(raw.subarray(off + HEADER, off + HEADER + n), i * CHUNK);
    }
    return out;
  }
}
