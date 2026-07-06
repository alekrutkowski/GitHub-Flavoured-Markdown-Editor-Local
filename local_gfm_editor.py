#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BUILD_ID = "2026-07-06-v7-drop-handle-dpi"
TEXT_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".txt", ""}
OPEN_FILETYPES = [
    ("Markdown files", "*.md *.markdown *.mdown *.mkd"),
    ("Text files", "*.txt"),
    ("All files", "*.*"),
]
SAVE_FILETYPES = [
    ("Markdown files", "*.md"),
    ("Text files", "*.txt"),
    ("All files", "*.*"),
]


def default_dialog_dir() -> Path:
    for candidate in (Path.home() / "Documents", Path.home()):
        try:
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
        except Exception:
            pass
    return Path.cwd().resolve()


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        try:
            # Windows 10+: per-monitor v2 gives the sharpest common dialogs.
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        except Exception:
            pass
        try:
            # Windows 8.1+: per-monitor DPI aware.
            if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
                return
        except Exception:
            pass
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass


def read_text_file(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")




def normalize_suggested_name(name: str) -> str:
    clean = (name or "untitled.md").strip()
    clean = "".join("-" if ch in r'\/:*?"<>|' else ch for ch in clean)
    clean = clean.strip().strip('.') or "untitled.md"
    if Path(clean).suffix.lower() not in {".md", ".markdown", ".mdown", ".mkd", ".txt"}:
        clean += ".md"
    return Path(clean).name


def normalize_initial(initial_path: str | None, suggested_name: str = "untitled.md") -> tuple[Path, str]:
    raw = (initial_path or "").strip().strip('"')
    if raw:
        p = Path(raw).expanduser()
        if p.exists() and p.is_dir():
            return p.resolve(), suggested_name or "untitled.md"
        if p.name:
            parent = p.parent if str(p.parent) not in ("", ".") else default_dialog_dir()
            return parent.expanduser().resolve(), p.name
    return default_dialog_dir(), suggested_name or "untitled.md"


def dialog_helper_main(payload_json: str) -> int:
    try:
        payload = json.loads(payload_json or "{}")
        kind = payload.get("kind") or "open"
        initial_path = payload.get("initial_path") or ""
        suggested_name = payload.get("suggested_name") or "untitled.md"
        initial_dir, initial_file = normalize_initial(initial_path, suggested_name)

        enable_windows_dpi_awareness()
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.title("Local Markdown Editor")
        try:
            dpi = root.winfo_fpixels("1i")
            if dpi and dpi > 0:
                root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
        try:
            root.geometry("1x1+80+80")
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            root.update()
            root.withdraw()
            root.update()
        except Exception:
            pass

        if kind == "open":
            selected = filedialog.askopenfilename(
                parent=root,
                title="Open Markdown file",
                initialdir=str(initial_dir),
                filetypes=OPEN_FILETYPES,
            )
        else:
            selected = filedialog.asksaveasfilename(
                parent=root,
                title="Save Markdown file",
                initialdir=str(initial_dir),
                initialfile=initial_file,
                defaultextension=".md",
                filetypes=SAVE_FILETYPES,
            )
        try:
            root.destroy()
        except Exception:
            pass
        print(json.dumps({"ok": True, "path": selected or ""}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), flush=True)
        return 1


def run_tk_dialog_subprocess(kind: str, initial_path: str | None = None, suggested_name: str = "untitled.md") -> Path | None:
    payload = json.dumps({"kind": kind, "initial_path": initial_path or "", "suggested_name": suggested_name})
    cmd = [sys.executable, str(Path(__file__).resolve()), "--_dialog_helper", payload]
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 1
    proc = subprocess.run(cmd, text=True, capture_output=True, startupinfo=startupinfo)
    output = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    if proc.returncode != 0:
        err = output[0] or (proc.stderr or "Tk dialog failed.").strip()
        try:
            parsed = json.loads(err)
            err = parsed.get("error") or err
        except Exception:
            pass
        raise RuntimeError(err)
    try:
        result = json.loads(output[0])
    except Exception as exc:
        raise RuntimeError(f"Dialog helper returned invalid output: {output[0]!r}") from exc
    if not result.get("ok", True):
        raise RuntimeError(result.get("error") or "Dialog helper failed.")
    path = result.get("path") or ""
    return Path(path).expanduser().resolve() if path else None


def run_powershell_winforms_dialog(kind: str, initial_path: str | None = None, suggested_name: str = "untitled.md") -> Path | None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        raise RuntimeError("PowerShell was not found.")
    initial_dir, initial_file = normalize_initial(initial_path, suggested_name)
    script = r'''
param([string]$Mode, [string]$InitialDirectory, [string]$InitialFile)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class DpiHelper {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int value);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  public static void Enable() {
    try { if (SetProcessDpiAwarenessContext(new IntPtr(-4))) return; } catch {}
    try { if (SetProcessDpiAwareness(2) == 0) return; } catch {}
    try { SetProcessDPIAware(); } catch {}
  }
}
"@
[DpiHelper]::Enable()
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try { [System.Windows.Forms.Application]::SetHighDpiMode([System.Windows.Forms.HighDpiMode]::PerMonitorV2) | Out-Null } catch {}
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Local Markdown Editor'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(1,1)
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.Opacity = 0
$form.Show()
$form.Activate()
if ($Mode -eq 'open') {
  $dialog = New-Object System.Windows.Forms.OpenFileDialog
  $dialog.Title = 'Open Markdown file'
  $dialog.Filter = 'Markdown files (*.md;*.markdown;*.mdown;*.mkd)|*.md;*.markdown;*.mdown;*.mkd|Text files (*.txt)|*.txt|All files (*.*)|*.*'
  $dialog.Multiselect = $false
} else {
  $dialog = New-Object System.Windows.Forms.SaveFileDialog
  $dialog.Title = 'Save Markdown file'
  $dialog.Filter = 'Markdown files (*.md)|*.md|Text files (*.txt)|*.txt|All files (*.*)|*.*'
  $dialog.DefaultExt = 'md'
  $dialog.AddExtension = $true
  $dialog.OverwritePrompt = $true
  if ($InitialFile) { $dialog.FileName = $InitialFile }
}
if ($InitialDirectory -and (Test-Path -LiteralPath $InitialDirectory)) { $dialog.InitialDirectory = $InitialDirectory }
$dialog.ShowHelp = $true
$result = $dialog.ShowDialog($form)
if ($result -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.WriteLine($dialog.FileName) }
$form.Close()
$form.Dispose()
'''
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        script_path = Path(fh.name)
    try:
        cmd = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Sta", "-File", str(script_path), kind, str(initial_dir), initial_file]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "Windows Forms dialog failed.").strip())
        selected = (proc.stdout or "").strip().splitlines()[-1:] or [""]
        return Path(selected[0]).expanduser().resolve() if selected[0] else None
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except Exception:
            pass


def run_zenity_or_kdialog(kind: str, initial_path: str | None = None, suggested_name: str = "untitled.md") -> Path | None:
    initial_dir, initial_file = normalize_initial(initial_path, suggested_name)
    zenity = shutil.which("zenity")
    if zenity:
        cmd = [zenity, "--file-selection", f"--title={'Open Markdown file' if kind == 'open' else 'Save Markdown file'}"]
        if kind != "open":
            cmd.append("--save")
            cmd.append("--confirm-overwrite")
            cmd.append(f"--filename={str(initial_dir / initial_file)}")
        else:
            cmd.append(f"--filename={str(initial_dir) + os.sep}")
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode == 0:
            selected = (proc.stdout or "").strip()
            return Path(selected).expanduser().resolve() if selected else None
        if proc.returncode == 1:
            return None
        raise RuntimeError((proc.stderr or proc.stdout or "zenity failed.").strip())
    kdialog = shutil.which("kdialog")
    if kdialog:
        cmd = [kdialog, "--getopenfilename", str(initial_dir), "*.md *.markdown *.mdown *.mkd *.txt"] if kind == "open" else [kdialog, "--getsavefilename", str(initial_dir / initial_file), "*.md *.markdown *.mdown *.mkd *.txt"]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode == 0:
            selected = (proc.stdout or "").strip()
            return Path(selected).expanduser().resolve() if selected else None
        if proc.returncode == 1:
            return None
        raise RuntimeError((proc.stderr or proc.stdout or "kdialog failed.").strip())
    raise RuntimeError("Neither zenity nor kdialog is available.")


def ask_dialog(kind: str, initial_path: str | None = None, suggested_name: str = "untitled.md", backend: str = "auto") -> Path | None:
    errors: list[str] = []
    if backend == "auto":
        order = ["winforms", "tk"] if os.name == "nt" else ["native", "tk"]
    else:
        order = [backend]
    for method in order:
        try:
            if method == "tk":
                return run_tk_dialog_subprocess(kind, initial_path, suggested_name)
            if method == "winforms":
                return run_powershell_winforms_dialog(kind, initial_path, suggested_name)
            if method == "native":
                return run_zenity_or_kdialog(kind, initial_path, suggested_name)
        except Exception as exc:
            errors.append(f"{method}: {exc}")
    raise RuntimeError("Could not open a native file dialog. " + " | ".join(errors))


class LocalEditorServer(HTTPServer):
    def __init__(self, server_address, handler_class, public_dir: Path, startup_path: Path | None, token: str, dialog_backend: str) -> None:
        super().__init__(server_address, handler_class)
        self.public_dir = public_dir
        self.startup_path = startup_path
        self.token = token
        self.dialog_backend = dialog_backend
        self.last_dir = (startup_path.parent if startup_path else default_dialog_dir()).resolve()


class Handler(BaseHTTPRequestHandler):
    server_version = f"LocalGfmEditor/{BUILD_ID}"

    @property
    def app_server(self) -> LocalEditorServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self) -> bool:
        return self.headers.get("X-Local-Editor-Token") == self.app_server.token

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/info":
            self.send_json({"ok": True, "build": BUILD_ID, "dialog_backend": self.app_server.dialog_backend})
            return
        if parsed.path.startswith("/api/"):
            self.send_json({"ok": False, "error": f"Unknown API endpoint for GET: {parsed.path}"}, status=404)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self.authorized():
            self.send_json({"ok": False, "error": "Unauthorized local editor request."}, status=403)
            return
        if parsed.path in {"/api/open", "/api/open-dialog", "/api/open_file", "/api/open-file"}:
            self.handle_open_dialog()
        elif parsed.path in {"/api/open-path", "/api/read-path", "/api/open-known-path"}:
            self.handle_open_path()
        elif parsed.path in {"/api/save", "/api/save-dialog", "/api/save-as", "/api/write", "/api/write-file"}:
            self.handle_save()
        else:
            self.send_json({"ok": False, "error": f"Unknown API endpoint for POST: {parsed.path}"}, status=404)

    def get_startup_payload(self) -> dict:
        path = self.app_server.startup_path
        if not path:
            return {"path": "", "name": "", "text": None}
        try:
            if not path.exists() or not path.is_file():
                return {"path": str(path), "name": path.name, "text": None, "error": f"Startup file does not exist: {path}"}
            return {"path": str(path), "name": path.name, "text": read_text_file(path)}
        except Exception as exc:
            return {"path": str(path), "name": path.name, "text": None, "error": str(exc)}

    def send_opened_file(self, path: Path) -> None:
        selected = path.expanduser().resolve()
        if not selected.exists() or not selected.is_file():
            raise FileNotFoundError(f"File does not exist: {selected}")
        self.app_server.last_dir = selected.parent
        self.send_json({"ok": True, "canceled": False, "path": str(selected), "name": selected.name, "text": read_text_file(selected)})

    def handle_open_dialog(self) -> None:
        try:
            payload = self.read_json_body()
            print("Opening native file-open dialog...", flush=True)
            selected = ask_dialog("open", payload.get("path") or str(self.app_server.last_dir), backend=self.app_server.dialog_backend)
            if selected is None:
                self.send_json({"ok": True, "canceled": True})
                return
            self.send_opened_file(selected)
            print(f"Opened {selected}", flush=True)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            print(f"Open failed: {exc}", flush=True)

    def handle_open_path(self) -> None:
        try:
            payload = self.read_json_body()
            raw_path = str(payload.get("path") or "").strip()
            if not raw_path:
                self.send_json({"ok": False, "error": "No path was supplied."}, status=400)
                return
            selected = Path(raw_path).expanduser().resolve()
            self.send_opened_file(selected)
            print(f"Opened dropped path {selected}", flush=True)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            print(f"Open dropped path failed: {exc}", flush=True)

    def handle_save(self) -> None:
        try:
            payload = self.read_json_body()
            text = str(payload.get("text") or "")
            suggested_name = normalize_suggested_name(str(payload.get("suggested_name") or "untitled.md"))
            existing_path = str(payload.get("path") or "").strip()
            save_as = bool(payload.get("save_as"))
            current_path_input = Path(existing_path).expanduser() if existing_path else None
            bare_relative_path = bool(current_path_input and not current_path_input.is_absolute() and current_path_input.parent == Path("."))
            if existing_path and not save_as and not bare_relative_path:
                current_path = current_path_input.resolve()
                # The filename field in the HTML UI is authoritative.
                # If the user edits it, plain Save writes beside the current file
                # under the edited name instead of silently reverting to the old path.
                path = current_path.with_name(suggested_name) if suggested_name != current_path.name else current_path
            else:
                # Do not treat a browser-only file.name like "notes.md" as a real path.
                # Resolving such a bare name would write into the editor's working folder.
                print("Opening native file-save dialog...", flush=True)
                dialog_initial = existing_path if existing_path and not bare_relative_path else str(self.app_server.last_dir)
                path = ask_dialog("save", dialog_initial, suggested_name, backend=self.app_server.dialog_backend)
                if path is None:
                    self.send_json({"ok": True, "canceled": True})
                    return
            write_text_file(path, text)
            self.app_server.last_dir = path.parent
            self.send_json({"ok": True, "canceled": False, "path": str(path), "name": path.name})
            print(f"Saved {path}", flush=True)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            print(f"Save failed: {exc}", flush=True)

    def serve_static(self, request_path: str) -> None:
        if request_path in ("", "/"):
            request_path = "/index.html"
        rel = unquote(request_path).lstrip("/")
        target = (self.app_server.public_dir / rel).resolve()
        try:
            target.relative_to(self.app_server.public_dir.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        if target.name == "index.html":
            payload = self.get_startup_payload()
            boot = {
                "token": self.app_server.token,
                "startupPath": payload.get("path") or "",
                "startupName": payload.get("name") or "",
                "startupText": payload.get("text"),
                "build": BUILD_ID,
                "dialogBackend": self.app_server.dialog_backend,
            }
            text = data.decode("utf-8")
            boot_script = 'window.__LOCAL_BACKEND__ = ' + json.dumps(boot, ensure_ascii=False) + ';'
            text, replaced = re.subn(r'window\.__LOCAL_BACKEND__\s*=\s*\{[^\n]*\};', lambda _match: boot_script, text, count=1)
            if not replaced:
                marker = 'window.__LOCAL_BACKEND__ = {"token":"","startupPath":"","startupName":"","startupText":null,"build":"static"};'
                text = text.replace(marker, boot_script)
            data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript", "text/html"} else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)


def find_server(public_dir: Path, startup_path: Path | None, requested_port: int, dialog_backend: str):
    token = secrets.token_urlsafe(24)
    ports = [requested_port] if requested_port else list(range(8765, 8795))
    for port in ports:
        try:
            return LocalEditorServer(("127.0.0.1", port), Handler, public_dir, startup_path, token, dialog_backend), port
        except OSError:
            continue
    raise RuntimeError("Could not bind a local port on 127.0.0.1.")


def main(argv: list[str] | None = None) -> int:
    enable_windows_dpi_awareness()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--_dialog_helper":
        return dialog_helper_main(argv[1] if len(argv) > 1 else "{}")

    parser = argparse.ArgumentParser(description="Run the local GitHub Markdown Editor backend.")
    parser.add_argument("file", nargs="?", help="Optional Markdown file to open at startup.")
    parser.add_argument("--port", type=int, default=8765, help="Preferred local port. Default: 8765.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--dialog-backend", choices=["auto", "tk", "winforms", "native"], default="auto", help="Native dialog mechanism. On Windows auto means WinForms first, then Tk.")
    parser.add_argument("--test-dialog", choices=["open", "save"], help="Show a native dialog and print the selected path, then exit.")
    args = parser.parse_args(argv)

    if args.test_dialog:
        selected = ask_dialog(args.test_dialog, args.file or None, "untitled.md", backend=args.dialog_backend)
        print(selected or "<canceled>")
        return 0

    script_dir = Path(__file__).resolve().parent
    public_dir = script_dir / "public"
    startup_path = Path(args.file).expanduser().resolve() if args.file else None
    server, port = find_server(public_dir, startup_path, args.port, args.dialog_backend)
    url = f"http://127.0.0.1:{port}/?v={BUILD_ID}"
    print(f"Local GitHub Markdown Editor backend {BUILD_ID}")
    print(f"Serving: {url}")
    print(f"Dialog backend: {args.dialog_backend} (Windows auto = WinForms first, then Tk)")
    if startup_path:
        print(f"Startup file: {startup_path}")
    print("Open this URL in the browser. Press Ctrl+C here to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
