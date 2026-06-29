# Local GitHub-Flavoured Markdown Editor

This is a local version of the [GitHub-flavoured Markdown editor](https://github.com/alekrutkowski/GitHub-Flavoured-Markdown-Editor). The browser remains the GUI, but file I/O is delegated to a localhost Python server, so Markdown is read from and saved to real files on disk.

## Requirements

- Python 3.10 or newer.
- Internet access in the browser for rendering libraries loaded from jsDelivr.

No Python packages are required.

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

The frontend talks to these endpoints:

- `GET /api/info`
- `GET /api/list?dir=relative/folder`
- `GET /api/open?path=relative-or-absolute-file`
- `PUT /api/save` with JSON `{ "path": "relative-or-absolute-file", "text": "..." }`
- `POST /api/native-open`
- `POST /api/native-save-as`
- `POST /api/create-folder` with JSON `{ "path": "relative/folder" }`

## Notes

The Markdown rendering libraries are loaded in the browser so preview stays responsive. File reads and writes are not done through the browser sandbox; they happen in the local Python process.
