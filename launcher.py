"""
launcher.py — Mindinguflac first-run extractor + launcher.

First run (or after a version change):
  - Shows a native-looking setup window (light/dark follows system theme)
  - User clicks Unpack to start extraction
  - Extracts bundle.zip to %LOCALAPPDATA%\Mindinguflac\app\<build_id>\
  - Cleans up previous version directories
  - Marks extraction complete with .ok

Subsequent runs: skips straight to launching the extracted app.
"""

import os
import sys
import pathlib
import shutil
import subprocess
import threading
import zipfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_id() -> str:
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
    try:
        return (base / "_build_id.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def _local_appdata() -> pathlib.Path:
    v = os.environ.get("LOCALAPPDATA", "")
    return pathlib.Path(v) if v else pathlib.Path.home() / "AppData" / "Local"


def _launcher_exe() -> pathlib.Path:
    return pathlib.Path(sys.executable)


def _is_dark_mode() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        return False


def _create_shortcut(special_folder: str, name: str, target: pathlib.Path) -> None:
    """Create a .lnk in a Windows special folder resolved by PowerShell.
    special_folder: "Desktop", "Programs", etc. (Environment.SpecialFolder names)
    """
    try:
        target_str = str(target).replace("\\", "\\\\")
        workdir    = str(target.parent).replace("\\", "\\\\")
        script = (
            f'$folder = [Environment]::GetFolderPath("{special_folder}"); '
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("$folder\\{name}"); '
            f'$s.TargetPath = "{target_str}"; '
            f'$s.WorkingDirectory = "{workdir}"; '
            f'$s.Save()'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Extraction window
# ---------------------------------------------------------------------------

def _apply_dark_titlebar(hwnd: int) -> None:
    """Tell DWM to render a dark title bar (Windows 10 20H1+ / Windows 11)."""
    try:
        import ctypes
        val = ctypes.c_int(1)
        for attr in (20, 19):   # 20 = Win11, 19 = Win10 build 18985+
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def _make_toggle(tk, parent, text: str, var, bg: str, fg: str) -> None:
    """Custom checkbox that fully respects bg/fg — avoids native GDI indicator."""
    CHECKED   = "☑"
    UNCHECKED = "☐"

    def _toggle(_event=None):
        var.set(not var.get())
        ind.config(text=CHECKED if var.get() else UNCHECKED)

    f = tk.Frame(parent, bg=bg, cursor="hand2")
    f.bind("<Button-1>", _toggle)

    ind = tk.Label(f, text=CHECKED if var.get() else UNCHECKED,
                   bg=bg, fg=fg, font=("Segoe UI", 10), cursor="hand2")
    ind.pack(side="left")
    ind.bind("<Button-1>", _toggle)

    lbl = tk.Label(f, text=f"  {text}", bg=bg, fg=fg,
                   font=("Segoe UI", 9), cursor="hand2")
    lbl.pack(side="left")
    lbl.bind("<Button-1>", _toggle)

    f.pack(side="left", padx=14)


def _run_extraction_ui(bundle: pathlib.Path, target: pathlib.Path) -> dict:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        _extract_silent(bundle, target)
        return {"desktop": False, "startmenu": False}

    dark = _is_dark_mode()

    bg     = "#1c1c1c" if dark else "#ffffff"
    fg     = "#ffffff" if dark else "#000000"
    fg_sub = "#aaaaaa" if dark else "#555555"

    result       = {"desktop": True, "startmenu": True}
    progress_ref = [0]
    done_event   = threading.Event()
    error_ref    = [None]
    extracting   = [False]

    root = tk.Tk()
    root.title("Mindinguflac Setup")
    root.resizable(False, False)
    root.configure(bg=bg)
    root.geometry("460x240")
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"460x240+{(sw - 460) // 2}+{(sh - 240) // 2}")
    root.attributes("-topmost", True)

    def _on_close():
        if not extracting[0]:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)

    if dark:
        root.update()
        _apply_dark_titlebar(root.winfo_id())

    style = ttk.Style(root)
    try:
        style.theme_use("vista")
    except Exception:
        style.theme_use("default")

    tk.Label(root, text="Mindinguflac Setup",
             bg=bg, fg=fg, font=("Segoe UI", 12, "bold")).pack(pady=(22, 3))
    tk.Label(root,
             text="Files need to be unpacked on first run.\nThis only happens once.",
             bg=bg, fg=fg_sub, font=("Segoe UI", 9), justify="center").pack()

    cb_frame = tk.Frame(root, bg=bg)
    cb_frame.pack(pady=(14, 0))

    var_desktop   = tk.BooleanVar(value=True)
    var_startmenu = tk.BooleanVar(value=True)
    _make_toggle(tk, cb_frame, "Desktop shortcut",   var_desktop,   bg, fg)
    _make_toggle(tk, cb_frame, "Start Menu shortcut", var_startmenu, bg, fg)

    bar = ttk.Progressbar(root, length=420, mode="determinate", maximum=100)
    bar.pack(pady=(14, 0))
    bar.pack_forget()

    status_lbl = tk.Label(root, text="", bg=bg, fg=fg_sub, font=("Segoe UI", 8))
    status_lbl.pack(pady=(4, 0))

    btn = ttk.Button(root, text="Unpack")
    btn.pack(pady=(10, 0))

    def _on_unpack():
        extracting[0] = True
        btn.pack_forget()
        bar.pack(pady=(14, 0))
        status_lbl.config(text="Extracting...")
        result["desktop"]   = var_desktop.get()
        result["startmenu"] = var_startmenu.get()
        threading.Thread(target=_worker, daemon=True).start()
        root.after(80, _tick)

    btn.config(command=_on_unpack)

    def _tick():
        bar["value"] = progress_ref[0]
        if done_event.is_set():
            bar["value"] = 100
            status_lbl.config(text="Done. Launching...")
            root.update()
            root.after(800, root.destroy)
        else:
            root.after(80, _tick)

    def _worker():
        try:
            _extract_with_progress(bundle, target, progress_ref)
        except Exception as exc:
            error_ref[0] = exc
        finally:
            done_event.set()

    root.mainloop()

    if error_ref[0]:
        raise error_ref[0]

    return result


def _extract_with_progress(bundle: pathlib.Path, target: pathlib.Path,
                            progress_ref: list) -> None:
    with zipfile.ZipFile(bundle) as zf:
        members = zf.infolist()
        total = max(len(members), 1)
        for i, member in enumerate(members, 1):
            zf.extract(member, target)
            progress_ref[0] = int(i / total * 100)


def _extract_silent(bundle: pathlib.Path, target: pathlib.Path) -> None:
    with zipfile.ZipFile(bundle) as zf:
        zf.extractall(target)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    bid      = _build_id()
    app_root = _local_appdata() / "Mindinguflac" / "app"
    target   = app_root / bid
    marker   = target / ".ok"
    app_exe  = target / "Mindinguflac.exe"
    bundle   = pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "bundle.zip"

    if not marker.exists() or not app_exe.exists():
        # Remove stale version directories
        if app_root.exists():
            for d in app_root.iterdir():
                if d.is_dir() and d.name != bid:
                    shutil.rmtree(d, ignore_errors=True)

        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)

        prefs = _run_extraction_ui(bundle, target)
        marker.touch()

        launcher = _launcher_exe()

        if prefs.get("desktop"):
            _create_shortcut("Desktop", "Mindinguflac.lnk", launcher)

        if prefs.get("startmenu"):
            _create_shortcut("Programs", "Mindinguflac.lnk", launcher)

    subprocess.Popen(
        [str(app_exe)] + sys.argv[1:],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


if __name__ == "__main__":
    main()
