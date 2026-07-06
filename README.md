# Local GitHub-Flavoured Markdown Editor

This is a local version of the [GitHub-flavoured Markdown editor](https://github.com/alekrutkowski/GitHub-Flavoured-Markdown-Editor). The browser remains the GUI, but file I/O is delegated to a localhost Python server, so Markdown is read from and saved to real files on disk.

## Requirements

- Python 3.10 or newer.
- Internet access in the browser for rendering libraries loaded from jsDelivr.

No Python packages are required. On Windows, the automatic dialog backend prefers Windows Forms and enables DPI awareness before falling back to Tk.

## Download

https://github.com/alekrutkowski/GitHub-Flavoured-Markdown-Editor-Local/archive/refs/heads/main.zip

## Run on Linux

```bash
python3 local_gfm_editor.py
```

Use a custom port:

```bash
python3 local_gfm_editor.py --port 9876
```

## Run on Windows

In PowerShell:

```powershell
python local_gfm_editor.py
```

## API summary

The frontend talks to these local endpoints:

- `GET /api/info`
- `POST /api/open` with JSON `{ "path": "optional-current-file" }` – shows the native Open dialog and returns the selected file text, name, and absolute path.
- `POST /api/open-path` with JSON `{ "path": "absolute-file" }` – reopens a known dropped/remembered path when the browser/OS exposes one.
- `POST /api/save` with JSON `{ "path": "absolute-or-directed-relative-file", "suggested_name": "file.md", "text": "...", "save_as": false }` – writes to the remembered path, or shows Save As when no safe path is known.

## Notes

The Markdown rendering libraries are loaded in the browser so preview stays responsive. File reads and writes are not done through the browser sandbox; they happen in the local Python process.

The editor remembers the absolute path returned by native Open, native Save As, startup-file loading, and `/api/open-path`. Plain Save reuses that path. For drag/drop, Chromium-family browsers can provide a writable browser file handle; when that happens, plain Save writes back to the dropped file without opening Save As. Browser-only drag/drop is still supported as an import path; when the browser provides neither a usable absolute path nor a writable file handle, Save asks for a real destination instead of writing a bare filename beside `local_gfm_editor.py`.
