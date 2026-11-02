#!/usr/bin/env python3
#SPDX-License-Identifier: GPL-3.0-only
"""
FFMPEG Frame Accurate Cutter App
FFACA is a User Interface to accurately preview frames and cut clips from videos. Tk based UI that harnesses ffmpeg to:

  * browse a video by key frames (a filmstrip of sampled frames),
  * let the user MARK START and MARK END at chosen key frames,
  * show the resulting ffmpeg command line,
  * offer a button to copy that command to the clipboard,
  * offer a button to execute the command, with ffmpeg output streamed
    into a log panel.

Environment notes handled automatically:
  * LD_LIBRARY_PATH=/usr/local/lib is injected into every ffmpeg/ffprobe
    subprocess, so the custom /usr/local/bin/ffmpeg build finds its shared
    libraries
  * single frames are grabbed with:  ffmpeg ... -f image2pipe -vcodec ppm pipe:1
    
instructions:
            + "click a filmstrip cell (or use the ◀ ▶ buttons) to move "
            "between key frames — the strip is a fixed-width subsection "
            "you scroll with the mouse wheel, the bar under it, or the "
            "« scroll » buttons; ◀ frame / frame ▶ step one video frame "
            "at a time between key frames; MARK START / MARK END set the "
            "cut at the exact current position (fast copy snaps it to "
            "the nearest I-frame — accurate keeps it frame exact); the "
            "ffmpeg command appears in the black panel. ")
"""

import os
import sys
import shutil
import shlex
import threading
import subprocess
import time
import tkinter as tk
from tkinter import font as tkfont
from io import BytesIO

try:
    from PIL import Image
    from PIL.ImageTk import PhotoImage as PILPhotoImage
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

FFMPEG_FALLBACK = "/usr/local/bin/ffmpeg"
FFPROBE_FALLBACK = "/usr/local/bin/ffprobe"
DEFAULT_LD = "/usr/local/lib"
PREFER = {"ff": None}   # alternate ffmpeg binary configured via the menu
THUMB_W = 140            # filmstrip thumbnail width (px)
PREVIEW_W = 512          # large preview width (px)
VISIBLE_CELLS = 8        # key-frame cells shown at once in the strip window
BAR_H = 26               # height of the app-drawn scrollbar bar
MAX_KEYFRAMES = 400
CLIP_FALLBACK_FILE = os.path.expanduser("~/.clipboard-fallback.txt")

# --------------------------------------------------------------------- env

def ffmpeg_env():
    """Environment for ffmpeg/ffprobe subprocesses; guarantees LD_LIBRARY_PATH."""
    env = os.environ.copy()
    ld = env.get("LD_LIBRARY_PATH", "")
    parts = [p for p in ld.split(":") if p]
    if DEFAULT_LD not in parts:
        parts.insert(0, DEFAULT_LD)
    env["LD_LIBRARY_PATH"] = ":".join(parts)
    return env


def ffmpeg_path():
    return shutil.which("ffmpeg") or (
        FFMPEG_FALLBACK if os.path.exists(FFMPEG_FALLBACK) else None)


def ffprobe_path():
    # when an alternate ffmpeg was configured, prefer the ffprobe that
    # lives next to it (same build family, matching decoders)
    if PREFER["ff"]:
        twin = os.path.join(os.path.dirname(PREFER["ff"]), "ffprobe")
        if os.path.exists(twin):
            return twin
    return shutil.which("ffprobe") or (
        FFPROBE_FALLBACK if os.path.exists(FFPROBE_FALLBACK) else None)


def ffmpeg_candidates():
    """All usable ffmpeg binaries, best first.  The menu-configured
       alternate (PREFER) wins when set; then the PATH / custom build,
       then distro fallbacks — image grabs and accurate re-encodes
       fall through this list, so codecs the first cannot decode
       (AV1, mostly) still show thumbnails/previews."""
    out = []
    for c in (PREFER["ff"], ffmpeg_path(), "/usr/bin/ffmpeg", "/bin/ffmpeg"):
        if c and os.path.exists(c) and c not in out:
            out.append(c)
    return out


def fmt_num(t):
    """12.0 -> '12', 12.3000 -> '12.3' (compact ffmpeg-friendly number)."""
    s = f"{t:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


def num6(t):
    """Full precision (up to 6 dp) for ffmpeg time arguments: key frame
       times like 16.666667 must NOT be rounded up or the seek lands one
       frame past the key frame.  Display strings keep fmt_num."""
    s = f"{t:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def fmt_clock(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:05.2f}"

# ----------------------------------------------------------------- probe

def probe(path, pump=None):
    """Return {duration,width,height,fps} (values may be None)."""
    info = {"duration": None, "width": None, "height": None,
            "fps": None, "codec": None}
    fp = ffprobe_path()
    if not fp:
        return info
    argv = [fp, "-v", "error",
            "-show_entries",
            "format=duration:stream=codec_name,width,height,r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=0", path]
    p = run_ff(argv, pump)
    for line in (p.stdout or b"").decode("utf-8", "replace").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        try:
            if k == "duration":
                info["duration"] = float(v)
            elif k == "codec":
                if info["codec"] is None:   # first stream = video
                    info["codec"] = v
            elif k == "width":
                info["width"] = int(v)
            elif k == "height":
                info["height"] = int(v)
            elif k == "r_frame_rate" and "/" in v:
                n, d = v.split("/")
                info["fps"] = float(n) / float(d)
        except (ValueError, ZeroDivisionError):
            pass
    return info


def grab_frame(video, t, width):
    """Grab the frame at time t as a PIL Image scaled to `width` px.
       Tries every ffmpeg binary (the custom build first, then the
       distro one) so codecs the first cannot decode — AV1, mostly —
       still get images."""
    if not HAVE_PIL:
        return None
    for ff in ffmpeg_candidates():
        img = _grab_frame(ff, video, t, width)
        if img is not None:
            return img
    return None


def _grab_frame(ff, video, t, width):
    argv = [ff, "-loglevel", "error",
            "-ss", f"{max(0.0, t):.6f}", "-i", video,
            "-frames:v", "1",
            "-vf", f"scale={width}:-1",
            "-f", "image2pipe", "-vcodec", "ppm", "pipe:1"]
    try:
        p = subprocess.run(argv, env=ffmpeg_env(), capture_output=True)
    except OSError:
        return None
    if not p.stdout:
        return None
    try:
        return Image.open(BytesIO(p.stdout)).convert("RGB")
    except Exception:
        return None

# -------------------------------------------------------- batch thumbnails

def run_ff(argv, pump=None):
    """subprocess.run stand-in for ffmpeg/ffprobe: when `pump` is given it
       is called in a loop while the process runs, giving the Tk window a
       chance to redraw (window stays responsive while a big file loads)."""
    try:
        p = subprocess.Popen(argv, env=ffmpeg_env(),
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    except OSError:
        return subprocess.CompletedProcess(argv, -1, b"", b"")
    if pump:
        box = [b""]
        def _drain(p=p, box=box):
            box[0] = p.stdout.read()
            try:
                p.stdout.close()
            except Exception:
                pass
        th = threading.Thread(target=_drain)
        th.start()
        while p.poll() is None:
            pump()
        th.join()
        out = box[0]
    else:
        out = p.stdout.read()
    try:
        err = p.stderr.read()
    except Exception:
        err = b""
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


def list_keyframes(video, pump=None):
    """Times (seconds, sorted) of every I-frame (keyframe) packet in the
       video, from ffprobe's packet listing.  These are the frames the
       container itself can be cut at with -c copy.  Returns None if the
       probe yields nothing usable (caller falls back to a time grid)."""
    ff = ffprobe_path()
    if not ff:
        return None
    argv = [ff, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "packet=pts_time,flags", "-of", "csv",
            video]
    p = run_ff(argv, pump)
    times = []
    for line in (p.stdout or b"").decode("utf-8", "replace").splitlines():
        parts = line.split(",")
        if len(parts) >= 3 and parts[0] == "packet" and "K" in parts[2]:
            try:
                times.append(max(0.0, float(parts[1])))
            except ValueError:
                pass
    if not times:
        return None
    times.sort()
    out = []
    for t in times:
        if not out or t - out[-1] > 1e-6:
            out.append(t)
    return out


def grab_keyframe_thumbs(video, k, width, pump=None):
    """Decodes ONLY the I-frames (-skip_frame nokey), keeps every k-th of
       them (-vsync vfr + select=not(mod(n,K)); vsync is needed or this
       ffmpeg pads the sparse stream with duplicates), and streams one
       pass of PPM images out.  Much faster than decoding every frame,
       and the images line up 1:1 with list_keyframes()[::k].  Falls
       through the ffmpeg candidates list (AV1 etc. the primary build
       cannot decode)."""
    if not HAVE_PIL:
        return []
    sel = f"select=not(mod(n\\,{k}))," if k > 1 else ""
    for ff in ffmpeg_candidates():
        argv = [ff, "-loglevel", "error",
                "-skip_frame", "nokey", "-i", video,
                "-vsync", "vfr", "-vf", f"{sel}scale={width}:-1",
                "-f", "image2pipe", "-vcodec", "ppm", "pipe:1"]
        p = run_ff(argv, pump)
        imgs = parse_ppm_stream(p.stdout or b"")
        if imgs:
            return imgs
    return []


def grab_thumbs(video, step, width, pump=None):
    """One ffmpeg decode pass -> list of PIL thumbnails at times i*step.
       Returns (images, frames_count). Used for the scrollable filmstrip
       so even long videos stay fast (single pass, capped frame count).
       Tries every ffmpeg binary until one decodes."""
    if not HAVE_PIL:
        return [], 0
    fps = 1.0 / step
    for ff in ffmpeg_candidates():
        argv = [ff, "-loglevel", "error", "-i", video,
                "-vf", f"fps={fps:.6f},scale={width}:-1",
                "-f", "image2pipe", "-vcodec", "ppm", "pipe:1"]
        p = run_ff(argv, pump)
        imgs = parse_ppm_stream(p.stdout or b"")
        if imgs:
            return imgs, 0
    return [], 0


def parse_ppm_stream(data):
    """Split a stream of concatenated binary PPM (P6) images into PIL images."""
    out = []
    i, n = 0, len(data)

    def skip_ws():
        nonlocal i
        while i < n and data[i] in (32, 9, 10, 13):
            i += 1

    def num():
        nonlocal i
        skip_ws()
        j = i
        while j < n and 48 <= data[j] <= 57:
            j += 1
        v = int(data[i:j]) if j > i else 0
        i = j
        return v

    while i < n:
        skip_ws()
        if data[i:i + 2] != b"P6":
            break
        i += 2
        w, h = num(), num()
        num()          # max value
        i += 1         # single whitespace after header
        chunk = data[i:i + w * h * 3]
        if len(chunk) < w * h * 3:
            break
        i += len(chunk)
        try:
            out.append(Image.frombytes("RGB", (w, h), chunk))
        except Exception:
            break
    return out


# -------------------------------------------------------------- command
# ---------------------------------------------------------------- command

def build_argv(mode, video, start, end, out_path, crf=23, ff=None,
               codec="libx264"):
    """Build the ffmpeg argv for copying [start,end] out of `video`.

    'copy'     : -c copy stream copy — very fast, but the cut snaps to the
                 container's key frames (can include a little extra).
    'accurate' : re-encode — the cut is frame exact; quality is `crf`
                 (lower = better, 0..51) with the chosen `codec`
                 (libx264 default, libx265 available in this build).
    `ff` optionally overrides the ffmpeg binary — needed when the source
    codec (e.g. AV1) cannot be decoded by the default build; the menu-
    configured alternate (PREFER) is used when no override is passed.
    """
    ff = ff or PREFER["ff"] or ffmpeg_path() or "ffmpeg"
    dur = end - start
    if mode == "copy":
        return [ff, "-y",
                "-ss", num6(start), "-i", video,
                "-t", num6(dur),
                "-c", "copy", out_path]
    return [ff, "-y",
            "-i", video,
            "-ss", num6(start), "-to", num6(end),
            "-c:v", codec, "-crf", str(int(crf)),
            "-c:a", "copy", out_path]


def default_output(video, start, end, mode, out_dir=None):
    stem, ext = os.path.splitext(video)
    if out_dir:
        # configured output folder instead of "next to the source"
        stem = os.path.join(out_dir, os.path.basename(stem))
    if mode == "accurate":
        ext = ".mp4"
    if not ext:
        ext = ".mp4"
    return f"{stem}_{fmt_num(start)}_{fmt_num(end)}{ext}"


def copy_to_clipboard(root, text):
    """Try xclip, wl-copy, then the Tk (X11) clipboard, then a fallback file.
       Returns (ok, message)."""
    if shutil.which("xclip"):
        try:
            p = subprocess.run(["xclip", "-selection", "clipboard"],
                               input=text.encode("utf-8"))
            if p.returncode == 0:
                return True, "command copied via xclip."
        except OSError:
            pass
    if shutil.which("wl-copy"):
        try:
            p = subprocess.run(["wl-copy"], input=text.encode("utf-8"))
            if p.returncode == 0:
                return True, "command copied via wl-copy."
        except OSError:
            pass
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        return True, "command copied via the Tk/X11 clipboard."
    except tk.TclError:
        pass
    try:
        with open(CLIP_FALLBACK_FILE, "w") as fh:
            fh.write(text + "\n")
        return True, f"no clipboard tool found — command saved to {CLIP_FALLBACK_FILE}."
    except OSError:
        return False, "could not copy to clipboard."

# ------------------------------------------------------------------- App

class App:
    def __init__(self):
        self.video = None
        self.info = None
        self.times = []
        self.current = 0
        self.start = 0.0
        self.end = 0.0
        self.play_t = 0.0           # exact playhead (seconds)
        self.frame_dt = 1.0 / 25.0  # one video frame, from probe fps
        self.mode = "copy"
        self.out_path = ""
        self.cmd_argv = []
        self.strip_mode = "batch"   # how strip thumbs were grabbed
        self.enc_codec = "libx264"  # accurate-mode encoder (menu-config)
        self.out_dir = ""           # output dir ("" = next to source)
        self.decode_ff = None       # ffmpeg binary that decodes the file
        self.alt_note = ""          # note when a secondary build is used
        self.frames = {}          # (time, width) -> PIL image
        self.keep_images = []     # PhotoImages kept alive for display
        self.cells = []           # filmstrip cells
        self.proc_lines = None
        self.proc_done = None
        self.eff_step = 1.0
        self.sel_k = 1              # keep every k-th key frame
        self.kf_mode = False        # key frames = real I-frames
        self.kf_base = []           # ALL I-frame times from ffprobe
        self.scrollable = False
        self.strip_view = None

    # ------------------------------------------------------------ helpers

    def frame_for(self, t, width):
        key = (round(t, 6), width)
        if key not in self.frames:
            self.frames[key] = grab_frame(self.video, t, width)
        return self.frames[key]

    def photo(self, pil):
        ph = PILPhotoImage(pil)
        self.keep_images.append(ph)
        return ph

    # ---------------------------------------------------------------- UI

    def make_ui(self):
        root = tk.Tk()
        root.wm_title("Keyframe Video Editor")
        self.root = root
        mono = tkfont.nametofont("TkFixedFont")

        # --- header / status
        self.status = tk.Label(root, wraplength=760, justify="left",
                               fg="#606060")
        self.status.pack()
        
        # --- open a video: single button + the standard Tk file dialog
        self.open_btn = tk.Button(root, text="Open a video file…",
                                  command=self.open_dialog)
        self.open_btn.pack()

        # --- scrollable filmstrip subsection ---------------------------
        # A tk.Canvas acts as the viewport: the key-frame cells are placed
        # on it with create_window, and its width is capped, so long
        # videos scroll (wheel / scrollbar drag / buttons) instead of
        # stretching the window.  (Tk 8.6 only gives scan/xview to canvas,
        # text and listbox — plain frames cannot scroll.)
        self.strip_win = tk.Frame(root)
        self.strip_win.pack()
        # the Tk Scrollbar of this build renders a 13 px trough with only
        # the arrows visible — useless.  The bar is therefore drawn by
        # the app on a small canvas: trough + proportional thumb + end
        # arrows, always clearly visible and comfortably clickable.
        self.strip_sb = tk.Canvas(self.strip_win, highlightthickness=0)
        self.strip_sb.pack(side="bottom")
        self.strip_view = None
        nav1 = tk.Frame(root)
        nav1.pack()
        for txt, cmd in (("|◀ first kf", self.first_key),
                         ("◀ prev key frame", self.prev_key),
                         ("next key frame ▶", self.next_key),
                         ("« scroll ◀", self.scroll_left),
                         ("scroll ▶ »", self.scroll_right),
                         ("last kf ▶|", self.last_key)):
            tk.Button(nav1, text=txt, command=cmd).pack(side="left")

        self.step_lbl = tk.Label(root, fg="#606060")
        self.step_lbl.pack()

        # --- large preview of the selected key frame
        self.preview_caption = tk.Label(root, fg="#606060")
        self.preview_caption.pack()
        self.preview = tk.Label(root)
        self.preview.pack()

        # --- navigation buttons
        nav0 = tk.Frame(root)
        nav0.pack()
        for txt, cmd in (("◀ -1 frame", self.prev_frame),
                         ("frame +1 ▶", self.next_frame)):
            tk.Button(nav0, text=txt, command=cmd).pack(side="left")
        nav = tk.Frame(root)
        nav.pack()
        for txt, cmd in (("|◀ first", self.first_key),
                         ("◀ prev key frame", self.prev_key),
                         ("next key frame ▶", self.next_key),
                         ("last ▶|", self.last_key)):
            tk.Button(nav, text=txt, command=cmd).pack(side="left")
        nav2 = tk.Frame(root)
        nav2.pack()
        for txt, cmd in (("MARK START", self.mark_start),
                         ("MARK END", self.mark_end)):
            tk.Button(nav2, text=txt, command=cmd).pack(side="left")
        # --- key-frame thinning slider + cut mode
        # slider = "keep every N-th key frame" (I-frames are found with
        # -skip_frame nokey / ffprobe; 1 = all of them).  No longer shown
        # to the user: the app picks the thinning itself (keeping all
        # key frames when they fit on screen, thinning only long enough
        # for the strip to stay scrollable).  The tk.Scale stays alive
        # (fixed at 1 + auto cap) because the strip code reads it.
        self.step_scale = tk.Scale(root, from_=1, to=100, resolution=5,
                                   orient="horizontal")
        self.step_scale.set(1)
        self.step_scale.configure(command=self.set_step)
        # NOTE: not packed — invisible to the user, control is automatic
        self.cut_mode = tk.StringVar(value="fast copy")
        self.mode_btn = tk.OptionMenu(
            root, self.cut_mode,
            "fast copy  — stream copy, snaps to key frames",
            "accurate  — re-encode, frame exact",
            command=self.pick_mode)
        self.mode_btn.pack()

        # --- crf input: only shown while the cut mode is 'accurate'
        # (it lives in a frame that is packed/unpacked on mode change)
        self.crf_win = tk.Frame(root)
        self.crf_lbl = tk.Label(self.crf_win, fg="#606060")
        self.crf_lbl["text"] = ("re-encode quality crf (0 best … 51 worst, "
                                "default 23):")
        self.crf_lbl.pack()
        # takefocus=1 so the entry CAN take keyboard focus (this build
        # refuses it otherwise); Enter on it then runs crf_enter, which
        # applies the value and blurs focus — so +/- reach the playhead
        self.crf_e = tk.Entry(self.crf_win, width=6, takefocus=1)
        self.crf_e.insert("end", "23")
        self.crf_e.pack(side="left")
        # apply the typed crf immediately: a button right of the input...
        self.crf_apply_btn = tk.Button(self.crf_win, text="Apply CRF",
                                       command=self.apply_crf)
        self.crf_apply_btn.pack(side="left")
        # ...plus event bindings for people who just type and hit Enter.
        # Applying must ALSO blur the entry's keyboard focus, otherwise
        # the + / - keys the user presses next to step frames would just
        # be typed into the crf box instead of moving the playhead.
        # (this Tk build never fires the virtual <<Enter>>/focus events,
        # so also bind the physical <Return>; harmless if the entry
        # consumes it.)  The button is the guaranteed path.
        try:
            self.crf_e.bind("<Return>", self.crf_enter)
        except tk.TclError:
            pass
        # numpad Enter generates a <KP_Enter>
        try:
            self.crf_e.bind("<KP_Enter>", self.crf_enter)
        except tk.TclError:
            pass
        for seq in ("<<Enter>>", "<<Toggle-Focus-Out>>", "<<Leave>>"):
            try:
                self.crf_e.bind(seq, self.crf_enter)
            except tk.TclError:
                pass

        # --- command panel
        self.now_lbl = tk.Label(root, fg="#202020")
        self.now_lbl.pack()
        self.cmd_panel = tk.Text(root, height=4, takefocus=0, wrap="word",
                                 bg="#1e1e1e", fg="#dcdcdc")
        self.cmd_panel.config(font=mono)
        self.cmd_panel.pack()
        self.cmd_info = tk.Label(root, justify="left", fg="#202020")
        self.cmd_info.pack()

        # --- action buttons
        self.copy_btn = tk.Button(root, text="Copy command to clipboard",
                                  command=self.copy_cmd)
        self.copy_btn.pack()
        self.run_btn = tk.Button(root, text="Run command", command=self.run_cmd)
        self.run_btn.pack()

        # --- menu bar: plain path-typed open.  The stock Tk file dialog
        # can't cope with names/links containing commas or parentheses
        # (gvfs mounts like
        # /run/user/1000/gvfs/afp-volume:host=X,user=Y,volume=Z/x(1080p).mkv),
        # so this menu entry asks for the path as one plain string instead.
        m = tk.Menu(root)
        root.config(menu=m)
        m.add_command(label="Open video file (type path)…",
                      command=self.menu_open)
        # --- va01 config: alternate ffmpeg binary + output folder, and
        # codec choice for accurate re-encode.  Tries real cascades; if
        # this Tk build has none, falls back to flat menu entries.
        self.nested_menu_ok = False
        try:
            cm = tk.Menu(root)
            cm.add_command(label="libx264 (default)",
                           command=lambda: self.pick_codec("libx264"))
            cm.add_command(label="libx265",
                           command=lambda: self.pick_codec("libx265"))
            cfg = tk.Menu(root)
            cfg.add_command(label="ffmpeg binary (alternate path)…",
                            command=self.menu_set_ffmpeg)
            cfg.add_command(label="output folder…",
                            command=self.menu_set_outdir)
            cfg.add_cascade(label="codec (accurate re-encode)",
                            menu=cm)
            m.add_cascade(label="Config", menu=cfg)
            self.nested_menu_ok = True
        except tk.TclError:
            m.add_command(label="Set ffmpeg binary…",
                          command=self.menu_set_ffmpeg)
            m.add_command(label="Set output folder…",
                          command=self.menu_set_outdir)
            m.add_command(label="Pick codec: libx264 (default)",
                          command=lambda: self.pick_codec("libx264"))
            m.add_command(label="Pick codec: libx265",
                          command=lambda: self.pick_codec("libx265"))

        # --- ffmpeg output log
        self.log = tk.Text(root, height=9, takefocus=0,
                           bg="#1e1e1e", fg="#dcdcdc")
        self.log.config(font=mono)
        self.log.pack()

        # keyboard: '+' / '-' move the playhead one video frame forward /
        # back.  A catch-all <Key> binding on root sits BELOW every
        # widget's own bindings (Tk resolves per widget first), so typing
        # in the crf entry, Return on buttons, dialogs etc. is untouched;
        # keys that no focused widget handles fall through to this.
        try:
            root.bind("<Key>", self.on_key)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ open

    def open_video(self, path):
        self.video = path
        self.frames = {}
        self.status["text"] = (
            f"reading metadata of {os.path.basename(path)}... the window "
            "stays live while ffmpeg works")
        self.root.update_idletasks()
        self.info = probe(path, pump=self.make_pump("reading metadata"))
        dur = self.info["duration"]
        if dur is None:
            self.status["text"] = (f"ffprobe could not read metadata of {path} "
                                   "— check the path and ffmpeg's libraries.")
            return
        self.start, self.end = 0.0, dur
        self.current = 0
        self.play_t = 0.0
        fps = self.info.get("fps")
        self.frame_dt = (1.0 / fps) if fps else (1.0 / 25.0)
        # which ffmpeg binary can actually DECODE this file?  (the
        # menu-configured alternate is tried first when set)
        self.detect_ffmpeg(path)
        # the real key frames of the container (I-frames); this ffprobe
        # packet scan can take a while on long / network files, so it
        # gets a pump to keep the GUI redrawing
        self.status["text"] = (
            f"scanning the container for I-frames of "
            f"{os.path.basename(path)}... (this can take a while on long "
            "or network files — the window stays live)")
        self.root.update_idletasks()
        kf = list_keyframes(path, pump=self.make_pump(
            "scanning for I-frame key frames"))
        self.kf_mode = kf is not None
        self.kf_base = kf or []
        # NOTE: the cut mode is NOT reset here: it is a user choice that
        # persists across videos (the OptionMenu still shows the old
        # selection, so self.mode must keep matching it).
        self.step_scale.set(1)
        self.rebuild_times()
        self.render_filmstrip()
        self.status["text"] = (
            f"{os.path.basename(path)} — {fmt_clock(dur)} long, "
            f"{self.info['width']}x{self.info['height']}, "
            f"{round(fps, 3) if fps else '?'} fps — "
            + (f"{len(self.kf_base)} real I-frame key frames in this file; "
               "the strip shows them (all of them, or auto-thinned if "
               "the file has so many that the strip would be huge). "
               if self.kf_mode else
               "no I-frame packets found — using a 1 s key-frame grid. ")
            + self.alt_note)
        self.set_crf_visibility()   # mode may have persisted as accurate
        self.select(0)
        self.refresh_command()

    def menu_open(self):
        """Menu entry: ask for a full path as one plain string — works
           with gvfs/network-mount links whose names contain commas,
           parentheses, accents (everything the Tk file dialog chokes on)."""
        try:
            from tkinter import simpledialog
            path = simpledialog.askstring(
                "Open video file", "Full path of the video file:",
                parent=self.root)
        except Exception:
            path = None
        if not path:
            return
        path = path.strip()
        if os.path.exists(path):
            self.open_video(path)
        else:
            self.status["text"] = f"file not found: {path}"

    # --------------------------------------------------- va01: config menu

    def detect_ffmpeg(self, path):
        """Pick the first ffmpeg binary (menu-alternate first, then PATH/
           custom build, then distro fallbacks) that can really decode
           the file; keep a note when it is not the usual one."""
        dur = (self.info or {}).get("duration") or 0
        t = min(1.0, dur * 0.5) if dur else 0.0
        self.decode_ff = None
        for c in ffmpeg_candidates():
            if _grab_frame(c, path, t, 32):
                self.decode_ff = c
                break
        first = (ffmpeg_candidates() or [None])[0]
        self.alt_note = (
            f"NB: the primary ffmpeg build cannot decode "
            f"{self.info.get('codec')} — strip, preview and accurate "
            f"re-encode transparently use {self.decode_ff} instead. "
            if self.decode_ff and first and self.decode_ff != first else "")
        return self.decode_ff

    def menu_set_ffmpeg(self):
        """Config menu: point the app at an ALTERNATE ffmpeg binary
           (anything outside the plain system/user path).  Empty input
           restores the default search order."""
        try:
            from tkinter import simpledialog
            p = simpledialog.askstring(
                "Alternate ffmpeg binary",
                "Full path of an alternate ffmpeg binary\n"
                "(leave empty to go back to the default search):",
                parent=self.root)
        except Exception:
            return
        if p is None:
            return
        p = p.strip()
        if not p:
            PREFER["ff"] = None
            self.status["text"] = ("alternate ffmpeg unset — the default "
                                   "search order is back in use.")
            self.root.update_idletasks()
        elif not os.path.exists(p):
            self.status["text"] = f"alternate ffmpeg not found: {p}"
            return
        elif not os.access(p, os.X_OK):
            self.status["text"] = (f"alternate ffmpeg exists but is not "
                                   f"executable: {p}")
            return
        else:
            PREFER["ff"] = p
            self.status["text"] = (f"alternate ffmpeg in use: {p} "
                                   "(grabs, probes and commands now "
                                   "prefer it; empty the field to reset)")
        if self.video:
            self.detect_ffmpeg(self.video)
        self.refresh_command()

    def menu_set_outdir(self):
        """Config menu: choose the output folder for the cut copies
           (default: the same folder as the source file).  A directory
           BROWSER pops up instead of typing the path."""
        try:
            from tkinter import filedialog
            initial = (self.out_dir or
                       (os.path.dirname(self.video)
                        if self.video else None) or ".")
            try:
                d = filedialog.askdirectory(
                    parent=self.root, title="Choose output folder",
                    initialdir=initial, mustexist=False)
            except TypeError:
                # older/lean builds may lack mustexist kw
                d = filedialog.askdirectory(parent=self.root,
                                            title="Choose output folder")
        except Exception:
            return
        if not d:
            # canceled: keep current setting
            return
        self.out_dir = os.path.expanduser(d)
        self.refresh_command()

    def pick_codec(self, label):
        """Config menu: encoder for accurate frame re-encode (libx264
           default, libx265 also available in this build)."""
        self.enc_codec = label.split()[0]
        self.status["text"] = (
            f"accurate re-encode codec: {self.enc_codec}")
        self.refresh_command()

    def open_dialog(self):
        """Single button that pops the standard Tk file dialog
           (filedialog.askopenfilenames, restricted to video files).  If
           several files are selected, the first one is opened."""
        try:
            from tkinter import filedialog
        except ImportError:
            self.status["text"] = ("this Tk build has no file dialog — "
                                   "pass the video path on the command "
                                   "line instead.")
            return
        d = (os.path.dirname(self.video) if self.video
             else os.path.expanduser("~"))
        vtypes = " ".join(f"*{e}" for e in self.VIDEO_EXT)
        try:
            files = filedialog.askopenfilenames(
                parent=self.root, title="Open a video file",
                initialdir=d,
                filetypes=[("Video files", vtypes), ("All files", "*")])
        except tk.TclError:
            return
        if not files:
            return
        if isinstance(files, str):   # older bindings join with ';'
            files = tuple(s for s in files.split(";") if s)
        path = files[0]
        if not os.path.exists(path):
            self.status["text"] = f"file not found: {path}"
            return
        self.open_video(path)
        if len(files) > 1:
            self.status["text"] += (" — the other files you selected were "
                                    "ignored (the app shows one video at a "
                                    "time)")

    VIDEO_EXT = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mpg",
                 ".mpeg", ".ts", ".mts", ".flv", ".wmv", ".ogv", ".m2v")


    # -------------------------------------------------------- filmstrip

    def refresh_idle(self):
        """Queue-able redraw callback (avoids root.update(ms), whose name
           is shadowed by Label.update on this Tk build)."""
        self.root.update_idletasks()

    def make_pump(self, label):
        """Callback handed to long ffmpeg/ffprobe runs: every call lets
           Tk redraw (root.update), so the window never freezes; the
           status line shows elapsed seconds while the job runs."""
        t0 = [time.monotonic()]
        n = [0]
        def tick():
            # queue an idle redraw (never call root.update(ms): in this
            # Tk build that name is shadowed by Label.update on widgets)
            self.root.after(1, self.refresh_idle)
            time.sleep(0.08)            # throttle the pump loop
            n[0] += 1
            if n[0] % 10 == 0:
                el = int(time.monotonic() - t0[0])
                self.status["text"] = (
                    f"{label} of {os.path.basename(self.video)} — "
                    f"{el}s elapsed — the window stays live, the job "
                    "is still running, just wait...")
                self.root.update_idletasks()
        return tick

    def verify_thumbs(self, times, imgs):
        """True if the batch images look like exactly the frames at the
           given times: same count, and a few sampled cells byte-match
           an exact seek grab of the same time."""
        if len(imgs) != len(times):
            return False
        if not times:
            return True
        idxs = sorted({0, len(times) // 3, (2 * len(times)) // 3,
                       len(times) - 1})
        for i in idxs:
            a = imgs[i]
            b = grab_frame(self.video, times[i], THUMB_W)
            if a is None or b is None:
                if a is None and b is None:
                    continue          # both paths failed: not a mismatch
                return False
            if a.tobytes() != b.tobytes():
                return False
        return True

    def rebuild_times(self):
        """Key frames = the video's own I-frames when available; the
           slider keeps every N-th of them so long videos stay capped
           (MAX_KEYFRAMES) with the step widened automatically."""
        if self.kf_mode and self.kf_base:
            base = self.kf_base
            k = max(1, int(float(self.step_scale.get())))
            auto = (len(base) + MAX_KEYFRAMES - 1) // MAX_KEYFRAMES
            k = max(k, auto)
            self.sel_k = k
            self.times = base[::k]
            self.eff_step = k
        else:
            dur = self.info["duration"]
            step = 1.0 * max(1, int(float(self.step_scale.get())))
            n = int(dur // step) + 1
            if n > MAX_KEYFRAMES:
                n = MAX_KEYFRAMES
                step = dur / (n - 1)
            self.times = [round(i * step, 3) for i in range(n)]
            self.eff_step = step
            self.sel_k = 1

    def render_filmstrip(self):
        """Lay the key-frame cells on a fixed-width tk.Canvas viewport.
           Scrolling is handled by the app itself (pixels), not by the
           Tk scan protocol, whose shape changed between Tk versions:
           cells are re-positioned with `coords`, the scrollbar thumb is
           updated with `set`, and wheel / click-drag on the bar / scroll
           buttons drive it.  Long videos therefore take a constant
           amount of screen space."""
        for c in self.cells:
            c["img"].destroy()
            c["lbl"].destroy()
        if self.strip_view:
            self.strip_view.destroy()
        self.cells = []

        canvas = tk.Canvas(self.strip_win, highlightthickness=0)
        canvas.pack(side="top")
        self.strip_view = canvas

        # thumbnails: only the I-frames are decoded (-skip_frame nokey)
        if HAVE_PIL:
            pump = self.make_pump("decoding key-frame thumbnails")
            if self.kf_mode:
                imgs = grab_keyframe_thumbs(self.video, self.sel_k,
                                            THUMB_W, pump=pump)
            else:
                imgs, _ = grab_thumbs(self.video, self.eff_step,
                                      THUMB_W, pump=pump)
            # The batch decode is only trusted when its images really do
            # line up 1:1 with the key-frame list.  Some containers
            # (e.g. mkv tag/keyframe cues) disagree with the decoder on
            # which frames are key frames, and the strip then drifts a
            # few frames per GOP (thumbs from the middle of scenes).
            # Sample a few cells against exact per-time seeks (what the
            # preview shows); on disagreement, re-grab every strip thumb
            # by seek — slower but always consistent with the preview.
            if not self.verify_thumbs(self.times, imgs):
                self.strip_mode = "seek"
                self.status["text"] = (
                    "this file's key-frame table and the decoded stream "
                    "disagree — re-grabbing the strip with exact seeks...")
                self.root.update_idletasks()
                imgs = []
                n = len(self.times)
                for j, t in enumerate(self.times):
                    imgs.append(grab_frame(self.video, t, THUMB_W))
                    if n > 20 and j % 10 == 9:
                        self.status["text"] = (
                            f"strip thumbs by exact seeks: {j + 1}/{n} "
                            "— the window stays live, wait a moment...")
                        self.root.after(1, self.refresh_idle)
            else:
                self.strip_mode = "batch"
        else:
            imgs = []

        cellw = THUMB_W + 14
        max_ih = max_lb_h = 0
        for i, t in enumerate(self.times):
            img = tk.Label(self.strip_win)
            lbl = tk.Label(self.strip_win, text=fmt_clock(t), fg="#505050")
            self.cells.append({"img": img, "lbl": lbl})
            if imgs and i < len(imgs):
                self.frames[(round(t, 6), THUMB_W)] = imgs[i]
            if HAVE_PIL:
                img.bind("<Button-1>", lambda e, i=i: self.select(i))
                img.bind("<Double-1>", lambda e, i=i: self.select(i))
                for seq in ("<MouseWheel>", "<ButtonMotion-1>",
                            "<Alt-B1>", "<Shift-B1>"):
                    try:
                        img.bind(seq, self.wheel)
                        lbl.bind(seq, self.wheel)
                    except tk.TclError:
                        pass      # keysym unsupported on this Tk build
            if HAVE_PIL:
                pil = self.frames.get((round(t, 6), THUMB_W))
                if pil is not None:
                    img.configure(image=self.photo(pil))
                else:
                    img.configure(image="", text=fmt_clock(t))
            else:
                img.configure(text=fmt_clock(t))
            max_ih = max(max_ih, img.winfo_reqheight())
            max_lb_h = max(max_lb_h, lbl.winfo_reqheight())

        # scroll wheel also over the canvas itself (gaps between cells)
        for seq in ("<MouseWheel>", "<ButtonMotion-1>", "<Alt-B1>",
                    "<Shift-B1>"):
            try:
                canvas.bind(seq, self.wheel)
            except tk.TclError:
                pass

        self.row_h = max_ih + max_lb_h + 12
        self.y_img = 6 + max_ih // 2
        self.y_lbl = self.row_h - 6 - max_lb_h // 2
        self.cellw = cellw
        self.content_w = 8 + len(self.times) * cellw
        visible = min(len(self.times), VISIBLE_CELLS)
        self.window_w = min(self.content_w, visible * cellw + 8)
        self.max_scroll = max(0, self.content_w - self.window_w)
        self.scroll_x = 0.0

        canvas.configure(width=self.window_w, height=self.row_h)
        self.item_ids = []
        for i in range(len(self.cells)):
            # start everything at its real place; redraws move the row
            iid = canvas.create_window(
                4 + i * cellw + cellw // 2, self.y_img,
                window=self.cells[i]["img"])
            lid = canvas.create_window(
                4 + i * cellw + cellw // 2, self.y_lbl,
                window=self.cells[i]["lbl"])
            self.item_ids.append((iid, lid))
        self.strip_win.pack_propagate(False)
        self.strip_win.configure(
            width=self.window_w,
            height=self.row_h + BAR_H + 8)
        self.strip_sb.configure(width=self.window_w, height=BAR_H)

        # scrollbar bar: click / drag jumps to that position of the row
        for seq in ("<Button-1>", "<B1-Motion>", "<B2-Motion>"):
            try:
                self.strip_sb.bind(seq, self.sb_jump)
            except tk.TclError:
                pass
        self.update_thumb()

        self.scrollable = self.max_scroll > 0
        if self.kf_mode:
            head = (f"key frames = the file's own I-frames: {len(self.kf_base)} "
                    f"in the video, showing every {self.sel_k}-th = "
                    f"{len(self.times)}; ")
        else:
            head = (f"key frames (no I-frame packets found — time grid): "
                    f"every {fmt_num(self.eff_step)} s — {len(self.times)}; ")
        self.step_lbl["text"] = (
            head + f"{max(1, self.window_w // cellw)} visible at a time "
            + ("— scroll with the mouse wheel over the strip, click/drag the "
               "bar under it, or use the « scroll » buttons."
               if self.scrollable else
               "— everything fits, no scrolling needed.")
            + ("" if self.strip_mode == "batch" else
               "  NB: this file's key-frame table disagrees with the "
               "decoded stream, so strip thumbs use exact seeks like "
               "the preview (consistent, a bit slower)."))
        self.highlight()

    def redraw_strip(self):
        if not self.strip_view or not self.item_ids:
            return
        sv = self.strip_view
        for i, (iid, lid) in enumerate(self.item_ids):
            cx = 4 + i * self.cellw + self.cellw // 2 - self.scroll_x
            sv.tk.call(sv._w, "coords", str(iid), cx, self.y_img)
            sv.tk.call(sv._w, "coords", str(lid), cx, self.y_lbl)

    def update_thumb(self):
        """Redraw the app-drawn scrollbar: a long visible trough, a
           thumb whose size matches how much of the filmstrip the
           viewport shows, and end arrows."""
        sb = self.strip_sb
        if not self.content_w:
            return
        w, h = sb.winfo_width(), BAR_H
        if w < 12:
            return
        sb.tk.call(sb._w, "delete", "withtags", "bar")
        ax = 16                        # arrow zones at both ends
        y = h // 2
        # trough: the full usable run — clearly visible
        sb.create_rectangle(ax, y - 3, w - ax, y + 3, fill="#9a9a9a",
                            outline="#707070", tags="bar")
        # thumb: proportional to the visible slice, always >= 18 px wide
        frac = min(1.0, self.window_w / float(self.content_w))
        run = w - 2 * ax
        thumb_w = max(18, int(frac * run))
        f = (self.scroll_x / self.max_scroll) if self.max_scroll else 0.0
        x0 = ax + int(f * (run - thumb_w))
        sb.create_rectangle(x0, y - 8, x0 + thumb_w, y + 8,
                            fill="#3f3f3f", outline="#101010",
                            tags="bar")
        # end arrows pointing at the scroll directions
        for cx, d in ((9, -1), (w - 9, 1)):
            sb.create_polygon(cx + 5 * d, y, cx - 4 * d, y - 5,
                              cx - 4 * d, y + 5, fill="#505050",
                              tags="bar")

    def scroll_to(self, px):
        self.scroll_x = max(0.0, min(float(self.max_scroll), float(px)))
        self.redraw_strip()
        self.update_thumb()

    def scroll_by(self, dx):
        self.scroll_to(self.scroll_x + float(dx))

    def sb_jump(self, event):
        """Click / drag on the scrollbar bar: jump to that position."""
        w = self.strip_sb.winfo_width()
        if w < 10:
            return
        f = max(0.0, min(1.0, event.x / float(w)))
        self.scroll_to(f * self.max_scroll)

    def wheel(self, event):
        d = getattr(event, "delta", None)
        if not d:                       # X11 wheel: Alt-B1 = up, others = down
            d = -120 if "Alt-B1" in str(event.name) else 120
        self.scroll_by(d / 3.0)

    def scroll_left(self):
        self.scroll_by(-max(40.0, 0.6 * self.window_w))

    def scroll_right(self):
        self.scroll_by(max(40.0, 0.6 * self.window_w))

    def set_step(self, _value=None):
        if not self.video:
            return
        self.rebuild_times()
        self.render_filmstrip()
        if self.current >= len(self.times):
            self.current = len(self.times) - 1
        self.select(self.current)
        self.refresh_command()

    def highlight(self):
        for i, c in enumerate(self.cells):
            sel = (i == self.current)
            c["img"].configure(bd=3 if sel else 1,
                               relief=tk.SUNKEN if sel else tk.RAISED)
            c["lbl"].configure(fg="#1010c0" if sel else "#505050")

    # ----------------------------------------------------- navigation

    def select(self, i):
        if not self.times:
            return
        self.current = max(0, min(len(self.times) - 1, i))
        self.play_t = self.times[self.current]
        self.update_now()
        # keep the filmstrip centred on whatever the preview now shows
        self.center_on_current()

    def on_key(self, event):
        """Catch-all keyboard handler (bound on root, under every widget):
           '+' steps the frame preview forward, '-' backward — so the
           playhead can be nudged frame by frame without clicking."""
        ch = getattr(event, "char", None)
        if not ch or not self.times:
            return
        if ch in ("+", "*", "="):
            self.next_frame()
        elif ch in ("-", "_"):
            self.prev_frame()

    def center_on_current(self):
        """Scroll the strip so the selected key frame sits (near the
           middle of) the visible window; no-op when everything already
           fits or the cell is already visible."""
        if not self.cells or self.max_scroll <= 0 or not self.cells:
            return
        cx = 4 + self.current * self.cellw + self.cellw // 2
        left = cx - self.window_w // 2
        if left < self.scroll_x - 2 or left > self.scroll_x + 2:
            self.scroll_to(left)

    def set_play_t(self, t):
        """Move the playhead to an arbitrary time (clamped to the file)."""
        if not self.times:
            return
        hi = (self.info or {}).get("duration") or self.times[-1]
        self.play_t = max(0.0, min(float(hi), float(t)))
        self.update_now()

    def update_now(self):
        """Refresh highlight / label / preview for the current playhead.
           The nearest key-frame cell is highlighted; between key frames
           the exact position is shown."""
        if not self.times:
            return
        t = self.play_t
        ci = min(range(len(self.times)),
                 key=lambda i: abs(self.times[i] - t))
        self.current = ci
        self.highlight()
        exact = abs(t - self.times[ci]) < 1e-4
        if exact:
            self.now_lbl["text"] = (f"current key frame #{ci + 1} of "
                                    f"{len(self.times)} — t = {fmt_num(t)} s "
                                    f"({fmt_clock(t)})")
            cap = f"preview — key frame #{ci + 1}"
        else:
            if ci == len(self.times) - 1:
                where = f"past key frame #{ci + 1} (the last one)"
            else:
                where = f"between key frames #{ci + 1} and #{ci + 2}"
            self.now_lbl["text"] = (
                f"current position t = {fmt_num(t)} s ({fmt_clock(t)}) — "
                f"{where}; frame steps of {fmt_num(self.frame_dt)} s — "
                "MARK START / MARK END use this exact position "
                "(frame exact in accurate mode)")
            cap = f"preview — exact position t = {fmt_num(t)} s"
        if HAVE_PIL:
            pil = self.frame_for(t, PREVIEW_W)
            if pil is not None:
                self.preview.configure(image=self.photo(pil))
                self.preview_caption["text"] = cap

    def prev_key(self):
        self.select(self.current - 1)

    def next_key(self):
        self.select(self.current + 1)

    def first_key(self):
        self.select(0)

    def last_key(self):
        self.select(len(self.times) - 1)

    def prev_frame(self):
        """One video frame earlier (works between key frames)."""
        if self.video:
            self.set_play_t(self.play_t - self.frame_dt)

    def next_frame(self):
        if self.video:
            self.set_play_t(self.play_t + self.frame_dt)

    def mark_start(self):
        if self.times:
            self.start = self.play_t
            self.refresh_command()

    def mark_end(self):
        if self.times:
            self.end = self.play_t
            self.refresh_command()

    def set_crf_visibility(self):
        """Show the crf label+input only while mode is accurate."""
        if self.mode == "accurate":
            try:
                self.crf_win.pack(after=self.mode_btn)
            except tk.TclError:
                self.crf_win.pack()
        else:
            self.crf_win.pack_forget()

    def pick_mode(self, label):
        self.mode = "accurate" if str(label).startswith("accurate") else "copy"
        self.set_crf_visibility()
        self.refresh_command()

    def unfocus_crf(self):
        """Move the keyboard focus away from the crf entry (to the root
           window, which carries the + / - playhead bindings).  This
           build's `focus` has no -clear option — the only way to drop
           the entry's focus is to give focus to another widget."""
        try:
            self.root.tk.call("focus", "-force", self.root._w)
        except (tk.TclError, AttributeError):
            pass

    def apply_crf(self):
        """Apply CRF button: rebuild the command AND drop the crf entry
           focus so + / - keys then work for the playhead."""
        self.refresh_command()
        self.unfocus_crf()

    def crf_enter(self, event):
        """Return pressed while the crf entry is in focus: same as the
           Apply CRF button (apply + release focus)."""
        self.refresh_command()
        self.unfocus_crf()

    def crf_value(self):
        """Read the crf from the Entry; clamp to the libx264 range."""
        try:
            v = int(float(self.crf_e.get()))
        except (ValueError, tk.TclError):
            v = 23
        return max(0, min(51, v))

    # ------------------------------------------------------ command box

    def snap_key(self, t):
        """Nearest true I-frame (all of them, not just the thinned ones
           shown in the strip) — where -c copy can actually cut."""
        base = self.kf_base if self.kf_mode and self.kf_base else self.times
        if not base:
            return float(t)
        return base[min(range(len(base)),
                        key=lambda i: abs(base[i] - t))]

    def refresh_command(self):
        if not self.video:
            return
        s, e = self.start, self.end
        note = ""
        if self.mode == "copy":
            ks, ke = self.snap_key(s), self.snap_key(e)
            if abs(ks - s) > 1e-6 or abs(ke - e) > 1e-6:
                note = (" — fast copy snaps the cut to the nearest I-frames;"
                        " switch to accurate mode for these exact"
                        " positions")
            s, e = ks, ke
        if e <= s:
            self.cmd_panel.replace("1.0", "end",
                                   "invalid range — mark an END key frame "
                                   "after a START key frame")
            self.cmd_info["text"] = ""
            self.cmd_argv = []
            return
        if self.out_dir:
            try:
                os.makedirs(self.out_dir, exist_ok=True)
            except OSError as e:
                self.status["text"] = (
                    f"cannot create output folder {self.out_dir}: "
                    f"{e.strerror}")
                self.root.update_idletasks()
        self.out_path = default_output(self.video, s, e, self.mode,
                                       self.out_dir)
        # accurate mode decodes the source: if the primary build cannot
        # (AV1...), use the binary open_video picked; the menu-configured
        # alternate is honored inside build_argv for copy mode too
        ff = (self.decode_ff
              if self.mode == "accurate" and self.decode_ff else None)
        self.cmd_argv = build_argv(self.mode, self.video, s, e,
                                   self.out_path, self.crf_value(), ff,
                                   self.enc_codec)
        self.cmd_panel.replace("1.0", "end", shlex.join(self.cmd_argv))
        self.cmd_info["text"] = (
            f"range {fmt_num(s)} s → {fmt_num(e)} s  "
            f"({fmt_clock(s)} → {fmt_clock(e)}), "
            f"mode {self.mode}"
            + (f", codec {self.enc_codec}"
               if self.mode == "accurate" else "")
            + f", output {os.path.basename(self.out_path)}"
            + (f" (in {self.out_dir})" if self.out_dir else "")
            + (f" — encoder build: {ff}"
               if ff and ff != ffmpeg_path() else "")
            + note)

    def copy_cmd(self):
        # rebuild first, so a crf typed into the entry (but never applied
        # via the button/Enter) is read fresh at click time
        self.refresh_command()
        if not self.cmd_argv:
            return
        ok, msg = copy_to_clipboard(self.root, shlex.join(self.cmd_argv))
        self.log.insert("end", f"\nclipboard: {msg}\n")
        self.log.see("end")

    # ---------------------------------------------------------- execute

    def run_cmd(self):
        # rebuild first: the run carries exactly the crf (and marks) as
        # they are in the UI at the moment the button is clicked
        self.refresh_command()
        if not self.cmd_argv:
            return
        self.proc_lines = []
        self.proc_done = None
        argv = list(self.cmd_argv)
        self.log.insert("end", "\n$ " + shlex.join(argv) + "\n")
        self.log.see("end")

        def worker():
            try:
                p = subprocess.Popen(argv, env=ffmpeg_env(),
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     text=True)
                for line in p.stdout:
                    self.proc_lines.append(line.rstrip("\n"))
                self.proc_done = p.wait()
            except OSError as e:
                self.proc_lines.append(f"ERROR: {e}")
                self.proc_done = 999

        threading.Thread(target=worker, daemon=True).start()
        self._watch_proc(0)

    def _watch_proc(self, seen):
        # stream ffmpeg output to the log without Tcl calls in the thread
        lines = self.proc_lines or []
        for line in lines[seen:]:
            self.log.insert("end", line + "\n")
        self.log.see("end")
        if self.proc_done is None:
            self.root.after(150, self._watch_proc, len(lines))
            return
        rc = self.proc_done
        self.log.insert("end",
                        ("--- finished OK — output file written ---\n"
                         if rc == 0 else f"--- ffmpeg exit code {rc} ---\n"))
        self.log.see("end")
        if rc == 0 and self.out_path and os.path.exists(self.out_path):
            self.log.insert("end",
                            f"result: {self.out_path} "
                            f"({os.path.getsize(self.out_path)} bytes)\n")
            self.log.see("end")

    def log_clear(self):
        self.log.delete("1.0", "end")


def main():
    app = App()
    app.make_ui()
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg and os.path.exists(arg):
        app.open_video(arg)
    elif arg:
        app.status["text"] = f"file not found: {arg} — use the " \
                             "\u201cOpen a video file…\u201d button."
    else:
        app.status["text"] = ("Use the \u201cOpen a video file…\u201d button "
                              "(standard Tk file dialog), or the menu "
                              "\u201cOpen video file (type path)…\u201d for "
                              "awkward names/network mounts (paths with "
                              "commas, gvfs links), or pass the file "
                              "as a command-line argument.")
    app.root.mainloop()


if __name__ == "__main__":
    main()
