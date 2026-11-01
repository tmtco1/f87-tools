// Firmware panel: load a firmware image, patch it, download it (flash with sinowisp).
import { identify, applyPatches, parseIhx, blobToIhx, BOOT_ANIMS, EFFECT_BLOBS, FW_SIZE } from "./firmware.js";

const $ = (s) => document.querySelector(s);

const BASE_URL = "https://raw.githubusercontent.com/tmtco1/f87fw/main/firmware/base_f87_decrypted.bin";
const OUT_NAME = "f87_patched.bin";
const BOOT_LABELS = {
  fkeys: "F-key sweep", wipe: "Wipe", rainbow_frow: "Rainbow F-row", tmtco: "T-M-T-C-O ripple",
};

export function initFirmware() {
  const fw = { source: null, name: "", id: null, output: null, customFx: [] };
  const el = {
    get: $("#fw-get"), open: $("#fw-open"), idText: $("#fw-id"), opts: $("#fw-options"),
    download: $("#fw-download"), status: $("#fw-status"), summary: $("#fw-summary"), boot: $("#fw-boot"),
    life: $("#fw-life"), fx: $("#fw-fx"), fxList: $("#fw-fx-list"),
  };

  for (const [key, p] of Object.entries(BOOT_ANIMS)) {
    const o = document.createElement("option");
    o.value = key;
    o.textContent = `${BOOT_LABELS[key] || key}: ${p.about}`;
    el.boot.append(o);
  }

  const status = (text, kind = "") => { el.status.textContent = text; el.status.dataset.kind = kind; };

  async function setSource(bytes, name) {
    fw.source = bytes;
    fw.name = name;
    fw.id = await identify(bytes);
    if (fw.id.kind === "stock") {
      el.idText.textContent = `${name}: AULA F87 base firmware. Any settings and key assignments in it are kept.`;
    } else if (fw.id.kind === "patched") {
      el.idText.textContent = `${name}: AULA F87 base firmware with earlier patches. They are undone first, so choose everything you want below.`;
    } else {
      el.idText.textContent = `${name}: ${fw.id.reason}. It can't be patched here.`;
    }
    el.idText.dataset.kind = fw.id.kind;
    el.opts.disabled = fw.id.kind === "unknown";
    status("");
    refresh();
  }

  function options() {
    const v = (id) => $(id).value.trim();
    const effects = [];
    // same order as patch_firmware.py (--badapple, then --life), so the outputs match byte for byte
    if (EFFECT_BLOBS.badapple && $("#fw-badapple").checked) effects.push({ ...blobToIhx(EFFECT_BLOBS.badapple), name: "Bad Apple" });
    if (el.life.checked) effects.push({ ...blobToIhx(EFFECT_BLOBS.life), name: "Game of Life" });
    effects.push(...fw.customFx);
    return {
      manufacturer: v("#fw-manufacturer"), product: v("#fw-product"), bt3: v("#fw-bt3"), bt5: v("#fw-bt5"),
      bootAnim: el.boot.value || undefined, effects,
    };
  }

  function refresh() {
    el.summary.textContent = "";
    el.summary.dataset.kind = "";
    fw.output = null;
    if (fw.source && fw.id.kind !== "unknown") {
      try {
        const r = applyPatches(fw.id.image, options());
        if (r.log.length || fw.id.kind === "patched") {
          fw.output = r.image;
          const undo = fw.id.kind === "patched" ? ["earlier patches undone"] : [];
          el.summary.textContent = [...undo, ...r.log].join(" · ");
        } else {
          el.summary.textContent = "Choose at least one patch.";
        }
      } catch (e) {
        el.summary.textContent = e.message;
        el.summary.dataset.kind = "error";
      }
    }
    el.download.disabled = !fw.output;
  }

  el.get.addEventListener("click", async () => {
    el.get.disabled = true;
    status("Downloading from tmtco1/f87fw…", "busy");
    try {
      const res = await fetch(BASE_URL, { cache: "no-cache" });
      if (!res.ok) throw new Error(`GitHub answered ${res.status}`);
      const bytes = new Uint8Array(await res.arrayBuffer());
      await setSource(bytes, "base_f87_decrypted.bin");
      if (fw.id.kind !== "stock") throw new Error("the downloaded file isn't the expected base firmware");
    } catch (e) {
      status(`Couldn't get the base firmware: ${e.message}. Download it from github.com/tmtco1/f87fw and open it instead.`, "error");
    } finally {
      el.get.disabled = false;
    }
  });

  el.open.addEventListener("change", async () => {
    const f = el.open.files[0];
    el.open.value = "";
    if (!f) return;
    const bytes = new Uint8Array(await f.arrayBuffer());
    if (bytes.length !== FW_SIZE) {
      status(`${f.name} is ${bytes.length} bytes; a firmware image is ${FW_SIZE}.`, "error");
      return;
    }
    await setSource(bytes, f.name);
  });

  el.download.addEventListener("click", () => {
    if (!fw.output) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([fw.output], { type: "application/octet-stream" }));
    a.download = OUT_NAME;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    status(`Saved ${OUT_NAME}. Flash it with the command below.`, "ok");
  });

  el.fx.addEventListener("change", async () => {
    for (const f of el.fx.files) {
      try {
        fw.customFx.push({ ...parseIhx(await f.text()), name: f.name });
      } catch (e) {
        status(`${f.name}: ${e.message}`, "error");
      }
    }
    el.fx.value = "";
    renderFx();
    refresh();
  });
  function renderFx() {
    el.fxList.textContent = "";
    fw.customFx.forEach((fx, i) => {
      const li = document.createElement("li");
      li.textContent = `${fx.name} (${fx.hi - fx.lo + 1} bytes, effect ${fx.bytes.get(fx.lo + 9)}) `;
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "quiet";
      rm.textContent = "Remove";
      rm.onclick = () => { fw.customFx.splice(i, 1); renderFx(); refresh(); };
      li.append(rm);
      el.fxList.append(li);
    });
  }
  el.opts.addEventListener("input", refresh);
  el.opts.addEventListener("change", refresh);

  if (EFFECT_BLOBS.badapple) $("#fw-badapple-row").hidden = false;
  refresh();
}
