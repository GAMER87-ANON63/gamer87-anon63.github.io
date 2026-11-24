"""
PC Hardware Dashboard - lightweight, dark-mode, Windows only.
Dependencies: psutil (everything else is in the Python standard library).
Run:  python hwinfo_dashboard.py
"""
import ctypes
import json
import platform
import subprocess
import sys
import threading
import tkinter as tk
import winreg

import psutil

# ---------- Theme ----------
BG = "#0f1115"
CARD = "#181b22"
BORDER = "#262a33"
TEXT = "#e6e8ee"
MUTED = "#8b92a3"
ACCENT = "#4f9cff"
WARN = "#ff9f43"
DANGER = "#ff5c5c"
FONT = "Segoe UI"


# ---------- Data collection ----------
def ps_json(command):
    """Run a PowerShell command that outputs JSON; always return a list of dicts."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"{command} | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
        if not out:
            return []
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def fmt_bytes(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024


def fmt_vram(n):
    gb = n / 1024 ** 3
    return f"{gb:.0f} GB" if gb >= 1 and abs(gb - round(gb)) < 0.05 else (
        f"{gb:.1f} GB" if gb >= 1 else f"{n / 1024 ** 2:.0f} MB")


def get_cpu():
    rows = ps_json("Get-CimInstance Win32_Processor | "
                   "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed")
    if rows:
        r = rows[0]
        return {
            "Name": " ".join(str(r.get("Name", "Unknown")).split()),
            "Cores": f"{r.get('NumberOfCores', '?')} physical / "
                     f"{r.get('NumberOfLogicalProcessors', '?')} logical",
            "Base clock": f"{(r.get('MaxClockSpeed') or 0) / 1000:.2f} GHz",
        }
    return {"Name": platform.processor() or "Unknown",
            "Cores": f"{psutil.cpu_count(logical=False)} physical / "
                     f"{psutil.cpu_count(logical=True)} logical"}


def gpu_vram_from_registry():
    """Real VRAM (64-bit) per adapter. Win32_VideoController.AdapterRAM caps at 4 GB."""
    result = {}
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        desc = winreg.QueryValueEx(k, "DriverDesc")[0]
                        mem = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                        if isinstance(mem, (bytes, bytearray)):
                            mem = int.from_bytes(mem, "little")
                        result[desc] = int(mem)
                except OSError:
                    continue
    except OSError:
        pass
    return result


def get_gpus():
    rows = ps_json("Get-CimInstance Win32_VideoController | "
                   "Select-Object Name,AdapterRAM,DriverVersion")
    reg = gpu_vram_from_registry()
    gpus = []
    for r in rows:
        name = r.get("Name") or "Unknown GPU"
        vram = reg.get(name) or r.get("AdapterRAM") or 0
        gpus.append({
            "Model": name,
            "VRAM": fmt_vram(vram) if vram else "Unknown",
            "Driver": r.get("DriverVersion") or "Unknown",
        })
    return gpus or [{"Model": "Not detected", "VRAM": "-", "Driver": "-"}]


def get_ram():
    total = psutil.virtual_memory().total
    sticks = ps_json("Get-CimInstance Win32_PhysicalMemory | "
                     "Select-Object Capacity,Speed,ConfiguredClockSpeed,SMBIOSMemoryType")
    info = {"Total": fmt_bytes(total)}
    if sticks:
        speed = max((s.get("ConfiguredClockSpeed") or s.get("Speed") or 0) for s in sticks)
        mem_type = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5"}.get(
            sticks[0].get("SMBIOSMemoryType"), "")
        info["Speed"] = f"{speed} MT/s {mem_type}".strip() if speed else "Unknown"
        info["Modules"] = " + ".join(fmt_bytes(s.get("Capacity") or 0) for s in sticks)
    return info


def get_board():
    rows = ps_json("Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product")
    bios = ps_json("Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion")
    info = {}
    if rows:
        info["Board"] = f"{rows[0].get('Manufacturer', '')} {rows[0].get('Product', '')}".strip()
    if bios:
        info["BIOS"] = bios[0].get("SMBIOSBIOSVersion", "Unknown")
    return info or {"Board": "Unknown"}


def get_windows():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            def val(name, default=""):
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except OSError:
                    return default
            build = int(val("CurrentBuildNumber", 0) or 0)
            product = val("ProductName", "Windows")
            if build >= 22000:  # registry still says "Windows 10" on Windows 11
                product = product.replace("Windows 10", "Windows 11")
            return {
                "Version": product,
                "Release": val("DisplayVersion") or val("ReleaseId"),
                "Build": f"{build}.{val('UBR', 0)}",
                "Architecture": platform.machine(),
            }
    except OSError:
        return {"Version": f"{platform.system()} {platform.release()}", "Build": platform.version()}


def get_drives():
    drives = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        drives.append({"mount": p.mountpoint, "fs": p.fstype,
                       "total": u.total, "free": u.free, "pct": u.percent})
    return drives


def collect():
    return {"cpu": get_cpu(), "gpus": get_gpus(), "ram": get_ram(),
            "board": get_board(), "win": get_windows(), "drives": get_drives()}


# ---------- UI ----------
class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PC Hardware Dashboard")
        self.configure(bg=BG)
        self.geometry("860x760")
        self.minsize(760, 560)
        self._dark_titlebar()

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 8))
        tk.Label(header, text="System Overview", bg=BG, fg=TEXT,
                 font=(FONT, 20, "bold")).pack(side="left")
        self.btn = tk.Label(header, text="⟳  Refresh", bg=ACCENT, fg="white",
                            font=(FONT, 10, "bold"), padx=14, pady=6, cursor="hand2")
        self.btn.pack(side="right")
        self.btn.bind("<Button-1>", lambda e: self.refresh())

        # Scrollable body
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(24, 8), pady=(0, 16))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        self.scroll = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.win_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self.win_id, width=e.width - 12))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.body.columnconfigure((0, 1), weight=1, uniform="col")

        self.refresh()

    def _dark_titlebar(self):
        try:
            self.update()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)
        except Exception:
            pass

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        tk.Label(self.body, text="Detecting hardware…", bg=BG, fg=MUTED,
                 font=(FONT, 11)).grid(row=0, column=0, columnspan=2, pady=40)
        self.btn.config(bg=BORDER)
        threading.Thread(target=lambda: self.after(0, self.render, collect()),
                         daemon=True).start()

    def card(self, title, row, col, span=1):
        outer = tk.Frame(self.body, bg=BORDER)
        outer.grid(row=row, column=col, columnspan=span, sticky="nsew", padx=6, pady=6)
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(inner, text=title.upper(), bg=CARD, fg=ACCENT,
                 font=(FONT, 9, "bold")).pack(anchor="w", padx=16, pady=(14, 6))
        return inner

    def rows(self, parent, data):
        for k, v in data.items():
            if not v:
                continue
            r = tk.Frame(parent, bg=CARD)
            r.pack(fill="x", padx=16, pady=2)
            tk.Label(r, text=k, bg=CARD, fg=MUTED, font=(FONT, 9), width=12,
                     anchor="nw").pack(side="left", anchor="n")
            tk.Label(r, text=str(v), bg=CARD, fg=TEXT, font=(FONT, 10, "bold"),
                     anchor="w", justify="left", wraplength=290).pack(side="left", fill="x")
        tk.Frame(parent, bg=CARD, height=12).pack()

    def render(self, d):
        for w in self.body.winfo_children():
            w.destroy()
        self.btn.config(bg=ACCENT)

        self.rows(self.card("Processor", 0, 0), d["cpu"])
        gpu_card = self.card("Graphics", 0, 1)
        for i, g in enumerate(d["gpus"]):
            if i:
                tk.Frame(gpu_card, bg=BORDER, height=1).pack(fill="x", padx=16, pady=6)
            self.rows(gpu_card, g)
        self.rows(self.card("Memory", 1, 0), d["ram"])
        self.rows(self.card("Motherboard", 1, 1), d["board"])
        self.rows(self.card("Operating System", 2, 0, span=2), d["win"])

        st = self.card("Storage", 3, 0, span=2)
        for dr in d["drives"]:
            row = tk.Frame(st, bg=CARD)
            row.pack(fill="x", padx=16, pady=6)
            top = tk.Frame(row, bg=CARD)
            top.pack(fill="x")
            tk.Label(top, text=f"{dr['mount']}  ({dr['fs']})", bg=CARD, fg=TEXT,
                     font=(FONT, 10, "bold")).pack(side="left")
            tk.Label(top, text=f"{fmt_bytes(dr['free'])} free of {fmt_bytes(dr['total'])}",
                     bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="right")
            bar = tk.Canvas(row, height=8, bg=BORDER, highlightthickness=0)
            bar.pack(fill="x", pady=(5, 0))
            color = DANGER if dr["pct"] >= 90 else WARN if dr["pct"] >= 75 else ACCENT
            bar.bind("<Configure>", lambda e, b=bar, p=dr["pct"], c=color: (
                b.delete("all"), b.create_rectangle(0, 0, e.width * p / 100, 8, fill=c, width=0)))
        tk.Frame(st, bg=CARD, height=10).pack()


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("This app is for Windows only.")
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on HiDPI screens
    except Exception:
        pass
    Dashboard().mainloop()