import {
  VID, PID, USAGE_PAGE, REPORT_ID, EFFECTS, ZONES, ZONE_MODES, ZONE_COLORS, KEYS, LAYOUT,
} from "./constants.js";
import { Device, slotOffset, palOffset } from "./device-config.js";
import { hex } from "./hid-transport.js";
import { initFirmware } from "./fw-ui.js";

const $ = (s, r = document) => r.querySelector(s);

const state = { dev: null, cfg: null, pal: null, keyColors: new Map(), profile: 0 };

// ---------- log & status ----------
const logEl = $("#log");
function log(msg) {
  logEl.textContent += msg + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}
function setStatus(kind, text) {
  const el = $("#status");
  el.dataset.state = kind;
  el.textContent = text;
}
function setEnabled(on) {
  for (const id of ["keys-section", "effect-section", "zone-section", "raw-section"]) $("#" + id).disabled = !on;
  $("#intro").hidden = on;
}
const errText = (e) => (e && e.message) || String(e);

// ---------- helpers ----------
const toHex = ([r, g, b]) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
const fromHex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const effectById = (id) => EFFECTS.find((e) => e.id === id);
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** Run a device operation; report failures in status + log, never leave the UI half-updated. */
async function run(label, op) {
  if (!state.dev) return;
  try {
    return await op(state.dev);
  } catch (e) {
    log(`${label} failed: ${errText(e)}`);
    setStatus("error", `${label} failed: ${errText(e)}`);
    return undefined;
  }
}

// ---------- effect panel ----------
const effectsEl = $("#effects");
for (const e of EFFECTS) {
  const li = document.createElement("li");
  const id = `fx-${e.id}`;
  li.innerHTML = `<input type="radio" name="fx" id="${id}" value="${e.id}"><label for="${id}"><span class="n">${String(e.id).padStart(2, "0")}</span>${e.name}</label>`;
  effectsEl.append(li);
}
effectsEl.addEventListener("change", (ev) => {
  const id = Number(ev.target.value);
  run("Set effect", async (d) => {
    state.cfg = await d.setEffect(id);
    renderEffect();
    setStatus("ok", `Effect: ${effectById(id).name}`);
  });
});

const slotInfo = () => {
  const id = state.cfg[0x0a];
  const fx = effectById(id);
  if (!fx || id < 1 || id > 18) return null;
  const o = slotOffset(id);
  return { id, fx, brightness: state.cfg[o], speed: state.cfg[o + 1] >> 4, slot: state.cfg[o + 1] & 0x0f };
};

function renderEffect() {
  if (!state.cfg) return;
  const cur = state.cfg[0x0a];
  const radio = $(`#fx-${cur}`);
  for (const r of effectsEl.querySelectorAll("input")) r.checked = false;
  if (radio) radio.checked = true;

  const info = slotInfo();
  const set = (id, show, val) => {
    $("#p-" + id).hidden = !show;
    if (show && val !== undefined) {
      const inp = $("#" + id);
      inp.value = val;
      inp.nextElementSibling.textContent = val;
    }
  };
  set("brightness", !!info?.fx.brightness, info?.brightness);
  set("speed", !!info?.fx.speed, info?.speed);
  $("#p-colour").hidden = !info?.fx.colour;
  $("#colour-hint").hidden = !info?.fx.colour;
  if (info?.fx.colour) renderSwatches(info);
}

function renderSwatches(info) {
  const box = $("#swatches");
  box.textContent = "";
  for (let s = 0; s < 8; s++) {
    const b = document.createElement("button");
    b.type = "button";
    b.role = "radio";
    b.dataset.slot = s;
    b.setAttribute("aria-checked", String(info.slot === s));
    if (s < 7) {
      const o = palOffset(info.id, s);
      const rgb = [...state.pal.slice(o, o + 3)];
      b.style.setProperty("--c", toHex(rgb));
      b.innerHTML = `<i></i><span>${toHex(rgb).slice(1)}</span>`;
      b.title = `Slot ${s + 1}`;
    } else {
      b.classList.add("multi");
      b.innerHTML = `<i></i><span>multi</span>`;
      b.title = "Multicolour";
    }
    box.append(b);
  }
}

$("#swatches").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-slot]");
  const info = state.cfg && slotInfo();
  if (!b || !info) return;
  const slot = Number(b.dataset.slot);
  if (slot === info.slot && slot < 7) {
    const picker = $("#slot-picker");
    picker.value = b.style.getPropertyValue("--c");
    picker.dataset.slot = slot;
    picker.dataset.fx = info.id;
    picker.showPicker?.() ?? picker.click();
  } else {
    run("Select colour", async (d) => {
      state.cfg = await d.setParam(info.id, { slot });
      renderEffect();
    });
  }
});
$("#slot-picker").addEventListener("change", (ev) => {
  const { slot, fx } = ev.target.dataset;
  const rgb = fromHex(ev.target.value);
  run("Set colour", async (d) => {
    state.pal = await d.setPaletteColor(Number(fx), Number(slot), rgb);
    renderEffect();
  });
});

for (const key of ["brightness", "speed"]) {
  const inp = $("#" + key);
  const send = debounce((v) => {
    const info = slotInfo();
    if (!info) return;
    run(`Set ${key}`, async (d) => {
      state.cfg = await d.setParam(info.id, { [key]: v });
      renderEffect();
    });
  }, 150);
  inp.addEventListener("input", () => {
    inp.nextElementSibling.textContent = inp.value;
    send(Number(inp.value));
  });
}

// ---------- zones ----------
const zonesEl = $("#zones");
const zoneDefs = [["bar", "Light bar"], ["front", "Front light"]];
for (const [key, title] of zoneDefs) {
  const wrap = document.createElement("div");
  wrap.className = "zone";
  wrap.dataset.zone = key;
  const opts = (arr) => arr.map((t, i) => `<option value="${i}">${t}</option>`).join("");
  wrap.innerHTML = `
    <h2>${title}</h2>
    <label class="field">Mode <select data-f="0">${opts(ZONE_MODES)}</select></label>
    <label class="field">Colour <select data-f="1">${opts(ZONE_COLORS)}</select></label>
    <div class="param"><label>Brightness</label><input type="range" min="0" max="4" step="1" data-f="2"><output></output></div>
    <div class="param"><label>Speed</label><input type="range" min="0" max="4" step="1" data-f="3"><output></output></div>`;
  zonesEl.append(wrap);
}
function renderZones() {
  if (!state.cfg) return;
  for (const wrap of zonesEl.children) {
    const base = ZONES[wrap.dataset.zone];
    for (const el of wrap.querySelectorAll("[data-f]")) {
      el.value = state.cfg[base + Number(el.dataset.f)];
      if (el.type === "range") el.nextElementSibling.textContent = el.value;
    }
  }
}
const sendZone = debounce((base, f, v) => {
  run("Set light", async (d) => {
    state.cfg = await d.setZone(base, f, v);
    renderZones();
    renderEffect();
  });
}, 150);
zonesEl.addEventListener("input", (ev) => {
  const el = ev.target;
  if (!el.dataset.f) return;
  if (el.type === "range") el.nextElementSibling.textContent = el.value;
  sendZone(ZONES[el.closest(".zone").dataset.zone], Number(el.dataset.f), Number(el.value));
});

// ---------- keyboard ----------
const board = $("#board");
const keyEls = new Map();
for (const row of LAYOUT) {
  const r = document.createElement("div");
  r.className = "row";
  for (const item of row) {
    if (typeof item === "number") {
      const g = document.createElement("span");
      g.style.setProperty("--w", item);
      g.className = "gap";
      r.append(g);
      continue;
    }
    const [name, label, w] = item;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "key";
    b.style.setProperty("--w", w);
    b.dataset.idx = KEYS[name];
    b.title = name;
    b.textContent = label;
    keyEls.set(KEYS[name], b);
    r.append(b);
  }
  board.append(r);
}
function paintKeyEl(i) {
  const el = keyEls.get(i);
  const c = state.keyColors.get(i) ?? [0, 0, 0];
  el.style.setProperty("--k", toHex(c));
  const lum = (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255;
  el.classList.toggle("lit", c[0] + c[1] + c[2] > 0);
  el.classList.toggle("light", lum > 0.55);
}
const renderKeys = () => keyEls.forEach((_, i) => paintKeyEl(i));
for (const i of keyEls.keys()) state.keyColors.set(i, [0, 0, 0]);

let painting = false;
const paint = (el) => {
  const i = Number(el.dataset.idx);
  state.keyColors.set(i, fromHex($("#paint").value));
  paintKeyEl(i);
};
board.addEventListener("pointerdown", (ev) => {
  const el = ev.target.closest(".key");
  if (!el) return;
  if (ev.button === 2) return;
  painting = true;
  paint(el);
  ev.preventDefault();
});
board.addEventListener("pointerover", (ev) => {
  const el = ev.target.closest(".key");
  if (painting && el) paint(el);
});
addEventListener("pointerup", () => (painting = false));
board.addEventListener("contextmenu", (ev) => {
  const el = ev.target.closest(".key");
  if (!el) return;
  ev.preventDefault();
  $("#paint").value = toHex(state.keyColors.get(Number(el.dataset.idx)) ?? [0, 0, 0]);
});
board.addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter" && ev.key !== " ") return;
  const el = ev.target.closest(".key");
  if (el) { ev.preventDefault(); paint(el); }
});
$("#fill").addEventListener("click", () => {
  const c = fromHex($("#paint").value);
  for (const i of keyEls.keys()) state.keyColors.set(i, [...c]);
  renderKeys();
});
$("#clear").addEventListener("click", () => {
  for (const i of keyEls.keys()) state.keyColors.set(i, [0, 0, 0]);
  renderKeys();
});
$("#profile").addEventListener("change", () => {
  state.profile = Number($("#profile").value);
  reloadKeys();
});
$("#reload").addEventListener("click", () => reloadKeys());
async function reloadKeys() {
  await run("Reload profile", async (d) => {
    state.keyColors = await d.readKeyColors(state.profile);
    renderKeys();
    log(`Loaded profile ${state.profile + 1}`);
  });
}
$("#upload").addEventListener("click", () =>
  run("Upload", async (d) => {
    setStatus("busy", "Uploading…");
    state.cfg = await d.writeKeyColorsAndShow(state.profile, state.keyColors);
    renderEffect();
    renderZones();
    setStatus("ok", `Profile ${state.profile + 1} uploaded, custom effect on`);
  })
);

// ---------- advanced ----------
const parseByte = (s) => parseInt(String(s).trim().replace(/^0x/i, ""), 16);
$("#raw-read").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const cmd = parseByte(f.get("cmd")), arg = parseByte(f.get("arg")), size = Number(f.get("size"));
  if ([cmd, arg, size].some(Number.isNaN) || size < 1 || size > 4096) return log("Raw read: invalid command, arg or size");
  run("Raw read", async (d) => {
    const data = await d.rawRead(cmd, arg, size);
    log(`read 0x${(cmd & 0x7f).toString(16)} arg ${arg} (${data.length} bytes)\n${hex(data)}`);
  });
});
$("#raw-write").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const cmd = parseByte(f.get("cmd")), arg = parseByte(f.get("arg"));
  const bytes = (String(f.get("data")).match(/[0-9a-f]{2}/gi) || []).map((h) => parseInt(h, 16));
  if (Number.isNaN(cmd) || Number.isNaN(arg)) return log("Raw write: invalid command or arg");
  if (!bytes.length) return log("Raw write: payload is empty");
  run("Raw write", async (d) => {
    await d.rawWrite(cmd, arg, Uint8Array.from(bytes));
    log(`wrote ${bytes.length} bytes to 0x${cmd.toString(16)} arg ${arg}`);
  });
});
$("#dump").addEventListener("click", () =>
  run("Dump", async (d) => {
    const cfg = await d.rawRead(0x84, 0, 128);
    const pal = await d.rawRead(0x8a, 0, 512);
    log(`config\n${hex(cfg)}\n\npalette\n${hex(pal)}`);
  })
);
$("#factory-reset").addEventListener("click", () => {
  if (!confirm("Reset all lighting settings to factory defaults? Your effects, colours and per-key profiles will be lost.")) return;
  run("Factory reset", async (d) => {
    setStatus("busy", "Resetting…");
    state.cfg = await d.factoryReset();
    state.pal = await d.readPalette();
    state.keyColors = await d.readKeyColors(state.profile);
    renderEffect();
    renderZones();
    renderKeys();
    setStatus("ok", "Lighting reset to factory defaults");
    log("Factory reset: config, palette and per-key profiles 1-5 restored");
  });
});
$("#clear-log").addEventListener("click", () => (logEl.textContent = ""));

// ---------- connection ----------
const hasReport6 = (d) =>
  d.collections.some((c) => c.featureReports?.some((r) => r.reportId === REPORT_ID));

async function attach(hid) {
  setStatus("busy", "Connecting…");
  try {
    if (!hid.opened) await hid.open();
    state.dev = new Device(hid);
    setStatus("busy", "Reading settings…");
    state.cfg = await state.dev.readConfig();
    state.pal = await state.dev.readPalette();
    state.profile = 0;
    $("#profile").value = "0";
    state.keyColors = await state.dev.readKeyColors(0);
    setEnabled(true);
    renderEffect();
    renderZones();
    renderKeys();
    $("#connect").textContent = "Reconnect";
    setStatus("ok", `Connected: ${hid.productName || "keyboard"}`);
    log(`Connected to ${hid.productName} (${hid.vendorId.toString(16)}:${hid.productId.toString(16)})`);
  } catch (e) {
    state.dev = null;
    setEnabled(false);
    setStatus("error", errText(e));
    log(`Connect failed: ${errText(e)}`);
    try { if (hid.opened) await hid.close(); } catch { /* already gone */ }
  }
}

async function connect() {
  try {
    const picked = await navigator.hid.requestDevice({
      filters: [{ vendorId: VID, productId: PID, usagePage: USAGE_PAGE }],
    });
    if (!picked.length) return setStatus(state.dev ? "ok" : "off", state.dev ? "Connected" : "Not connected");
    const hid = picked.find(hasReport6);
    if (!hid) {
      setStatus("error", "That interface has no feature report 6. Choose the other entry for this keyboard.");
      return;
    }
    if (state.dev?.hid && state.dev.hid !== hid && state.dev.hid.opened) await state.dev.hid.close();
    await attach(hid);
  } catch (e) {
    setStatus("error", errText(e));
    log(`Connect failed: ${errText(e)}`);
  }
}

// ---------- firmware ----------
const startFirmwarePanel = () => initFirmware();

function init() {
  setEnabled(false);
  if (!("hid" in navigator)) {
    const insecure = !window.isSecureContext;
    $("#unsupported").textContent = insecure
      ? `WebHID only works on secure pages, and this one was opened as ${location.origin}. Open it over https, ` +
        "or from http://localhost / http://127.0.0.1 on the computer the keyboard is plugged into."
      : "This browser has no WebHID, so it can't talk to the keyboard. Open this page in Chrome, Edge or " +
        "another Chromium-based browser on a desktop (some privacy browsers turn WebHID off).";
    $("#unsupported").hidden = false;
    $("#connect").disabled = true;
    setStatus("error", insecure ? "WebHID needs https or localhost" : "WebHID not available");
    startFirmwarePanel();   // patching and downloading still work
    return;
  }
  startFirmwarePanel();
  $("#connect").addEventListener("click", connect);
  navigator.hid.addEventListener("disconnect", (ev) => {
    if (state.dev && ev.device === state.dev.hid) {
      state.dev = null;
      setEnabled(false);
      setStatus("error", "Keyboard disconnected");
      log("Keyboard disconnected");
    }
  });
  navigator.hid.addEventListener("connect", async (ev) => {
    if (!state.dev && ev.device.vendorId === VID && ev.device.productId === PID && hasReport6(ev.device)) {
      await attach(ev.device);
    }
  });
  navigator.hid.getDevices().then(async (list) => {
    const hid = list.find((d) => d.vendorId === VID && d.productId === PID && hasReport6(d));
    if (hid) await attach(hid);
  });
}
init();
