"""
launcher.py — Mindinguflac first-run extractor + launcher.

First run (or after a version change):
  - Extracts bundle.zip to %LOCALAPPDATA%\Mindinguflac\app\<build_id>\
  - Shows a themed progress window with desktop/Start-Menu shortcut options
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
    """Path to the running launcher exe (stable shortcut target)."""
    return pathlib.Path(sys.executable)


def _create_shortcut(link_path: pathlib.Path, target: pathlib.Path) -> None:
    """Create a Windows .lnk shortcut via PowerShell (no extra dependencies)."""
    try:
        script = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{link_path}"); '
            f'$s.TargetPath = "{target}"; '
            f'$s.WorkingDirectory = "{target.parent}"; '
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
# Extraction window (tkinter runs in main thread, extraction in a worker)
# ---------------------------------------------------------------------------

def _run_extraction_ui(bundle: pathlib.Path, target: pathlib.Path) -> dict:
    """
    Shows progress window, runs extraction in a background thread.
    Returns {"desktop": bool, "startmenu": bool} from checkbox state.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        # tkinter unavailable — extract silently
        _extract_silent(bundle, target)
        return {"desktop": False, "startmenu": False}

    result = {"desktop": True, "startmenu": True}
    progress_ref = [0]
    done_event = threading.Event()
    error_ref = [None]

    root = tk.Tk()
    root.title("Mindinguflac")
    root.resizable(False, False)
    root.configure(bg="#16213e")
    root.geometry("460x210")
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"460x210+{(sw - 460) // 2}+{(sh - 210) // 2}")
    root.attributes("-topmost", True)
    root.protocol("WM_DELETE_WINDOW", lambda: None)  # disable close during extraction

    # Title
    tk.Label(
        root, text="Setting up Mindinguflac",
        bg="#16213e", fg="#ffffff", font=("Segoe UI", 13, "bold"),
    ).pack(pady=(20, 3))
    tk.Label(
        root, text="First run — extracting files. This only happens once.",
        bg="#16213e", fg="#888888", font=("Segoe UI", 9),
    ).pack()

    # Progress bar
    style = ttk.Style(root)
    style.theme_use("default")
    style.configure(
        "mf.Horizontal.TProgressbar",
        troughcolor="#0f3460", background="#1db954",
        bordercolor="#16213e", lightcolor="#1db954", darkcolor="#1db954",
    )
    bar = ttk.Progressbar(
        root, length=420, mode="determinate", maximum=100,
        style="mf.Horizontal.TProgressbar",
    )
    bar.pack(pady=12)

    # Shortcut checkboxes
    cb_frame = tk.Frame(root, bg="#16213e")
    cb_frame.pack()

    var_desktop = tk.BooleanVar(value=True)
    var_startmenu = tk.BooleanVar(value=True)

    tk.Checkbutton(
        cb_frame, text="Create desktop shortcut",
        variable=var_desktop, bg="#16213e", fg="#cccccc",
        selectcolor="#0f3460", activebackground="#16213e",
        font=("Segoe UI", 9),
    ).pack(side="left", padx=10)
    tk.Checkbutton(
        cb_frame, text="Add to Start Menu",
        variable=var_startmenu, bg="#16213e", fg="#cccccc",
        selectcolor="#0f3460", activebackground="#16213e",
        font=("Segoe UI", 9),
    ).pack(side="left", padx=10)

    status_lbl = tk.Label(
        root, text="Extracting...",
        bg="#16213e", fg="#555555", font=("Segoe UI", 8),
    )
    status_lbl.pack(pady=(8, 0))

    def _tick():
        bar["value"] = progress_ref[0]
        if done_event.is_set():
            result["desktop"] = var_desktop.get()
            result["startmenu"] = var_startmenu.get()
            status_lbl.config(text="Done. Launching...")
            bar["value"] = 100
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

    threading.Thread(target=_worker, daemon=True).start()
    root.after(80, _tick)
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
    bid = _build_id()
    app_root = _local_appdata() / "Mindinguflac" / "app"
    target = app_root / bid
    marker = target / ".ok"
    app_exe = target / "Mindinguflac.exe"
    bundle = pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "bundle.zip"

    needs_extract = not marker.exists() or not app_exe.exists()

    if needs_extract:
        # Remove stale version directories first
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
            desktop = pathlib.Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Desktop"
            _create_shortcut(desktop / "Mindinguflac.lnk", launcher)

        if prefs.get("startmenu"):
            start = (
                _local_appdata().parent / "Roaming"
                / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            )
            start.mkdir(parents=True, exist_ok=True)
            _create_shortcut(start / "Mindinguflac.lnk", launcher)

    subprocess.Popen(
        [str(app_exe)] + sys.argv[1:],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


if __name__ == "__main__":
    main()
