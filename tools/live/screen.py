#!/usr/bin/env python3
"""Mirror the screen (or one window) on the AULA F87's key lights, live over USB. Stock firmware.

Uses the same live-frame command as stream_video.py (report 6 command 0x08, cable only). Each key
shows the average colour of the part of the screen it physically covers.

Screen capture:
  - Wayland (KDE, GNOME, ...): the desktop's ScreenCast portal + PipeWire, read with GStreamer.
    The desktop asks which screen or window to share the first time; the choice is remembered
    (--pick asks again).
  - X11: ffmpeg x11grab.

usage:
  screen.py [--fps 30] [--fit stretch|crop|pad] [--window] [--gray] [--saturation 1.3] [--gamma 1.0]
            [--brightness 1.0] [--invert] [--cursor] [--pick] [--backend auto|portal|x11]
Stop with Ctrl+C; the keyboard goes back to its own lighting shortly after.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stream_video as sv  # noqa: E402  (key layout and the live-frame sender)

W, H = sv.GRID_W, sv.GRID_H              # sampling grid: 4 pixels per key unit
TOKEN_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "f87-tools")
RESEND_S = 0.1                           # repeat the last frame this often when the screen is still


# ---------------------------------------------------------------- Wayland: portal + PipeWire
class Portal:
    """Minimal client for org.freedesktop.portal.ScreenCast."""
    DEST, PATH = "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
    IFACE = "org.freedesktop.portal.ScreenCast"

    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.n = 0
        self.session = None

    def _call(self, method, sig, args):
        Gio, GLib = self.Gio, self.GLib
        return self.bus.call_with_unix_fd_list_sync(self.DEST, self.PATH, self.IFACE, method, GLib.Variant(sig, args),
                                                    None, Gio.DBusCallFlags.NONE, -1, None, None)

    def _request(self, method, sig, args, options):
        """Call a portal method that answers through a Request object's Response signal."""
        GLib = self.GLib
        self.n += 1
        token = f"f87_{os.getpid()}_{self.n}"
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        options = {**options, "handle_token": GLib.Variant("s", token)}
        loop, out = GLib.MainLoop(), {}

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            out["code"], out["results"] = params.unpack()
            loop.quit()

        sub = self.bus.signal_subscribe(None, "org.freedesktop.portal.Request", "Response", path, None,
                                        self.Gio.DBusSignalFlags.NONE, on_response)
        try:
            self._call(method, sig, (*args, options))
            loop.run()
        finally:
            self.bus.signal_unsubscribe(sub)
        if out["code"] == 1:
            sys.exit("Screen sharing was cancelled.")
        if out["code"] != 0:
            sys.exit(f"The screen-sharing portal refused {method} (code {out['code']}).")
        return out["results"]

    def start(self, window, cursor, pick):
        """Ask for a screen (or window). Returns (pipewire fd, node id)."""
        GLib = self.GLib
        kind = "window" if window else "monitor"
        token_file = os.path.join(TOKEN_DIR, f"screen-token-{kind}")
        r = self._request("CreateSession", "(a{sv})", (),
                          {"session_handle_token": GLib.Variant("s", f"f87_{os.getpid()}")})
        self.session = r["session_handle"]
        opts = {"types": GLib.Variant("u", 2 if window else 1), "multiple": GLib.Variant("b", False),
                "cursor_mode": GLib.Variant("u", 2 if cursor else 1), "persist_mode": GLib.Variant("u", 2)}
        if not pick and os.path.exists(token_file):
            opts["restore_token"] = GLib.Variant("s", open(token_file).read().strip())
        self._request("SelectSources", "(oa{sv})", (self.session,), opts)
        r = self._request("Start", "(osa{sv})", (self.session, ""), {})
        if r.get("restore_token"):
            os.makedirs(TOKEN_DIR, exist_ok=True)
            with open(token_file, "w") as f:
                f.write(r["restore_token"])
        streams = r.get("streams") or []
        if not streams:
            sys.exit("The portal returned no stream.")
        node, props = streams[0]
        size = props.get("size")
        print(f"sharing {kind}" + (f" ({size[0]}x{size[1]})" if size else "") + f", PipeWire node {node}")
        res, fds = self.bus.call_with_unix_fd_list_sync(
            self.DEST, self.PATH, self.IFACE, "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (self.session, {})),
            None, self.Gio.DBusCallFlags.NONE, -1, None, None)
        return fds.get(res.unpack()[0]), node

    def close(self):
        if self.session:
            try:
                self.bus.call_sync(self.DEST, self.session, "org.freedesktop.portal.Session", "Close", None, None,
                                   self.Gio.DBusCallFlags.NONE, -1, None)
            except Exception:
                pass
            self.session = None


class PortalCapture:
    def __init__(self, a):
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
        except (ImportError, ValueError):
            sys.exit("needs python3-gobject and GStreamer (gstreamer1, gstreamer1-plugins-base, pipewire-gstreamer)")
        Gst.init(None)
        if not Gst.ElementFactory.find("pipewiresrc"):
            sys.exit("GStreamer has no pipewiresrc; install pipewire-gstreamer")
        self.Gst = Gst
        self.portal = Portal()
        fd, node = self.portal.start(a.window, a.cursor, a.pick)
        fit = {"stretch": "videoscale method=bilinear2 add-borders=false",
               "pad": "videoscale method=bilinear2 add-borders=true",
               "crop": f"aspectratiocrop aspect-ratio={W}/{H} ! videoscale method=bilinear2"}[a.fit]
        desc = (f"pipewiresrc fd={fd} path={node} do-timestamp=true keepalive-time={int(RESEND_S * 1000)} ! "
                f"videorate drop-only=true max-rate={max(1, round(a.fps))} ! {fit} ! "
                f"video/x-raw,width={W},height={H},pixel-aspect-ratio=1/1 ! videoconvert ! "
                f"video/x-raw,format=RGB ! appsink name=sink max-buffers=1 drop=true sync=false")
        self.pipe = Gst.parse_launch(desc)
        self.sink = self.pipe.get_by_name("sink")
        self.pipe.set_state(Gst.State.PLAYING)

    def frame(self, timeout_s):
        """Latest frame as a (H*W, 3) uint8 array, or None if nothing new arrived in time."""
        Gst = self.Gst
        msg = self.pipe.get_bus().pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if msg:
            if msg.type == Gst.MessageType.EOS:
                raise EOFError("screen sharing ended")
            err, dbg = msg.parse_error()
            raise RuntimeError(f"capture failed: {err.message}")
        sample = self.sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
        if sample is None:
            return None
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            data = np.frombuffer(info.data, np.uint8)
            stride = len(data) // H                  # GStreamer pads RGB rows to 4 bytes
            return data[:stride * H].reshape(H, stride)[:, :W * 3].reshape(H * W, 3).copy()
        finally:
            buf.unmap(info)

    def close(self):
        self.pipe.set_state(self.Gst.State.NULL)
        self.portal.close()


# ---------------------------------------------------------------- X11: ffmpeg
class X11Capture:
    def __init__(self, a):
        if not shutil.which("ffmpeg"):
            sys.exit("ffmpeg not found")
        fit = {
            "stretch": f"scale={W}:{H}:flags=area",
            "crop": f"crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})',scale={W}:{H}:flags=area",
            "pad": f"scale={W}:{H}:flags=area:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
        }[a.fit]
        if a.window:
            print("--window is only available through the Wayland portal; capturing the whole X screen")
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-framerate", str(a.fps),
             "-draw_mouse", "1" if a.cursor else "0", "-i", os.environ.get("DISPLAY", ":0"),
             "-vf", f"{fit},format=rgb24", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)

    def frame(self, timeout_s):
        data = self.proc.stdout.read(W * H * 3)
        if len(data) < W * H * 3:
            raise EOFError("ffmpeg stopped")
        return np.frombuffer(data, np.uint8).reshape(H * W, 3)

    def close(self):
        self.proc.kill()


# ---------------------------------------------------------------- mirroring
def make_sampler(a):
    """Returns a function frame (H*W, 3) -> {led (col, row): (r, g, b)}."""
    regions = sv.key_regions()
    leds = list(regions)
    weights = np.zeros((len(leds), W * H), np.float32)
    for k, led in enumerate(leds):
        weights[k, regions[led]] = 1.0 / len(regions[led])
    lut = np.array([min(255, round(255 * ((v / 255) ** a.gamma) * a.brightness)) for v in range(256)], np.uint8)
    if a.invert:
        lut = lut[::-1].copy()

    def sample(px):
        rgb = weights @ px.astype(np.float32)                  # average colour of each key's area
        grey = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        if a.gray:
            rgb = np.repeat(grey[:, None], 3, axis=1)
        elif a.saturation != 1.0:
            rgb = grey[:, None] + (rgb - grey[:, None]) * a.saturation
        out = lut[np.clip(np.rint(rgb), 0, 255).astype(np.uint8)]
        return {led: tuple(int(v) for v in out[k]) for k, led in enumerate(leds)}

    return sample


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fps", type=float, default=30, help="frames per second to send (default 30)")
    ap.add_argument("--fit", choices=("stretch", "crop", "pad"), default="stretch",
                    help="how to fit the screen onto the keyboard (default stretch)")
    ap.add_argument("--window", action="store_true", help="share one window instead of a whole screen (Wayland)")
    ap.add_argument("--pick", action="store_true", help="ask again which screen/window to share")
    ap.add_argument("--cursor", action="store_true", help="include the mouse pointer")
    ap.add_argument("--gray", action="store_true", help="black and white instead of colour")
    ap.add_argument("--saturation", type=float, default=1.3,
                    help="colour boost; averaged screen areas look washed out (default 1.3, 1 = as is)")
    ap.add_argument("--gamma", type=float, default=1.0, help="brightness curve, >1 = darker mid-tones")
    ap.add_argument("--brightness", type=float, default=1.0, help="0..1 scale (default 1)")
    ap.add_argument("--invert", action="store_true", help="swap light and dark")
    ap.add_argument("--backend", choices=("auto", "portal", "x11"), default="auto",
                    help="screen capture method (default: portal on Wayland, x11 otherwise)")
    ap.add_argument("--device", help="hidraw node (default: autodetect)")
    a = ap.parse_args()
    if a.fps <= 0:
        ap.error("--fps must be positive")

    backend = a.backend
    if backend == "auto":
        backend = "portal" if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland" \
            else "x11"
    lights = sv.LiveLights(a.device)                # fail on a missing keyboard before asking for the screen
    sample = make_sampler(a)
    cap = PortalCapture(a) if backend == "portal" else X11Capture(a)
    print("mirroring; Ctrl+C to stop")

    period = 1.0 / a.fps
    sent = 0
    total_write = worst = 0.0
    colours = None
    start = time.monotonic()
    try:
        while True:
            px = cap.frame(RESEND_S)
            if px is not None:
                colours = sample(px)
            if colours is None:                     # nothing captured yet
                continue
            t0 = time.monotonic()
            # repeat the last frame when the screen is still, or the keyboard drops out of live mode
            lights.send(lambda c, r: colours.get((c, r), (0, 0, 0)))
            took = time.monotonic() - t0
            total_write += took
            worst = max(worst, took)
            sent += 1
            wait = period - (time.monotonic() - t0)
            if wait > 0 and px is not None:
                time.sleep(wait)
    except KeyboardInterrupt:
        pass
    except (EOFError, RuntimeError) as e:
        print(e)
    finally:
        try:
            lights.black()
        finally:
            cap.close()
            lights.close()
    secs = time.monotonic() - start
    if sent:
        print(f"{sent} frames in {secs:.0f} s ({sent / secs:.1f} fps), "
              f"USB write avg {total_write / sent * 1000:.1f} ms / slowest {worst * 1000:.1f} ms")


if __name__ == "__main__":
    main()
