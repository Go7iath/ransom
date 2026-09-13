import ppap
import tkinter as tk
import sys
import ctypes
import shutil
import subprocess

EXIT_WORD = "charliekirk"
BUFFER_MAX = 32
BGM_VOLUME = 95		 # percent
ENFORCE_MS = 1000        # how often to re-assert volume


# ---------------------------------------------------------------
# Windows: pin the wave-out device volume
# ---------------------------------------------------------------
def set_volume_windows(vol_pct):
    """Pin the default wave-out device to vol_pct (0-100)."""
    vol = max(0, min(100, int(vol_pct)))
    level = int(0xFFFF * vol / 100)
    packed = (level & 0xFFFF) | (level << 16)
    try:
        ctypes.windll.winmm.waveOutSetVolume(0, packed)
    except Exception as e:
        print(f"waveOutSetVolume failed: {e}")


# ---------------------------------------------------------------
# Linux: pin the default sink volume via wpctl or pactl
# (both ship with the desktop; no install, no root needed)
# ---------------------------------------------------------------
def set_volume_linux(vol_pct):
    """Pin default audio sink to vol_pct. Tries wpctl, then pactl."""
    vol = max(0, min(100, int(vol_pct)))

    if shutil.which("wpctl"):
        # PipeWire — wpctl takes 0.0–1.0
        try:
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{vol/100:.2f}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
            return True
        except Exception as e:
            print(f"wpctl failed: {e}")

    if shutil.which("pactl"):
        # PulseAudio — pactl takes percent
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
            return True
        except Exception as e:
            print(f"pactl failed: {e}")

    return False


# ---------------------------------------------------------------
# Cross-platform volume setter
# ---------------------------------------------------------------
def set_volume(vol_pct=BGM_VOLUME):
    if sys.platform.startswith("win"):
        set_volume_windows(vol_pct)
    else:
        set_volume_linux(vol_pct)


def start_volume_lock(root, vol=BGM_VOLUME):
    """Re-assert volume every second on all platforms."""
    def enforce():
        set_volume(vol)
        try:
            root.after(ENFORCE_MS, enforce)
        except tk.TclError:
            pass

    set_volume(vol)   # set once immediately
    root.after(ENFORCE_MS, enforce)


# ---------------------------------------------------------------
# UI locking helpers
# ---------------------------------------------------------------
def block(event=None):
    return "break"


def install_word_exit(root, app, word=EXIT_WORD):
    buffer = {"text": ""}

    def on_key(event):
        ch = event.char
        if not ch or not ch.isprintable():
            return
        buffer["text"] = (buffer["text"] + ch.lower())[-BUFFER_MAX:]
        if buffer["text"].endswith(word):
            buffer["text"] = ""
            app._on_close()

    root.bind_all("<KeyPress>", on_key, add="+")


def regrab_focus(root):
    try:
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.after(2000, lambda: regrab_focus(root))
    except tk.TclError:
        pass


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
def main():
    root, app = ppap.create_window()

    # Lock system volume to 80% on Windows and Linux.
    start_volume_lock(root, BGM_VOLUME)

    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)

    root.protocol("WM_DELETE_WINDOW", block)
    root.bind_all("<Alt-F4>", block)
    root.bind_all("<Escape>", block)

    # Hidden exit chord
    root.bind_all("<Control-Shift-Q>", lambda e: app._on_close())

    # Media / volume keys — swallow them if Tk sees them first.
    # Names differ per platform; try each, ignore unknown keysyms.
    media_keys = (
        "<XF86AudioMute>", "<XF86AudioLowerVolume>", "<XF86AudioRaiseVolume>",
        "<XF86AudioPlay>", "<XF86AudioPause>", "<XF86AudioStop>",
        "<KeyPress-VolumeMute>", "<KeyPress-VolumeDown>", "<KeyPress-VolumeUp>",
    )
    for seq in media_keys:
        try:
            root.bind_all(seq, block)
        except tk.TclError:
            pass

    # Typed-word exit — routed through app._on_close so BGM dies cleanly.
    install_word_exit(root, app, word=EXIT_WORD)

    root.after(2000, lambda: regrab_focus(root))
    root.mainloop()


if __name__ == "__main__":
    main()
