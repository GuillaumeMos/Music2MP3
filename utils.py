import os, re, platform, subprocess
import tkinter as tk

DEFAULT_DROP_BG = '#e0e0e0'
LOADED_DROP_BG  = '#c0ffc0'

class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind('<Enter>', self.show)
        widget.bind('<Leave>', self.hide)
    def show(self, _):
        if self.tip or not self.text:
            return
        x,y,_cx,cy = self.widget.bbox('insert') if self.widget.bbox('insert') else (0,0,0,0)
        x += self.widget.winfo_rootx() + 25
        y += cy + self.widget.winfo_rooty() + 25
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f'+{x}+{y}')
        tk.Label(self.tip, text=self.text, bg='yellow', relief='solid', bd=1).pack()
    def hide(self, _):
        if self.tip:
            self.tip.destroy()
            self.tip = None

# Helpers OS

def open_folder(path: str):
    if not (path and os.path.isdir(path)):
        return False
    if platform.system() == "Windows":
        os.startfile(path)
    else:
        subprocess.run(['open', path])
    return True

# Helpers Noms

def safe_name(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s or "").strip()