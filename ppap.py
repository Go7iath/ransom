import tkinter as tk
from tkinter import messagebox
from functools import partial
import random
import os
import sys
import shutil
import ctypes
import subprocess
import atexit
import signal

MAX_ATTEMPTS = 3
CAPTCHA_COUNT = 10
CAPTCHA_LEN = 5
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

CANVAS_W = 520
CANVAS_H = 260

HERE = os.path.dirname(os.path.abspath(__file__))
PNG_PATH = os.path.join(HERE, "myimage.png")
BG_PATH  = os.path.join(HERE, "shrekbg.png")
BGM_PATH = os.path.join(HERE, "bgsound.mp3")

FRAME_MS = 16
LOGO_COUNT = 10
LOGO_SPEED_MIN = 2
LOGO_SPEED_MAX = 7
LOGO_TARGET_SIZE = 200

WIN_W = 900
WIN_H = 650

BGM_VOLUME = 80          # percent, used to build player launch flags
BGM_ENFORCE_MS = 1000    # how often to check the player is alive


def random_captcha_text(length=CAPTCHA_LEN):
    return "".join(random.choice(CAPTCHA_CHARS) for _ in range(length))


def stretch_photo(photo, target_w, target_h):
    """
    Stretch a tk.PhotoImage to roughly (target_w, target_h) using
    only zoom() and subsample() (integer-only, approximate).
    """
    if target_w < 1 or target_h < 1:
        return photo
    iw, ih = photo.width(), photo.height()
    if iw < 1 or ih < 1:
        return photo

    Z = max(
        4,
        (target_w + iw - 1) // iw,
        (target_h + ih - 1) // ih,
    )
    zoomed = photo.zoom(Z, Z)
    zw, zh = zoomed.width(), zoomed.height()
    sx = max(1, zw // target_w)
    sy = max(1, zh // target_h)
    return zoomed.subsample(sx, sy)


class PPAP:
    def __init__(self, root):
        self.root = root
        self.solved = 0
        self.text = ""
        self.attempts = MAX_ATTEMPTS

        # logos
        self.logo_img = None
        self.logos = []

        # background stretch
        self.bg_raw = None
        self.bg_image = None
        self.bg_item = None
        self._bg_pending = None

        # music
        self._music_proc = None      # Linux subprocess
        self._bgm_alias = None       # Windows MCI alias
        self._bgm_player = None      # "ffplay" | "mpv" | "mpg123" | "cvlc" | "mci"
        self._bgm_lock_job = None    # after() id for restart loop
        self._closing = False

        self.root.title("PPAP")
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.configure(bg="#101018")

        self.build_ui()
        self.new_captcha()
        self.start_logos()
        self.play_bgm()
        self._enforce_bgm_volume()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        atexit.register(self.stop_bgm)
        self.root.after(5 * 60 * 1000, self._auto_close)

    # ---------------------------------------------------------------
    # UI / layering
    # ---------------------------------------------------------------
    def _auto_close(self):
        self._on_close()

    def build_ui(self):
        # ============================================================
        # LAYER 0 (bottom): stretched background image
        # ============================================================
        self.bg_canvas = tk.Canvas(self.root, highlightthickness=0, bd=0,
                                   bg="#101018")
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)

        self.bg_raw = tk.PhotoImage(file=BG_PATH)
        self._stretch_bg(WIN_W, WIN_H)
        self.bg_item = self.bg_canvas.create_image(0, 0,
                                                   image=self.bg_image,
                                                   anchor="nw")
        self.bg_canvas.bind("<Configure>", self._on_bg_resize)

        # ============================================================
        # LAYER 1: mid panel
        # ============================================================
        self.mid_canvas = tk.Canvas(self.root,
                                    width=CANVAS_W - 60,
                                    height=CANVAS_H - 40,
                                    bg="#0a0a14",
                                    highlightthickness=0)
        self.mid_canvas.place(relx=0.5, rely=0.5, anchor="center")
        self.mid_canvas.create_text(10, 10, anchor="nw",
                                    text="layer 1",
                                    fill="#8a8aff", font=("Helvetica", 10))

        # ============================================================
        # LAYER 2: captcha
        # ============================================================
        self.captcha_canvas = tk.Canvas(self.root,
                                        width=CANVAS_W - 120,
                                        height=CANVAS_H - 80,
                                        bg="#ffffff",
                                        highlightthickness=0)
        self.captcha_canvas.place(relx=0.5, rely=0.5, anchor="center")

        # ============================================================
        # LAYER 3: interactive widgets
        # ============================================================
        tk.Label(self.root, text="CAPTCHA CHALLENGE",
                 bg="#101018", fg="#ffffff",
                 font=("Helvetica", 18, "bold")).place(relx=0.5, y=10, anchor="n")

        self.progress = tk.Label(self.root, text=f"0 / {CAPTCHA_COUNT}",
                                 bg="#101018", fg="#9fe870",
                                 font=("Helvetica", 12))
        self.progress.place(relx=0.5, y=45, anchor="n")

        self.entry = tk.Entry(self.root, font=("Helvetica", 16),
                              justify="center", width=15)
        self.entry.place(relx=0.5, rely=0.78, anchor="center")
        self.entry.bind("<Return>", lambda e: self.check())

        keypad = tk.Frame(self.root, bg="#101018")
        keypad.place(relx=0.5, rely=0.88, anchor="center")
        for i, ch in enumerate(CAPTCHA_CHARS):
            r, c = divmod(i, 9)
            tk.Button(keypad, text=ch, width=3,
                      command=partial(self.add_char, ch)
                      ).grid(row=r, column=c, padx=1, pady=1)

        controls = tk.Frame(self.root, bg="#101018")
        controls.place(relx=0.5, rely=0.97, anchor="s")
        tk.Button(controls, text="Clear",   width=8,
                  command=self.clear_entry).grid(row=0, column=0, padx=3)
        tk.Button(controls, text="Refresh", width=8,
                  command=self.new_captcha).grid(row=0, column=1, padx=3)
        tk.Button(controls, text="Submit",  width=8,
                  command=self.check).grid(row=0, column=2, padx=3)

        self.feedback = tk.Label(self.root, text="",
                                 bg="#101018", fg="#9fe870",
                                 font=("Helvetica", 11))
        self.feedback.place(relx=0.5, rely=0.72, anchor="center")

        self.entry.focus_force()

    # ---------------------------------------------------------------
    # Background stretch
    # ---------------------------------------------------------------
    def _stretch_bg(self, w, h):
        self.bg_image = stretch_photo(self.bg_raw, w, h)

    def _on_bg_resize(self, event):
        if self._bg_pending is not None:
            self.root.after_cancel(self._bg_pending)
        self._bg_pending = self.root.after(
            60, lambda: self._apply_bg_resize(event.width, event.height)
        )

    def _apply_bg_resize(self, w, h):
        self._bg_pending = None
        if w < 2 or h < 2:
            return
        self._stretch_bg(w, h)
        self.bg_canvas.itemconfig(self.bg_item, image=self.bg_image)
        self.bg_canvas.tag_lower(self.bg_item)

    # ---------------------------------------------------------------
    # Logos
    # ---------------------------------------------------------------
    def load_logo(self):
        if not os.path.exists(PNG_PATH):
            print(f"Missing image: {PNG_PATH}")
            return None
        try:
            img = tk.PhotoImage(file=PNG_PATH)
            x_factor = max(1, round(img.width()  / LOGO_TARGET_SIZE))
            y_factor = max(1, round(img.height() / LOGO_TARGET_SIZE))
            return img.subsample(x_factor, y_factor)
        except tk.TclError as e:
            print(f"Could not load {PNG_PATH}: {e}")
            return None

    def start_logos(self):
        self.logo_img = self.load_logo()
        if self.logo_img is None:
            return

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        iw = self.logo_img.width()
        ih = self.logo_img.height()

        for _ in range(LOGO_COUNT):
            x = random.randint(0, max(0, sw - iw))
            y = random.randint(0, max(0, sh - ih))
            dx = random.choice([-1, 1]) * random.randint(LOGO_SPEED_MIN, LOGO_SPEED_MAX)
            dy = random.choice([-1, 1]) * random.randint(LOGO_SPEED_MIN, LOGO_SPEED_MAX)

            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="black")
            tk.Label(win, image=self.logo_img, bd=0, bg="black").pack()
            win.geometry(f"{iw}x{ih}+{x}+{y}")

            self.logos.append({
                "win": win, "x": x, "y": y, "dx": dx, "dy": dy,
                "iw": iw, "ih": ih,
            })

        self.animate_logos()

    def animate_logos(self):
        try:
            if self.logos and self.logo_img is not None:
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()

                for lg in self.logos:
                    lg["x"] += lg["dx"]
                    lg["y"] += lg["dy"]
                    iw, ih = lg["iw"], lg["ih"]

                    if lg["x"] <= 0:
                        lg["x"] = 0
                        lg["dx"] = abs(lg["dx"])
                    elif lg["x"] + iw >= sw:
                        lg["x"] = sw - iw
                        lg["dx"] = -abs(lg["dx"])

                    if lg["y"] <= 0:
                        lg["y"] = 0
                        lg["dy"] = abs(lg["dy"])
                    elif lg["y"] + ih >= sh:
                        lg["y"] = sh - ih
                        lg["dy"] = -abs(lg["dy"])

                    lg["win"].geometry(f"+{lg['x']}+{lg['y']}")
        except tk.TclError:
            return

        self.root.after(FRAME_MS, self.animate_logos)

    # ---------------------------------------------------------------
    # Background music (volume locked from main.py)
    # ---------------------------------------------------------------
    def play_bgm(self):
        if not os.path.exists(BGM_PATH):
            print(f"No music file at {BGM_PATH}")
            return

        if sys.platform.startswith("win"):
            # Windows MCI — volume pinned from main.py via waveOutSetVolume.
            try:
                mci = ctypes.windll.winmm.mciSendStringW
                self._bgm_alias = f"bgm{os.getpid()}"
                mci(f'open "{BGM_PATH}" type mpegvideo alias {self._bgm_alias}',
                    None, 0, None)
                mci(f"play {self._bgm_alias} repeat", None, 0, None)
                self._bgm_player = "mci"
                print(f"Playing bgm via MCI at {BGM_VOLUME}%")
            except Exception as e:
                print(f"Could not start music on Windows: {e}")
                self._bgm_alias = None
                self._bgm_player = None
            return

        # Linux — each candidate launches with its own software volume
        # pinned to BGM_VOLUME. System sink volume is locked from main.py.
        candidates = [
            ("ffplay", ["ffplay", "-nodisp", "-loglevel", "quiet",
                        "-volume", str(BGM_VOLUME), "-loop", "0", BGM_PATH]),
            ("mpv",    ["mpv", "--no-video", "--loop=inf",
                        "--really-quiet", f"--volume={BGM_VOLUME}", BGM_PATH]),
            ("mpg123", ["mpg123", "--loop", "-1", "-q",
                        "-f", str(int(32768 * BGM_VOLUME / 100)), BGM_PATH]),
            ("cvlc",   ["cvlc", "--loop", "--quiet",
                        "--intf", "dummy",
                        "--volume", str(int(512 * BGM_VOLUME / 100)), BGM_PATH]),
        ]
        for name, args in candidates:
            if shutil.which(name):
                try:
                    self._music_proc = subprocess.Popen(
                        args,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    self._bgm_player = name
                    print(f"Playing bgm via {name} at {BGM_VOLUME}%")
                    return
                except Exception as e:
                    print(f"{name} failed: {e}")
        print("No MP3 player found. Install ffmpeg or mpv.")

    def _enforce_bgm_volume(self):
        """Restart the BGM player if it was killed. Volume is locked in main.py."""
        if self._closing:
            return
        try:
            if self._bgm_player in ("ffplay", "mpv", "mpg123", "cvlc"):
                if self._music_proc is None or self._music_proc.poll() is not None:
                    print("BGM player exited; restarting.")
                    self._music_proc = None
                    self.play_bgm()
        except Exception as e:
            print(f"BGM enforcement error: {e}")

        try:
            self._bgm_lock_job = self.root.after(
                BGM_ENFORCE_MS, self._enforce_bgm_volume
            )
        except tk.TclError:
            pass

    def stop_bgm(self):
        self._closing = True

        # Cancel the restart loop.
        if self._bgm_lock_job is not None:
            try:
                self.root.after_cancel(self._bgm_lock_job)
            except Exception:
                pass
            self._bgm_lock_job = None

        # Windows: MCI stop + close.
        if self._bgm_alias:
            try:
                mci = ctypes.windll.winmm.mciSendStringW
                mci(f"stop {self._bgm_alias}", None, 0, None)
                mci(f"close {self._bgm_alias}", None, 0, None)
            except Exception:
                pass
            self._bgm_alias = None

        # Linux: SIGKILL the whole process group.
        proc = self._music_proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as e:
                print(f"killpg failed, falling back: {e}")
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self._music_proc = None
        self._bgm_player = None

    # ---------------------------------------------------------------
    # Close handler
    # ---------------------------------------------------------------
    def _on_close(self):
        self.stop_bgm()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ---------------------------------------------------------------
    # Captcha
    # ---------------------------------------------------------------
    def add_char(self, ch):
        self.entry.insert(tk.END, ch)

    def clear_entry(self):
        self.entry.delete(0, tk.END)

    def new_captcha(self):
        self.text = random_captcha_text()
        self.draw_captcha(self.text)
        self.clear_entry()
        self.entry.focus_force()

    def draw_captcha(self, text):
        c = self.captcha_canvas
        c.delete("captcha")

        w = int(c.winfo_width()) or (CANVAS_W - 120)
        h = int(c.winfo_height()) or (CANVAS_H - 80)

        for _ in range(10):
            c.create_line(random.randint(0, w), random.randint(0, h),
                          random.randint(0, w), random.randint(0, h),
                          fill="#d0d0d0", tags="captcha")
        for _ in range(40):
            x, y = random.randint(0, w), random.randint(0, h)
            c.create_oval(x, y, x + 2, y + 2,
                          fill="#a0a0a0", outline="", tags="captcha")

        n = len(text)
        step = w // (n + 1)
        for i, ch in enumerate(text):
            c.create_text(step * (i + 1) + random.randint(-6, 6),
                          h // 2 + random.randint(-10, 10),
                          text=ch,
                          fill=random.choice(["#202020", "#404040", "#1a1a5a"]),
                          font=("Helvetica", random.randint(28, 40), "bold"),
                          tags="captcha")

    def check(self):
        user = self.entry.get().strip().upper()
        if user == self.text:
            self.solved += 1
            self.progress.config(text=f"{self.solved} / {CAPTCHA_COUNT}")
            self.feedback.config(text="Correct!", fg="#9fe870")
            if self.solved >= CAPTCHA_COUNT:
                messagebox.showinfo("PPAP", "All captchas completed!")
                self._on_close()
                return
            self.new_captcha()
        else:
            self.feedback.config(text="Wrong, try again.", fg="#ff6b6b")
            self.clear_entry()


def create_window():
    root = tk.Tk()
    app = PPAP(root)
    return root, app


if __name__ == "__main__":
    root = tk.Tk()
    app = PPAP(root)
    root.mainloop()
