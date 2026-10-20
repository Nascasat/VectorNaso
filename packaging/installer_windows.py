from __future__ import annotations

import base64
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
import zipfile


APP_NAME = "VectorNaso"
INSTALL_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME


def bundled_zip() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "VectorNaso-Windows.zip"


def create_start_menu_shortcut(executable: Path) -> None:
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
    ps = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{str(shortcut).replace(chr(39), chr(39) * 2)}');"
        f"$s.TargetPath='{str(executable).replace(chr(39), chr(39) * 2)}';"
        f"$s.WorkingDirectory='{str(INSTALL_DIR).replace(chr(39), chr(39) * 2)}';"
        f"$s.IconLocation='{str(executable).replace(chr(39), chr(39) * 2)},0';"
        "$s.Save()"
    )
    encoded = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Non è stato possibile creare il collegamento nel menu Start.")


class Installer:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Installa VectorNaso")
        root.geometry("480x230")
        root.resizable(False, False)
        root.configure(bg="#f4f6fa")

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6fa")
        style.configure("Title.TLabel", background="#f4f6fa", foreground="#111827", font=("Segoe UI", 17, "bold"))
        style.configure("Body.TLabel", background="#f4f6fa", foreground="#526079", font=("Segoe UI", 10))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 9))

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="VectorNaso", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Installa l’app e i 10 campioni nella cartella utente. Non serve installare Python.",
            style="Body.TLabel",
            wraplength=420,
        ).pack(anchor="w", pady=(8, 18))
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))
        self.status = ttk.Label(frame, text="Pronto per l’installazione", style="Body.TLabel")
        self.status.pack(anchor="w")
        self.button = ttk.Button(frame, text="Installa", style="Accent.TButton", command=self.install)
        self.button.pack(anchor="e", pady=(12, 0))

    def install(self) -> None:
        self.button.configure(state="disabled")
        self.status.configure(text="Installazione in corso…")
        self.root.update_idletasks()
        try:
            archive = bundled_zip()
            INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                members = bundle.infolist()
                total = max(1, len(members))
                install_root = INSTALL_DIR.resolve()
                for index, member in enumerate(members, start=1):
                    target = (INSTALL_DIR / member.filename).resolve()
                    if target != install_root and install_root not in target.parents:
                        raise RuntimeError("Il pacchetto contiene un percorso non valido.")
                    bundle.extract(member, INSTALL_DIR)
                    self.progress["value"] = index * 100 / total
                    if index % 25 == 0:
                        self.root.update_idletasks()

            executable = INSTALL_DIR / "VectorNaso.exe"
            if not executable.exists():
                raise RuntimeError("VectorNaso.exe non è presente nel pacchetto.")
            create_start_menu_shortcut(executable)
            self.status.configure(text="Installazione completata")
            messagebox.showinfo("VectorNaso installato", "VectorNaso è pronto. Sto aprendo l’app.", parent=self.root)
            subprocess.Popen([str(executable)], cwd=str(INSTALL_DIR))
            self.root.destroy()
        except Exception as exc:
            self.status.configure(text="Installazione non completata")
            self.button.configure(state="normal")
            messagebox.showerror("Errore di installazione", str(exc), parent=self.root)


if __name__ == "__main__":
    window = tk.Tk()
    Installer(window)
    window.mainloop()
