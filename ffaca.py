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
  * This custom ffmpeg build has no plain "ppm" muxer, so single frames
    are grabbed with:  ffmpeg ... -f image2pipe -vcodec ppm pipe:1
    
instructions:
            + "click a filmstrip cell (or use the ◀ ▶ buttons) to move "
            "between key frames — the strip is a fixed-width subsection "
            "you scroll with the mouse wheel, the bar under it, or the "
            "« scroll » buttons; ◀ frame / frame ▶ step one video frame "
            "at a time between key frames; MARK START / MARK END set the "
            "cut at the exact current position (fast copy snaps it to "
            "the nearest I-frame — accurate keeps it frame exact); the "
            "ffmpeg command appears in the black panel. "
            + "va03: in the column to the LEFT of the preview picture, "
            "PLAY ↦ (from this frame) plays the video at the current "
            "position and, below it, PLAY trimmed ⤠ plays it from MARK "
            "START to MARK END (the player seeks and stops, nothing is "
            "cut); ctrl + '+' goes to the next key frame, ctrl + '-' to "
            "the previous one, ctrl + Up to the first key frame and ctrl "
            "+ Down to the last. ")

va02 additions on top of va01:
  * av1_nvenc (NVIDIA NVENC AV1) as an accurate re-encode codec.  Its
    quality is tuned with a target BITRATE (-b:v, default 1M) instead
    of crf; the command carries the CUDA base defaults:
        -hwaccel cuda -hwaccel_output_format cuda -c:a copy -c:v av1_nvenc
        -preset p7 -tune uhq -tier 1 -b:v 1M -bufsize 5M -maxrate 10M
        -g 250 -b_ref_mode 1 -lookahead_level 15 -temporal-aq 1 -rc-lookahead
        48 -spatial-aq 1 -aq-strength 10 -temporal-aq 1 -nonref_p 1
        -i_qfactor 0.75 -b_qfactor 1.1
    (the cut range from MARK START / MARK END is applied with -ss /
    -to; the output lands in a .mkv).  NB: this option set needs an
    ffmpeg build with NVENC + nv-codec-headers AV1 — the /usr/local
    custom build has it; the plain distro build does not know
    -lookahead_level.
  * a PLAY button (left-aligned row) opens the video in an EXTERNAL
    PLAYER starting at the current position: mpv / vlc / ffplay
    understand a start-time option and seek from the playhead; if
    only the desktop file association exists (xdg-open), the OS-
    associated app opens the file and plays from the beginning (the
    log says so).  A second button, PLAY result, opens the file the
    last Run command produced.
  * the console panels (command display + ffmpeg log) are tk.LABELs,
    not Text: stock Tk offers no way to disable input in a Text —
    takefocus is silently ignored by this build, and a focused Text
    inserts characters internally, before any binding can intercept
    it (probed).  A Label simply CANNOT take keyboard input or focus,
    so the consoles are Labels behind a tiny LogPane/CmdPane shim
    that keeps the insert/see/replace call sites unchanged.
  * arrow keys move the playhead: left = 1 s back, right = 1 s
    forward, up = start of the video, down = end of the video — and
    the Down position shows the TRUE final frame (decoded from the
    short tail; container duration vs last-packet timestamps can put
    a single seek at dur - frame_dt one frame short).

va03 additions on top of va02:
  * the PLAY controls leave the bottom action row and get their OWN
    COLUMN right NEXT TO the preview picture: preview_row is one row
    frame with TWO columns packed side by side (pack decides left/right
    neighbours by the packing SIDE of the children of a single frame —
    there is no "put X beside Y" for widgets of different parents).
    Its LEFT column (play_win) holds PLAY from this frame with PLAY
    trimmed stacked under it; its RIGHT column (preview_col) holds the
    caption above the preview image, so the buttons touch the picture
    horizontally, never above or below it.  Swapping the two pack calls
    (or side="left" -> side="right" on play_win) mirrors the pair.
    PLAY trimmed opens the same video in the external player seeked to
    MARK START and stopped at MARK END — mpv --end= / vlc --stop-time=
    / ffplay -to (an INPUT option, so it stops at that position of the
    file): the cut range previewed without cutting anything.
    PLAY result (after run) stays in its old bottom row.
  * keybindings to jump between KEY frames (the strip cells), on top
    of the plain +/- frame stepping and the plain arrows:
        ctrl + '+'  next key frame      ctrl + '-'  previous key frame
        ctrl + Up   FIRST key frame     ctrl + Down LAST key frame
    '+' is matched by its keysym name (plus) and by the physical '='
    key, so Ctrl + Shift + '=' and Ctrl + '=' both work.  The handler
    parses the keysym of every keyboard event on root's catch-all
    binding, so the sequences need no exact spellings, and the plain
    +/- and arrow keys keep their va02 meaning.

va04 additions on top of va03 (desktop drag & drop, via tkinterdnd2):
  * the app window is a TkinterDnD.Tk window when the tkinterdnd2
    package is installed (it wraps the tkdnd Tk extension): its ROOT
    WINDOW is registered as a DROP TARGET for DND_Files.  Under X11
    tkdnd speaks the XDND v5 protocol, the one GNOME/Nautilus (Ubuntu's
    file manager), KDE and Qt applications use, so a video file grabbed
    from a Nautilus window and dropped anywhere over the app is opened
    by the app — no file dialog, no typed path.  Steps:
        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", self.on_drop)      # + the specialised
        root.dnd_bind("<<Drop:DND_Files>>", ...)     # and visual cues
        root.dnd_bind("<<DropEnter>>", ...)          #   <<DropLeave>>
    The tkdnd man page (https://www.ellogon.org/petasis/index.php/tcltk-
    projects/tkdnd/tkdnd-man-page) documents that a <<Drop>> binding MUST
    return the action it performed — one of copy / move / link / ask /
    private / refuse_drop — or the drop is refused, so on_drop returns
    COPY when it took the file and REFUSE_DROP when it did not (a
    folder, a picture, an unreadable name: Nautilus then shows the drop
    was not accepted instead of silently "eating" it).
  * %D (event.data) is the LIST of dropped files, braced by tkdnd
    (Nautilus also drops several files in one go), so the handler runs
    the string through Tcl splitlist, keeps the tokens that really
    exist on disk and, if none of them does, falls back to the raw
    string (that is the single-path-with-spaces case, which splitlist
    would otherwise chop).
  * the drop only RECORDS the path and opens it on root.after(), so the
    mouse action is released instantly (COPY returned) while the slow
    ffprobe/ffmpeg work (metadata, I-frame scan, strip thumbs) runs in
    the Tk idle cycle: the drop animation never waits for a video probe.
    The first video file of the drop is opened, the rest are reported.
  * a DnD_STATUS line under the header states whether drag & drop is
    live, and highlights while a file is dragged over the window
    (<<DropEnter>> / <<DropLeave>>).  Without tkinterdnd2 (or when the
    tkdnd library cannot load on this Tk build) the app falls back to a
    plain tk.Tk() window: every other feature is unchanged, the line
    says drag & drop is unavailable and the file dialog / the typed-
    path menu entry remain.  Dragging OUT of the app (a drag source, so
    Nautilus could receive the cut result) is NOT implemented.
  * the line ALSO carries a plain-language warning when the session
    advertises Wayland (WAYLAND_DISPLAY in the environment, which is
    what recent Ubuntu sets even when the app runs on the XWayland
    bridge): XDND only exists over X11, and GNOME's Nautilus is a
    Wayland-native program, so it sends no drop message to an X11 Tk
    window at all — nothing the app can intercept.  The app keeps
    everything else working and tells the user to use the file dialog
    or an Xorg session (drag & drop then works; an X11 file manager
    like Thunar/PCManFM, or Nautilus started as an X app, also works).
  * all four PLAY buttons (PLAY from start, PLAY from this frame, PLAY
    trimmed, PLAY result) are HIDDEN until a video is loaded: with
    nothing loaded there is nothing to play, a click could only answer
    "no video loaded", and a greyed-out Button does not exist in stock
    Tk, so the widgets are simply NOT PACKED (pack_forget) while no
    video is playable, and packed again once open_video succeeds —
    re-packed with before=/after= so the va03 order survives: the PLAY
    column returns to the LEFT of the preview (a plain pack would append
    it and hop it to the right of the picture) and PLAY from start goes
    back right after the "Open a video file…" button, which never hides
    because it is how a video gets loaded.  While the buttons are away
    the preview row narrows to the picture alone, so the picture
    recentres itself; nothing else in the layout moves.
  * LogPane gets a SCROLL COLUMN, shown only when necessary, over a
    console that is a FIXED rectangle while it scrolls.  It used to show
    only the tail VIEW=14 lines of a run that can produce hundreds, so
    most of a real ffmpeg log was unreachable: the shim now keeps a
    viewport (offset/view/follow) into the KEEP=400-line buffer.  The
    viewport counts DISPLAY ROWS, not logical lines, and LogPane
    hard-wraps every remembered line into rows of exactly `wrap`
    characters (wrap comes from this mono font's own measure, kept just
    inside the Label's 760 px wraplength so Tk can never re-wrap a row
    itself), padded to that width, and paints always exactly `view`
    rows.  Why that is mandatory, not cosmetic: Tk wraps by PIXELS, so a
    14-LINE window of ffmpeg output is 14/15/16 rows tall depending on
    which lines happen to be visible, and the Label is a child of its
    row — every different height re-lays the row out, the column slides
    up/down and resizes under the pointer, Tk stops delivering <B1-
    Motion>/<ButtonRelease-1> to the Canvas and the drag appears to
    "release the scroll" on its own.  Constant rows + constant width =
    constant box = the grab, the drag and the release all stay on the
    same widget.  The column itself is a hand-painted Canvas on the
    console's right (same reasoning as the filmstrip bar: this Tk
    build's Scrollbar renders a 13 px trough with an invisible thumb):
    trough + thumb whose HEIGHT shows how much of the log is hidden +
    up/down end arrows; click/drag jumps, the wheel scrubs by view//4
    rows, and the wheel is bound over the log panel as well as the bar
    (22 px of column in a ~760 px row is not a comfortable target).
    Following: while ffmpeg streams, the window stays pinned to the
    tail; as soon as the user scrolls away from it the pin drops, so
    the next lines cannot yank the text they are reading; scrolling
    back to the bottom re-arms it.  LogPane fires an on_change hook on
    insert/delete so the App repaints thumb and text together (never
    from refresh(), which the App itself calls — that would recurse).
"""

import os
import sys
import shutil
import shlex
import re
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

# va04: desktop drag & drop (Nautilus -> this window) through tkinterdnd2,
# the Python wrapper of the tkdnd Tk extension.  Under X11 tkdnd speaks
# XDND v5, the protocol GNOME/Nautilus (Ubuntu's file manager), KDE and
# Qt applications use, so a file dragged out of a Nautilus window and
# dropped over this app's window is received by it.  The package is NOT
# part of the stdlib: install it with pip (pip install tkinterdnd2 — the
# wheel carries the prebuilt tkdnd library for linux-x64, so nothing has
# to be compiled) and its tkdnd library may also refuse to load against
# this Tk build, so DND_OK gates everything: without it the app
# runs on a plain tk.Tk() window and drag & drop is simply unavailable
# (the file dialog and the typed-path menu entry still open videos).
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD, COPY, REFUSE_DROP
    DND_OK = True
except ImportError:
    DND_FILES = TkinterDnD = COPY = REFUSE_DROP = None
    DND_OK = False

FFMPEG_FALLBACK = "/usr/local/bin/ffmpeg"
FFPROBE_FALLBACK = "/usr/local/bin/ffprobe"
DEFAULT_LD = "/usr/local/lib"
PREFER = {"ff": None}   # alternate ffmpeg binary configured via the menu
THUMB_W = 140            # filmstrip thumbnail width (px)
PREVIEW_W = 512          # large preview width (px)
VISIBLE_CELLS = 8        # key-frame cells shown at once in the strip window
BAR_H = 26               # height of the app-drawn scrollbar bar
LOG_BAR_W = 22           # va04: width of the log's SCROLL COLUMN (px)
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


def grab_last_frame(video, dur, width):
    """Decode the short tail before EOF and return the LAST image — the
       TRUE final frame.  Seeking at exactly dur returns nothing, and
       seeking at dur - frame_dt can land ONE frame short on real files
       (container duration vs last packet pts_time disagree by rounding
       — user reports needing two frame-steps back after the Down key
       to see the final frame).  Decoding 0.25 s of tail and taking the
       last image is exact whatever the timestamps say.  Tries every
       ffmpeg candidate."""
    if not HAVE_PIL or not dur:
        return None
    t0 = max(0.0, dur - 0.5)
    for ff in ffmpeg_candidates():
        argv = [ff, "-loglevel", "error",
                "-ss", f"{t0:.6f}", "-i", video,
                "-vf", f"scale={width}:-1",
                "-f", "image2pipe", "-vcodec", "ppm", "pipe:1"]
        p = subprocess.run(argv, env=ffmpeg_env(), capture_output=True)
        imgs = parse_ppm_stream(p.stdout or b"")
        if imgs:
            return imgs[-1]
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
               codec="libx264", bitrate="1M"):
    """Build the ffmpeg argv for copying [start,end] out of `video`.

    'copy'     : -c copy stream copy — lossless and very fast, but the cut snaps to the
                 container's key frames (can include a little extra).
    'accurate' : re-encode — the cut is frame exact; quality is `crf`
                 (lower = better, 0..51) with the chosen `codec`
                 (libx264 default, libx265 available in this build), or,
                 for the va02 codec av1_nvenc (NVIDIA NVENC AV1), a
                 target `bitrate` (-b:v — crf is not used) on top of the
                 CUDA base defaults (-hwaccel cuda ... -preset p7 -tune
                 uhq -tier 1 ... -rc-lookahead 48 ...), exactly as given
                 by the user, with the cut range applied via -ss / -to
                 and the audio stream copied.  Such av1_nvenc commands
                 want an ffmpeg built with NVENC + nv-codec-headers AV1
                 (the /usr/local custom build has it).
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
    if codec == "av1_nvenc":
        # va02: user's CUDA base defaults; quality = target bitrate -b:v
        # (1M in the example) instead of crf; -ss/-to carry the cut.
        return [ff, "-y",
                "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                "-i", video,
                "-ss", num6(start), "-to", num6(end),
                "-c:a", "copy",
                "-c:v", "av1_nvenc",
                "-preset", "p7", "-tune", "uhq", "-tier", "1",
                "-b:v", str(bitrate), "-bufsize", "5M", "-maxrate", "10M",
                "-g", "250", "-b_ref_mode", "1",
                "-lookahead_level", "15",
                "-temporal-aq", "1", "-rc-lookahead", "48",
                "-spatial-aq", "1", "-aq-strength", "10",
                "-temporal-aq", "1", "-nonref_p", "1",
                "-i_qfactor", "0.75", "-b_qfactor", "1.1",
                out_path]
    return [ff, "-y",
            "-i", video,
            "-ss", num6(start), "-to", num6(end),
            "-c:v", codec, "-crf", str(int(crf)),
            "-c:a", "copy", out_path]


def default_output(video, start, end, mode, out_dir=None, codec="libx264"):
    stem, ext = os.path.splitext(video)
    if out_dir:
        # configured output folder instead of "next to the source"
        stem = os.path.join(out_dir, os.path.basename(stem))
    if mode == "accurate":
        # va02: the av1_nvenc base defaults end at output.mkv
        ext = ".mkv" if codec == "av1_nvenc" else ".mp4"
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

class LogPane:
    """va02: readonly ffmpeg-log view.  Stock Tk offers no way to
       disable input in a Text — this build even ignores takefocus, and
       a focused Text inserts typed characters INTERNALLY (before any
       <Key> binding can intercept, probed) — so the consoles avoid
       Text altogether: tk.Label cannot take keyboard input nor focus.
       This shim keeps the small Text API the app calls (insert/see/
       delete), accumulating lines in a Python buffer, and shows a
       window of it on the Label.

       va04 (the scroll column, half 1 of 2 — the App owns half 2): the
       buffer remembers far more than the Label can show, so the shim
       keeps a VIEWPORT into it.  Crucially the viewport is measured in
       DISPLAY ROWS, not in logical lines: each remembered line is
       hard-wrapped to exactly `wrap` characters and padded to that
       width, and the Label always paints exactly `view` of those rows.
       The reason this is not cosmetic: Tk wraps by PIXEL width, so a
       14-line window is 14 rows tall only while no line of those 14 is
       long enough to wrap — and an ffmpeg run mixes a single very long
       command line with short "Stream #0:1…" details, so consecutive
       14-line windows are 14/15/16 rows tall.  The console is a child
       of its row, so every different height re-lays out the row: the
       black box AND the scroll column shift up/down and the column
       changes size mid-drag; once the pointer leaves the Canvas, Tk
       stops delivering <B1-Motion> to it and the <ButtonRelease-1>
       lands on whatever is under it — the reported symptom "the mouse
       releases the scroll".  A constant rectangle (same x, same y,
       same width, same height for the whole scroll) is what keeps the
       grab, the drag and the release on one widget."""
    KEEP = 400                        # logical lines remembered
    VIEW = 14                         # display ROWS the window shows
    WRAP = 100                        # fallback chars per row (see make_ui)
    def __init__(self, label, wrap=None):
        self.label = label
        self.wrap = max(20, int(wrap or self.WRAP))
        self.lines = []               # logical lines (get()/history)
        self.rows = []                # wrapped + padded display rows
        self.view = self.VIEW         # rows shown at once
        self.offset = 0               # first ROW shown
        self.follow = True            # pin the window to the tail
        self.on_change = None         # App hook: repaint the column
    def insert(self, _index, text):
        # index ignored: the app only ever appends at "end"
        self.lines.extend(text.split("\n"))
        while self.lines and self.lines[-1] == "":
            self.lines.pop()
        if len(self.lines) > self.KEEP:
            del self.lines[:-self.KEEP]
        self.build_rows()
        if self.follow:
            self.offset = self.max_offset()
        # a shrunk buffer also drags the window back inside it
        self.set_offset(self.offset)
        self.refresh()
        self.notify()
    def delete(self, _a, _b):
        self.lines = []
        self.rows = []
        self.offset = 0
        self.follow = True
        self.refresh()
        self.notify()
    def build_rows(self):
        """Re-wrap the whole buffer into rows.  Bounded by KEEP lines of
           WRAP characters, so rebuilding per insert is microseconds —
           simpler and safer than trying to keep a per-line row count in
           step with the head-trimming."""
        self.rows = []
        for ln in self.lines:
            self.rows.extend(self.wrap_line(ln))
    def wrap_line(self, ln):
        """One logical line -> whole display rows, all exactly `wrap`
           characters (tabs expanded so the width is honest, trailing
           spaces kept so the box is a rectangle instead of a ragged
           edge that resizes with whatever window is showing)."""
        s = ln.expandtabs(4).rstrip()
        if not s:
            return [" " * self.wrap]
        out = []
        while s:
            head, s = s[:self.wrap], s[self.wrap:]
            out.append(head.ljust(self.wrap))
        return out
    def row_total(self):
        return len(self.rows)
    def scrollable(self):
        """True when the rows remembered do not fit the window — exactly
           when the App has to show its scroll column."""
        return len(self.rows) > self.view
    def max_offset(self):
        return max(0, len(self.rows) - self.view)
    def set_offset(self, o):
        self.offset = max(0, min(self.max_offset(), int(o)))
    def shown_rows(self):
        """The window: exactly `view` rows once the log scrolls, padded
           with blank (but full width) rows so the Label's requested
           height and width CANNOT change while the user scrolls.  While
           everything still fits, the Label shows just what it has, as
           in va02/va03 — a small panel the column does not need."""
        seg = self.rows[self.offset:self.offset + self.view]
        if self.scrollable():
            seg = seg + [" " * self.wrap] * (self.view - len(seg))
        return seg
    def refresh(self):
        self.label["text"] = "\n".join(self.shown_rows())
    def see(self, _index):
        pass                # Text API kept: a Label has no scroll region
    def yview(self, *_a):
        # Text API kept: where the window is, in display ROWS
        return (self.offset, min(len(self.rows), self.offset + self.view))
    def get(self, *_a):
        return "\n".join(self.lines)
    def notify(self):
        if self.on_change:
            self.on_change()


class CmdPane:
    """va02: readonly command display (same reasoning as LogPane): the
       one Text call the app makes is replace("1.0", "end", text)."""
    def __init__(self, label):
        self.label = label
    def replace(self, _a, _b, txt):
        self.label["text"] = txt
    def get(self, *_a):
        return self.label["text"]


# ---------------------------------------------------- external player
def player_argv(video, t, stop=None):
    """Best external-player command to play `video` at time t (seconds).
       Players that understand a start-time option are preferred (mpv
       family, then vlc, then ffplay next to the ffmpeg builds); the
       desktop file association (xdg-open — the OS app associated with
       the extension) is the last resort: it cannot be told where to
       start, only to open the file.  Returns (argv, player label,
       can_seek_from_t); (None, None, False) when nothing exists.
       va03: an optional `stop` (seconds) adds the matching STOP option
       so a player can play a TRIMMED range without cutting anything:
       mpv --end= (alias --stop), vlc --stop-time=, ffplay -to (before
       the input file, so it is an INPUT option and stops the playback
       at that position of the file)."""
    ts = num6(max(0.0, t))
    se = num6(max(0.0, stop)) if stop is not None else None
    for name in ("mpv", "mpv"):
        exe = shutil.which(name)
        if exe:
            opts = [f"--start={ts}"] + ([f"--end={se}"] if se else [])
            return [exe] + opts + [video], name, True
    for name in ("vlc", "cvlc"):
        exe = shutil.which(name)
        if exe:
            opts = [f"--start-time={ts}"] + (
                [f"--stop-time={se}"] if se else [])
            return [exe, video] + opts, name, True
    fp = shutil.which("ffplay")
    if not fp and os.path.exists("/usr/local/bin/ffplay"):
        fp = "/usr/local/bin/ffplay"
    if fp:
        opts = ["-ss", ts] + (["-to", se] if se else [])
        return [fp] + opts + [video], os.path.basename(fp), True
    if shutil.which("xdg-open"):
        return ["xdg-open", video], ("the app associated with the "
                                     "file type"), False
    return None, None, False


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
        # va04: desktop drag & drop state (Tk window class + note)
        self.dnd = False              # this window accepts desktop drops
        self.dnd_note = ""            # why it does not, when it cannot
        # va04: the PLAY buttons (from start / from here / trimmed /
        # result) only exist once a video is loaded: with nothing loaded
        # there is nothing to play, so they are not packed at all.  This
        # remembers which state they are in, so re-applying the choice
        # never double-packs a widget.
        self.play_shown = None        # None: not created yet

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
        # va04: the ROOT window class decides whether desktop drag & drop
        # is possible at all: tkdnd (through tkinterdnd2) loads its
        # extension into THIS interpreter here, which is what registers
        # the window with the desktop's XDND service in the first place —
        # a plain tk.Tk() window can never receive a Nautilus drop.
        # _require() inside TkinterDnD.Tk() raises RuntimeError when the
        # tkdnd library will not load against this Tk build, so the load
        # is attempted and, on any failure, the app falls back to the
        # plain window (drag & drop then just stays unavailable, and the
        # DnD line under the header says so).
        root = None
        if DND_OK:
            try:
                root = TkinterDnD.Tk()
                self.dnd = True
            except (RuntimeError, tk.TclError) as exc:
                self.dnd_note = (f"tkdnd would not load on this Tk build "
                                 f"({exc}) — ")
                root = None
        if root is None:
            root = tk.Tk()
        root.wm_title("FFACA: FFMPEG Frame Accurate Cutting App")
        self.root = root
        mono = tkfont.nametofont("TkFixedFont")

        # --- header / status
        self.status = tk.Label(root, wraplength=760, justify="left",
                               fg="#606060")
        self.status.pack()

        # --- va04: the drag & drop line: what the window accepts, and
        # the live cue while a file is dragged over it (<<DropEnter>> /
        # <<DropLeave>> repaint this Label).  Its background is remembered
        # so the cue can be undone exactly, whatever the theme default is.
        self.dnd_lbl = tk.Label(root, wraplength=760, justify="left",
                                fg="#505050")
        self.dnd_lbl.pack()
        self.dnd_bg = self.dnd_lbl.cget("bg")
        self.dnd_status()

        # --- open a video: single button + the standard Tk file dialog
        # va04: named attributes instead of a loop, because PLAY from
        # start is now HIDDEN until a video is loaded (see
        # set_play_visibility): the row hides that one child while
        # "Open a video file…" stays put — it is how a video loads.
        navhead = tk.Frame(root)
        navhead.pack()
        self.open_btn = tk.Button(navhead, text="Open a video file…",
                                  command=self.open_dialog)
        self.open_btn.pack(side="left")
        self.play_start_btn = tk.Button(
            navhead, text="PLAY from start (external player)",
            command=self.play_fromstart)
        self.play_start_btn.pack(side="left")
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
                         #("« scroll ◀", self.scroll_left),
                         #("scroll ▶ »", self.scroll_right),
                         ("last kf ▶|", self.last_key)):
            tk.Button(nav1, text=txt, command=cmd).pack(side="left")

        self.step_lbl = tk.Label(root, fg="#606060")
        self.step_lbl.pack()

        # --- large preview of the selected key frame, with the PLAY
        # controls right NEXT TO it (horizontally, NOT above/below).
        # Tk pack has no "put X to the left of Y" option: what sits side
        # by side is decided by the packing SIDE of the children, so the
        # picture and the PLAY buttons are now two children of ONE row
        # frame, both packed side="left".  The row is a normal propagating
        # Frame (unlike strip_win): its width is the width of BOTH
        # columns, so it only grows as wide as button column + preview.
        # Order inside the row: play column first -> picture column, so
        # the buttons are the LEFT neighbour of the preview; swap the two
        # blocks (or pack the picture with side="right") to flip sides.
        # anchor="c" centres the shorter column vertically against the
        # taller one (caption + image).
        # va04: this whole column is HIDDEN until a video is loaded
        # (set_play_visibility pack_forgets it).  Re-showing it must
        # therefore re-pack it with before=preview_col: pack_forget drops
        # a widget from the packing order and a plain pack() APPENDS it,
        # which would silently move the PLAY buttons to the RIGHT of the
        # preview.  The picture column stays, it is the video's own view.
        self.preview_row = tk.Frame(root)
        self.preview_row.pack()
        self.play_win = tk.Frame(self.preview_row)
        self.play_win.pack(side="left", anchor="c")
        self.preview_col = tk.Frame(self.preview_row)
        self.preview_col.pack(side="left", anchor="c", padx=(10, 0))

        # PLAY buttons column (left of the preview, stacked): PLAY from
        # this frame = the current playhead; PLAY trimmed = MARK START
        # → MARK END, both in the external player
        self.play_btn = tk.Button(
            self.play_win, text="PLAY ↦",
            command=self.play_external)
        self.play_btn.pack(anchor="w")
        self.play_trim_btn = tk.Button(
            self.play_win, text="PLAY trimmed ⤠",
            command=self.play_trimmed)
        self.play_trim_btn.pack(anchor="w")

        # picture column: caption above the image, as before
        self.preview_caption = tk.Label(self.preview_col, fg="#606060")
        self.preview_caption.pack()
        self.preview = tk.Label(self.preview_col)
        self.preview.pack()

        # --- navigation buttons
        nav0 = tk.Frame(root)
        nav0.pack()
        for txt, cmd in (("◀ -1 frame", self.prev_frame),
                         ("frame +1 ▶", self.next_frame)):
            tk.Button(nav0, text=txt, command=cmd).pack(side="left")
        nav = tk.Frame(root)
        nav.pack()
        for txt, cmd in (("|◀ first kf", self.first_key),
                         ("◀ prev key frame", self.prev_key),
                         ("next key frame ▶", self.next_key),
                         ("last kf ▶|", self.last_key)):
            tk.Button(nav, text=txt, command=cmd).pack(side="left")
        nav2 = tk.Frame(root)
        nav2.pack()
        for txt, cmd in (("MARK START⤃", self.mark_start),
                         ("⤂MARK END", self.mark_end)):
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
            "fast copy  — lossless, snaps to key frames",
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
        self.cmd_lb = tk.Label(root, justify="left", wrap=1,
                               wraplength=760, bg="#1e1e1e", fg="#dcdcdc",
                               bd=1, relief=tk.SUNKEN)
        self.cmd_lb.config(font=mono)
        self.cmd_lb.pack()
        self.cmd_panel = CmdPane(self.cmd_lb)   # readonly (va02)
        self.cmd_info = tk.Label(root, justify="left", fg="#202020")
        self.cmd_info.pack()

        # --- action buttons
        self.copy_btn = tk.Button(root, text="Copy command to clipboard",
                                  command=self.copy_cmd)
        self.copy_btn.pack()
        self.run_btn = tk.Button(root, text="Run command", command=self.run_cmd)
        self.run_btn.pack()
        # va02: PLAY buttons on their own LEFT-aligned row (anchor="w"):
        # va03: PLAY from here and the new PLAY trimmed moved UP beside
        # the preview (play_win is now the LEFT column of preview_row,
        # packed side="left" against the picture column); only PLAY
        # result — the file the last Run command produced — stays down
        # here, in its own left-aligned row under the Run button.
        playrow = tk.Frame(root)
        playrow.pack(side="top", anchor="e")
        self.play_res_btn = tk.Button(playrow,
                                      text="PLAY result (after run)",
                                      command=self.play_result)
        self.play_res_btn.pack(side="right")

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
            cm.add_command(label="av1_nvenc (NVENC GPU)",
                           command=lambda: self.pick_codec(
                               "av1_nvenc (NVENC GPU, bitrate)"))
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
            m.add_command(label="Pick codec: av1_nvenc (NVENC)",
                          command=lambda: self.pick_codec(
                              "av1_nvenc (NVENC, bitrate)"))

        # --- ffmpeg output log (va02: readonly Label + LogPane shim —
        # this build has no way to disable input in Text: takefocus is
        # ignored, and Labels simply cannot take input or focus)
        # va04: the console now lives in a ROW with a SCROLL COLUMN on
        # its right, and the column only appears when the remembered log
        # does not fit the window (LogPane.scrollable) — "when
        # necessary".  A tk.Label cannot scroll and this Tk build's
        # Scrollbar widget draws a 13 px trough whose thumb is
        # invisible (the very reason the filmstrip bar is hand drawn), so
        # the column is a small Canvas painted by the app: trough +
        # proportional thumb + end arrows, click/drag to jump, wheel to
        # scrub.  Side="left" for both children keeps the column on the
        # RIGHT of the console without a before= re-pack: the console is
        # already the first child, so appending the bar is its correct
        # place (unlike the preview row, where the PLAY column had to
        # come back in FRONT of its sibling — see set_play_visibility).
        self.log_win = tk.Frame(root)
        self.log_win.pack()
        # va04: LogPane WRAPS the log itself, into rows of a fixed number
        # of characters, and paints always the same number of rows: the
        # console is then a constant rectangle while the user scrolls
        # (Tk would wrap by PIXELS, and a 14-line window of ffmpeg output
        # is 14/15/16 rows tall depending on which lines are visible — a
        # height that changes mid-drag moves the scroll column out from
        # under the pointer, Tk stops sending <B1-Motion>/<ButtonRelease-
        # 1> to it and the drag is lost).  So the characters per row come
        # from this mono font's own metrics, kept just inside the Label's
        # wraplength so the Label can never re-wrap our rows itself.
        cw = float(mono.measure("x" * 10))
        cw = int(round(cw / 10.0)) or 8      # ONE character, in pixels
        log_wrap = max(40, (760 - 12) // cw)
        self.log_lb = tk.Label(self.log_win, justify="left", wrap=1,
                               wraplength=760, bg="#1e1e1e", fg="#dcdcdc",
                               bd=1, relief=tk.SUNKEN)
        self.log_lb.config(font=mono)
        self.log_lb.pack(side="left")
        self.log = LogPane(self.log_lb, log_wrap)   # readonly (va02)
        self.log_wrap = log_wrap    # kept for the log hint text
        self.log_sb = tk.Canvas(self.log_win, highlightthickness=0,
                                bg=self.log_lb.cget("bg"))
        # the column is NOT packed here: set_log_scrollbar decides
        for seq in ("<Button-1>", "<B1-Motion>", "<B2-Motion>"):
            try:
                self.log_sb.bind(seq, self.log_sb_jump)
            except tk.TclError:
                pass
        for seq in ("<MouseWheel>", "<ButtonMotion-1>", "<Alt-B1>",
                    "<Shift-B1>"):
            try:
                # wheel over the bar...
                self.log_sb.bind(seq, self.log_wheel)
                # ...and over the log panel itself: the bar is 22 px of a
                # ~760 px row, so hovering over the TEXT is what users do
                self.log_lb.bind(seq, self.log_wheel)
            except tk.TclError:
                pass      # wheel keysym unsupported on this Tk build
        # va04: let the shim tell the app whenever the buffer changed, so
        # the thumb is repainted while a run streams (its size follows
        # how many lines the buffer now holds)
        self.log.on_change = self.refresh_log

        # keyboard: '+' / '-' move the playhead one video frame forward /
        # back.  A catch-all <Key> binding on root sits BELOW every
        # widget's own bindings (Tk resolves per widget first), so typing
        # in the crf entry, Return on buttons, dialogs etc. is untouched;
        # keys that no focused widget handles fall through to this.
        try:
            root.bind("<Key>", self.on_key)
        except tk.TclError:
            pass
        # va02: arrow keys on the playhead — left: 1 s back, right: 1 s
        # forward, up: first frame, down: last frame.  Like the <Key>
        # catch-all these sit under every widget's own bindings, so a
        # focused entry (crf / bitrate) keeps its native arrow cursor
        # movement while the user types.
        # va03: ctrl + '+' (next key frame), ctrl + '-' (previous key
        # frame), ctrl + Up (FIRST key frame), ctrl + Down (LAST key
        # frame).  on_key parses the keysym, so the spellings below are
        # only a convenience list: whatever this Tk build calls a
        # Ctrl-joined event (Control-plus / Control-Shift-plus /
        # Control-Up / ...), it reaches on_key through the <Key> catch-
        # all anyway, and a bad name here is harmless.
        for seq in ("<Left>", "<Right>", "<Up>", "<Down>",
                    "<Control-Up>", "<Control-Down>",
                    "<Control-plus>", "<Control-equal>",
                    "<Control-minus>"):
            try:
                root.bind(seq, self.on_key)
            except tk.TclError:
                pass

        # va02: PIN keyboard focus to the root window for the whole
        # session.  This build's Text ignores takefocus (cget returns
        # empty): a clicked command console used to hold focus forever,
        # and keyboard events for focused Text are inserted INTERNALLY
        # — per-widget <Key> overrides cannot stop that (probed).  With
        # focus on root, every keystroke reaches root's catch-all
        # bindings (the playhead handler), and the consoles stay pure
        # output.  Clicking the crf/bitrate Entry still focuses it
        # normally (its own click code), and Apply CRF / Apply bitrate
        # returns focus here via unfocus_crf.  The consoles are tk.
        # Labels (va02): they can never hold focus or receive input.
        try:
            self.root.tk.call("focus", "-force", self.root._w)
        except (tk.TclError, AttributeError):
            pass

        # --- va04: make the whole window a drop target -----------------
        # Registering the ROOT window (and not one small widget) is what
        # a drag from a file manager wants: the drop is accepted
        # anywhere over the app, so the user only has to aim at the
        # window, not at a target icon.  DND_FILES is the portable type
        # for "a list of files" (under X11 tkdnd maps it to text/uri-
        # list, the format Nautilus sends).  Alongside the generic
        # <<Drop>> binding, the specialised <<Drop:DND_Files>> one is
        # bound too: the tkdnd man page says a binding for the
        # specialised event runs INSTEAD of the generic one when the
        # drop arrives with that type, so binding both covers a drop
        # however this tkdnd version chooses to report it.  The visual
        # cues are the <<DropEnter>> / <<DropLeave>> pair.
        # Every one of these handlers must return the action it took
        # (or, for <<DropLeave>>, nothing) — the man page is explicit
        # that a <<Drop>> binding with no action REFUSES the drop, which
        # is exactly the right answer for a folder or a picture.
        if self.dnd:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind("<<Drop>>", self.on_drop)
                self.root.dnd_bind("<<Drop:" + DND_FILES + ">>",
                                   self.on_drop)
                self.root.dnd_bind("<<DropEnter>>", self.dnd_enter)
                self.root.dnd_bind("<<DropLeave>>", self.dnd_leave)
            except (AttributeError, tk.TclError) as exc:
                # the extension answered something unexpected: keep the
                # app alive, drag & drop just stays off
                self.dnd = False
                self.dnd_note = f"drag & drop disabled ({exc}) — "
                self.dnd_status()

        # va04: hide every PLAY button at start-up.  No video is loaded
        # yet (make_ui runs before open_video, the arg/dialog/drop paths
        # all come later), so the buttons are packed during creation —
        # that is how their anchor/side options are remembered — and
        # dropped from the packing order here, before the window is ever
        # shown; set_play_visibility(True) at the end of a successful
        # open_video puts them back where they belong.
        self.set_play_visibility(False)

    # ------------------------------------------------------------- open

    def open_video(self, path):
        self.video = path
        self.frames = {}
        # va04: while a file is being probed (and after a probe that
        # failed outright) the PLAY buttons stay hidden: the previous
        # video, if any, is not playable any more and this one is not
        # playable yet, so a click could only confuse the user.  They
        # come back at the end of this method, once the video really is
        # loaded (the failure branch above returns before that).
        self.set_play_visibility(False)
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
        # va04: the video is loaded and playable — bring the PLAY
        # buttons back (from start, the two in the preview column, and
        # PLAY result at the bottom)
        self.set_play_visibility(True)

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

    def av1nvenc_supported(self):
        """True when the ffmpeg binary the app would run actually
           advertises the av1_nvenc encoder (NVENC build with nv-
           codec-headers AV1, like the /usr/local custom one)."""
        ff = self.decode_ff or PREFER["ff"] or ffmpeg_path()
        if not ff:
            return False
        p = run_ff([ff, "-hide_banner", "-encoders"])
        return b"av1_nvenc" in (p.stdout or b"")

    def pick_codec(self, label):
        """Config menu: encoder for accurate frame re-encode (libx264
           default, libx265; va02: av1_nvenc, NVIDIA's GPU encoder,
           whose quality is tuned with the bitrate field instead of
           crf — it needs an ffmpeg build with NVENC AV1 support)."""
        codec = label.split()[0]
        if codec == "av1_nvenc" and not self.av1nvenc_supported():
            self.status["text"] = (
                "the ffmpeg build in use has no av1_nvenc encoder — "
                "configure an ffmpeg built with NVENC/AV1 support (menu: "
                "ffmpeg binary) or pick another codec; selection unchanged.")
            self.root.update_idletasks()
            return
        self.enc_codec = codec
        # the shared quality entry gets the right default for the codec:
        # crf 23 for the CPU encoders, target bitrate 1M for av1_nvenc
        try:
            self.crf_e.delete(0, "end")
            self.crf_e.insert("end",
                              "1M" if codec == "av1_nvenc" else "23")
        except tk.TclError:
            pass
        self.update_quality_ui()
        self.status["text"] = (
            f"accurate re-encode codec: {self.enc_codec}"
            + (" — quality is tuned with the target-bitrate field"
               if codec == "av1_nvenc" else ""))
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

    # -------------------------------------------------- va04: desktop dnd

    def dnd_status(self):
        """Refresh the drag & drop line under the header: whether this
           window can receive desktop drops at all (tkdnd loaded or not).
           va04 also warns (without disabling anything) when the session
           looks Wayland-based: tkdnd's Unix protocol is XDND, which only
           travels over X11 — GNOME's Nautilus in recent Ubuntu is a
           Wayland-native program and sends no XDND message to an X11 Tk
           window, so the drop is never received and no handler can even
           refuse it.  The line tells the user what to do instead."""
        if self.dnd:
            self.dnd_lbl["text"] = (
                "drag & drop: grab a video file and drop it on this window "
                "(no dialog, no typed path)"
                + ("  NB: a Wayland session is in use"
                   if os.environ.get("WAYLAND_DISPLAY") else ""))
        else:
            self.dnd_lbl["text"] = (
                (self.dnd_note or "tkinterdnd2 is not installed — ")
                + "drag & drop is unavailable here: open a video with the "
                  "\u201cOpen a video file\u2026\u201d button or the menu "
                  "entry that takes a typed path")

    def dnd_enter(self, event):
        """<<DropEnter>> (va04): the pointer came into the window while a
           drop is in progress.  Paint the cue on the DnD line and return
           the action this window WOULD take: the tkdnd man page says a
           drop target that never answers is refused, so answering here
           is what tells Nautilus (and draws its 'drop here' ghost).
           Deliberately cheap — no probing of the file at this point."""
        self.dnd_lbl["text"] = ("a file is over this window — release it "
                                "to open it (or move out to cancel)")
        self.dnd_lbl.configure(bg="#ffe9a8")
        return COPY

    def dnd_leave(self, event):
        """<<DropLeave>> (va04): the pointer left the window before any
           drop happened; undo the cue.  No action expected back."""
        self.dnd_lbl.configure(bg=self.dnd_bg)
        self.dnd_status()

    def dnd_paths(self, event):
        """The dropped items as plain paths (va04).  %D — event.data for
           tkdnd events — is the LIST of files handed over, each item
           braced by tkdnd when its name holds spaces (Nautilus can drop
           several files at once), so the Tcl list is read with splitlist.
           Tokens that do not exist on disk are discarded, and when NONE
           of them does the raw string is tried as one path: a single
           unbraced name with spaces would otherwise be chopped by
           splitlist. Returns [] for a non-file drop (e.g. plain text)."""
        data = getattr(event, "data", None)
        if not data:
            return []
        try:
            parts = [p for p in self.root.tk.splitlist(data) if p]
        except tk.TclError:
            parts = []
        real = [p for p in parts if os.path.exists(p)]
        if real:
            return real
        if os.path.exists(data):
            return [data]
        # nothing survived.  tkdnd braces the items of a LIST, so an
        # unbraced string was ONE name — and splitlist has just chopped
        # it if it contains spaces: report the whole string instead (the
        # name may simply not exist any more, or it never did).
        if "{" not in data and "}" not in data:
            return [data]
        return parts

    def on_drop(self, event):
        """<<Drop>> / <<Drop:DND_Files>> (va04): Nautilus (or any XDND
           application) dropped files onto this window.  The video files
           among them are opened; everything else (folder, picture, text)
           makes the drop REFUSED, which Nautilus shows as 'no' instead of
           pretending the file went somewhere.
           The slow part — ffprobe metadata, the I-frame scan, decoding
           the strip thumbnails — is NOT done here: the drop is only
           recorded and the open is queued on root.after(), so the mouse
           action is released (COPY returned) at once and the video loads
           during the normal Tk idle cycle.  Tky callbacks that block are
           a bad idea in general: the file manager is still holding the
           drag when this handler runs.
           MUST return the action taken (COPY / REFUSE_DROP), see dnd_
           enter/dnd_leave and the tkdnd man page."""
        paths = self.dnd_paths(event)
        vids = [p for p in paths if os.path.isfile(p)
                and p.lower().endswith(self.VIDEO_EXT)]
        if not vids:
            self.log.insert("end", ("\ndropped item(s) refused: no video "
                                    "file among "
                                    f"{'; '.join(paths) or '(empty drop)'} "
                                    "— folders, images and text drops are "
                                    "not opened by this app\n"))
            self.log.see("end")
            return REFUSE_DROP
        first = vids[0]
        self.dnd_lbl["text"] = (f"dropped {os.path.basename(first)} — "
                                "probing it, the window stays live...")
        if len(vids) > 1:
            # one video at a time, like the file dialog already behaves
            self.log.insert("end", ("\ndropped several files: "
                                    f"{first} is opened, "
                                    f"{', '.join(vids[1:])} were ignored "
                                    "(the app shows one video at a time)\n"))
            self.log.see("end")
        self.root.after(80, self.dnd_open, first)
        return COPY

    def dnd_open(self, path):
        """Queued by on_drop: open the dropped file (the heavy probe runs
           in the idle cycle, not inside the drag callback) and restore
           the normal drag & drop line."""
        self.open_video(path)
        self.dnd_lbl.configure(bg=self.dnd_bg)
        self.dnd_status()


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
               "bar under it."
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
           '+' steps the frame preview forward, '-' backward (va01);
           va02 adds the arrow keys — Left: playhead 1 s back, Right:
           1 s forward, Up: start of the video, Down: end of the video
           (clamped by set_play_t).  A focused Entry (crf / bitrate)
           keeps its own arrow bindings, so these only act while the
           window itself holds the keyboard focus.
           va03 adds the KEY-frame jumps: ctrl + '+' = next key frame,
           ctrl + '-' = previous key frame, ctrl + Up = FIRST key frame,
           ctrl + Down = LAST key frame.  Tk names such an event with
           its modifiers joined to the key by '-', e.g. Control-plus or
           Control-Shift-plus, so split the keysym and test the base
           name: the '+' key comes in as 'plus' (and, since '+' is the
           shifted half of a key, some toolkits report the unshifted
           physical name 'equal' — both are accepted).  The plain '+'
           char path below still handles the unmodified key."""
        if not self.times:
            return
        ks = getattr(event, "keysym", "")
        # --- va03: ctrl + key  ->  jump to another KEY frame ---------
        # (checked before the plain arrow / char cases: a modified keysym
        # like "Control-Up" never equals "Up", but keep the order obvious)
        parts = ks.split("-")
        if len(parts) > 1 and "Control" in parts[:-1]:
            base = parts[-1]
            if base in ("Up", "up"):
                self.first_key()
                return
            if base in ("Down", "down"):
                self.last_key()
                return
            if base in ("plus", "equal", "+", "=", "*"):
                self.key_next()
                return
            if base in ("minus", "underscore", "-", "_"):
                self.key_prev()
                return
            # any other ctrl combination: do nothing with the playhead
            # (it belongs to the focused widget, if it has a use)
            return
        if ks == "Left":
            self.set_play_t(self.play_t - 1.0)
            return
        if ks == "Right":
            self.set_play_t(self.play_t + 1.0)
            return
        if ks == "Up":
            self.set_play_t(0.0)
            return
        if ks == "Down":
            dur = (self.info or {}).get("duration")
            self.set_play_t(dur if dur else self.times[-1])
            return
        ch = getattr(event, "char", None)
        if not ch:
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
            dur = (self.info or {}).get("duration")
            if dur and t >= dur - 1e-6:
                # va02: Down / end position = TRUE final frame via a
                # short tail decode (a single seek at dur - frame_dt can
                # still land one frame short on real files)
                key = ("EOF", PREVIEW_W)
                if key not in self.frames:
                    self.frames[key] = grab_last_frame(self.video, dur,
                                                       PREVIEW_W)
                pil = self.frames[key]
            else:
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

    # --- va03: key-frame jumps for the ctrl keybindings --------------
    # They walk the key-frame list relative to the EXACT playhead, so
    # after frame stepping / arrow nudges left the playhead between two
    # key frames, ctrl + '+' / '-' still moves in the pressed direction
    # instead of bouncing off the nearest cell.  select() parks the
    # playhead ON the key frame and recentres the strip on it.

    def key_next(self):
        """ctrl + '+': move to the next key frame after the playhead."""
        if not self.times:
            return
        for i, t in enumerate(self.times):
            if t > self.play_t + 1e-6:
                self.select(i)
                return
        # already at (or past) the last key frame: stay put

    def key_prev(self):
        """ctrl + '-': move to the previous key frame before the playhead."""
        if not self.times:
            return
        for i in range(len(self.times) - 1, -1, -1):
            if self.times[i] < self.play_t - 1e-6:
                self.select(i)
                return

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

    # --- va04: the PLAY buttons exist only while a video is loaded ----
    # With nothing loaded there is nothing to play, and all four of them
    # (PLAY from start, PLAY from this frame, PLAY trimmed, PLAY result)
    # are pure noise: a click could only answer "no video loaded".  They
    # are therefore NOT PACKED until open_video succeeds: hiding means
    # absent, not greyed out — this Tk build has no disabled-widget state
    # and an invisible-but-packed button would still be clickable and
    # still reserve its screen space.
    #
    # Re-showing must restore the PACKING ORDER, not just pack again:
    # pack_forget removes a widget from its master's packing order, and a
    # bare pack() APPENDS it to that side — for the preview row that
    # would hop the PLAY column to the RIGHT of the picture (va03 put it
    # on the left), so it is re-inserted with before=preview_col.  Same
    # for the top row, where PLAY from start goes back right after the
    # Open button.  This mirrors how set_crf_visibility re-packs the crf
    # frame with after= — `before`/`after` are how Tk re-positions.
    def set_play_visibility(self, show):
        """Pack (show=True, a video is loaded) or unpack (show=False)
           every PLAY button.  Idempotent through self.play_shown so a
           repeated call never double-packs a widget."""
        if show == self.play_shown:
            return
        self.play_shown = show
        if not show:
            for w in (self.play_start_btn, self.play_win,
                      self.play_res_btn):
                try:
                    w.pack_forget()
                except tk.TclError:
                    pass
            return
        try:
            self.play_start_btn.pack(side="left", after=self.open_btn)
        except tk.TclError:
            self.play_start_btn.pack(side="left")
        try:
            self.play_win.pack(side="left", anchor="c",
                               before=self.preview_col)
        except tk.TclError:
            self.play_win.pack(side="left", anchor="c")
        try:
            self.play_res_btn.pack(side="left")
        except tk.TclError:
            pass

    def set_crf_visibility(self):
        """Show the quality label+input only while mode is accurate.  The
           same entry is a CRF for libx264/libx265 and a target BITRATE
           (-b:v) when the codec is av1_nvenc (va02)."""
        self.update_quality_ui()
        if self.mode == "accurate":
            try:
                self.crf_win.pack(after=self.mode_btn)
            except tk.TclError:
                self.crf_win.pack()
        else:
            self.crf_win.pack_forget()

    def update_quality_ui(self):
        """Label + Apply button text follow the codec: crf for libx264
           / libx265, target bitrate (-b:v) for av1_nvenc (va02)."""
        if self.enc_codec == "av1_nvenc":
            self.crf_lbl["text"] = ("target bitrate -b:v (e.g. 1M, 5M, "
                                    "2500k; default 1M):")
            try:
                self.crf_apply_btn.configure(text="Apply bitrate")
            except tk.TclError:
                pass
        else:
            self.crf_lbl["text"] = ("re-encode quality crf (0 best … 51 worst, "
                                    "default 23):")
            try:
                self.crf_apply_btn.configure(text="Apply CRF")
            except tk.TclError:
                pass

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

    def bitrate_value(self):
        """va02: target bitrate typed into the SAME quality entry when
           the codec is av1_nvenc: 1M, 5M, 800k, 1G or a bare number
           (bits/s); unusable input falls back to the base default 1M."""
        try:
            v = self.crf_e.get().strip()
        except tk.TclError:
            v = ""
        if re.fullmatch(r"[0-9]+(\.[0-9]+)?[kKmMbBGT]?", v):
            return v
        return "1M"

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
                                       self.out_dir, self.enc_codec)
        # accurate mode decodes the source: if the primary build cannot
        # (AV1...), use the binary open_video picked; the menu-configured
        # alternate is honored inside build_argv for copy mode too
        ff = (self.decode_ff
              if self.mode == "accurate" and self.decode_ff else None)
        self.cmd_argv = build_argv(self.mode, self.video, s, e,
                                   self.out_path, self.crf_value(), ff,
                                   self.enc_codec,
                                   self.bitrate_value())
        self.cmd_panel.replace("1.0", "end", shlex.join(self.cmd_argv))
        self.cmd_info["text"] = (
            f"range {fmt_num(s)} s → {fmt_num(e)} s  "
            f"({fmt_clock(s)} → {fmt_clock(e)}), "
            f"mode {self.mode}"
            + (f", codec {self.enc_codec}"
               if self.mode == "accurate" else "")
            + (f", bitrate -b:v {self.bitrate_value()}"
               if self.mode == "accurate" and self.enc_codec == "av1_nvenc"
               else "")
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

    # ------------------------------------- va04: log scroll column
    # The log remembers KEEP lines and the Label shows VIEW of them, so
    # most of a real ffmpeg run used to be simply unreachable.  The
    # column appears ONLY when the buffer no longer fits the window
    # ("when necessary"): with the tail already showing everything there
    # is nothing to scroll and the row stays exactly as in va03.
    # Painted by hand like the filmstrip bar because this Tk build's
    # Scrollbar gives a 13 px trough with an invisible thumb.
    #
    # va04 follow-up: the console is a FIXED rectangle while it scrolls —
    # LogPane pre-wraps the log into `view` rows of `wrap` characters
    # each — so the column's box, and therefore the pointer's grip on it,
    # never moves mid-drag.  That is the whole point: with a Label that
    # re-wraps itself by pixels, each scroll step changed the row height,
    # Tk re-laid the row out, the Canvas slid away under the pointer, the
    # <B1-Motion> stream and the <ButtonRelease-1> went to another
    # widget and the drag looked like it had "released the scroll".
    def refresh_log(self):
        """Repaint the log window AND the scroll column as one unit: a
           thumb that disagrees with the visible lines is worse than a
           missing thumb.  LogPane calls this through on_change whenever
           its buffer grows or is cleared."""
        self.log.refresh()
        self.set_log_scrollbar()

    def set_log_scrollbar(self):
        """Show/hide the column depending on LogPane.scrollable() and
           keep it exactly as tall as the console, which is what the
           pixel→line mapping assumes."""
        if self.log.scrollable():
            if self.log_sb.winfo_manager() == "":
                self.log_sb.pack(side="left", padx=(8, 0))
            # the console's REQUESTED height reflects its text the
            # instant the text is set; its displayed height only follows
            # on the next update — and a thumb mapped to that stale,
            # shorter value would sit nowhere near the lines it claims
            h = self.log_lb.winfo_reqheight()
            if h < 12:
                h = max(24, self.log_sb.winfo_height())
            self.log_sb.configure(width=LOG_BAR_W, height=h)
            self.draw_log_bar()
        else:
            if self.log_sb.winfo_manager() != "":
                self.log_sb.pack_forget()
            self.log_sb.delete("all")

    def draw_log_bar(self):
        """Paint the column: long visible trough, a thumb whose HEIGHT is
           the fraction of the log the window shows (so the user sees how
           much is hidden), its POSITION is the window in the buffer, and
           up/down end arrows."""
        sb = self.log_sb
        # REQUESTED sizes: they are what the column will be (and will be
        # drawn as) after the next update, and they follow the console's
        # text immediately — the displayed size would lag and the thumb
        # would then map to the wrong lines
        w, h = sb.winfo_reqwidth(), sb.winfo_reqheight()
        if w < 10:
            w = LOG_BAR_W
        if h < 24:
            h = sb.winfo_height()
        sb.delete("all")
        # ROWS, not the logical lines: what the trough has to represent
        # is the same thing LogPane scrolls through
        total = self.log.row_total()
        view = self.log.view
        if total <= view:
            return                    # nothing to scroll: leave it blank
        ax = 14                       # arrow zones at both ends
        x = w // 2
        run = h - 2 * ax
        thumb_h = max(14, int(view / float(total) * run))
        maxo = self.log.max_offset()
        f = (self.log.offset / float(maxo)) if maxo else 1.0
        y0 = ax + int(f * (run - thumb_h))
        sb.create_rectangle(x - 3, ax, x + 3, h - ax, fill="#9a9a9a",
                            outline="#707070")
        sb.create_rectangle(x - 8, y0, x + 8, y0 + thumb_h,
                            fill="#3f3f3f", outline="#101010")
        # arrows: up = older rows, down = newer rows
        sb.create_polygon(x, 4, x - 5, 12, x + 5, 12, fill="#505050")
        sb.create_polygon(x, h - 4, x - 5, h - 12, x + 5, h - 12,
                          fill="#505050")

    def log_sb_jump(self, event):
        """Click / drag on the column: jump the window to that fraction
           of the log, like the filmstrip bar does horizontally."""
        if not self.log.scrollable():
            return
        # a column that was just packed has not been drawn yet, so its
        # actual height still reads 1: fall back to the requested height,
        # which set_log_scrollbar has just configured
        h = self.log_sb.winfo_height()
        if h < 24:
            h = self.log_sb.winfo_reqheight()
        if h < 28:
            return
        ax = 14
        f = max(0.0, min(1.0, (event.y - ax) / float(h - 2 * ax)))
        self.log.set_offset(f * self.log.max_offset())
        # at the very bottom the user clearly wants to watch again
        self.log.follow = self.log.offset >= self.log.max_offset()
        self.refresh_log()

    def log_wheel(self, event):
        """Wheel over the column or over the log panel: scrub by a few
           lines at a time.  X11 reports no <MouseWheel> and no delta:
           its single ButtonMotion-1 event means "down" and Alt-B1 the
           opposite (same probing the filmstrip wheel handler uses).
           A wheel at the very bottom re-arms tail following, so a run
           that has just finished can be watched again by scrolling down."""
        if not self.log.scrollable():
            return
        d = getattr(event, "delta", None)
        if not d:
            d = -120 if "Alt-B1" in str(event.name) else 120
        step = max(1, self.log.view // 4)
        self.log.set_offset(self.log.offset + (-step if d > 0 else step))
        self.log.follow = self.log.offset >= self.log.max_offset()
        self.refresh_log()

    # ---------------------------------------------- va02: external play
    def _launch_player(self, path, t, stop=None):
        """Shared launcher for the PLAY buttons: start the best
           external player (mpv/vlc/ffplay, else the OS association)
           for `path` at t seconds; report what happened in the log.
           va03: `stop` makes it a trimmed range (start → stop)."""
        argv, name, can_seek = player_argv(path, t, stop)
        if not argv:
            self.log.insert("end", ("\nno external player found (mpv, vlc, "
                                    "ffplay or xdg-open) — nothing started\n"))
            self.log.see("end")
            return False
        try:
            # detached: the player window is independent of the Tk app
            subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as e:
            self.log.insert("end", f"\ncould not start player: {e}\n")
            self.log.see("end")
            return False
        if stop is None:
            msg = (f"external player started: {name} — playing from t = "
                   f"{fmt_num(t)} s ({fmt_clock(t)})")
        else:
            msg = (f"external player started: {name} — playing the trimmed "
                   f"range {fmt_num(t)} s ({fmt_clock(t)}) → {fmt_num(stop)} "
                   f"s ({fmt_clock(stop)}); it stops at MARK END")
        if not can_seek:
            msg += (" from the beginning: the OS-associated app cannot be "
                    "told where to start (install mpv or vlc to seek "
                    "from the selected frame)")
        self.log.insert("end", "\n" + msg + "\n")
        self.log.see("end")
        return True

    def play_external(self):
        """PLAY from here: open the CURRENT video in the external
           player starting at the selected playhead position."""
        if self.video:
            self._launch_player(self.video, self.play_t)
    
    def play_fromstart(self):
        """PLAY from start: open the CURRENT video in the external
           player."""
        if self.video:
            self._launch_player(self.video,0)

    def play_trimmed(self):
        """PLAY trimmed: open the CURRENT video in the external player
           seeked to MARK START and stopped at MARK END — the exact
           range the cut command would produce, previewed without
           cutting anything (mpv --end= / vlc --stop-time= / ffplay -to).
           The marks are used as they are; in fast copy mode the written
           command snaps to the nearest I-frames, the preview does not."""
        if not self.video:
            self.log.insert("end", ("\nno video loaded — nothing to play\n"))
            self.log.see("end")
            return
        s, e = self.start, self.end
        if e <= s:
            self.log.insert("end", ("\nMARK END is not after MARK START "
                                    "— mark a start and an end key frame "
                                    "first, then PLAY trimmed\n"))
            self.log.see("end")
            return
        self._launch_player(self.video, s, e)

    def play_result(self):
        """PLAY result: open the output file produced by the last Run
           command (self.out_path) in the external player.  If the
           run has not happened yet or the file is gone, say so."""
        if not self.out_path:
            self.log.insert("end", ("\nno result yet — click Run command "
                                    "first\n"))
            self.log.see("end")
            return
        if not os.path.exists(self.out_path):
            self.log.insert("end", (f"\nresult file not found: "
                                    f"{self.out_path}\n"))
            self.log.see("end")
            return
        self._launch_player(self.out_path, 0.0)


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
                              "commas, gvfs links)")
    app.root.mainloop()


if __name__ == "__main__":
    main()
