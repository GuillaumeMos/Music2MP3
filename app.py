import tkinter as tk
try:
    from tkinterdnd2 import TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

from gui import Music2MP3GUI

def main():
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()

    app = Music2MP3GUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()