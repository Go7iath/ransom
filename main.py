import ppap
import tkinter as tk

EXIT_WORD = "charliekirk"
BUFFER_MAX = 32


def block(event=None):
    return "break"


def install_word_exit(root, word=EXIT_WORD):
    buffer = {"text": ""}

    def on_key(event):
        ch = event.char
        if not ch or not ch.isprintable():
            return
        buffer["text"] = (buffer["text"] + ch.lower())[-BUFFER_MAX:]
        if buffer["text"].endswith(word):
            buffer["text"] = ""
            root.destroy()

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


def main():
    root, app = ppap.create_window()

    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)

    root.protocol("WM_DELETE_WINDOW", block)
    root.bind_all("<Alt-F4>", block)
    root.bind_all("<Escape>", block)

    # Chords
    root.bind_all("<Control-Shift-Q>", lambda e: root.destroy())


    # Typed word
    install_word_exit(root, word=EXIT_WORD)

    root.after(2000, lambda: regrab_focus(root))
    root.mainloop()


if __name__ == "__main__":
    main()
