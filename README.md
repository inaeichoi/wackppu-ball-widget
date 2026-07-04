# Wackppu Ball Widget

Typing-powered desktop widget for Windows. A single Wackppu Ball floats on top of the screen, cracks as you type, and refills itself after it breaks.

## Features

- Always-on-top frameless widget
- Global key press counting without reading typed text
- Gradual visual cracking while typing
- Break animation and refill
- Optional local ASMR MP3 support
- Fallback generated crunch sound when no MP3 is provided

## Download

The GitHub Actions workflow builds a Windows executable.

1. Open the repository's **Actions** tab.
2. Run **Build Windows app** manually, or push a tag like `v0.1.0`.
3. Download `WackppuBallWidget-windows.zip` from the workflow artifact.
4. Unzip it and run `WackppuBallWidget.exe` or `run-widget.bat`.

When a `v*` tag is pushed, the workflow also creates a GitHub Release with the zip attached.

## Run From Source

```powershell
python -m pip install -r requirements.txt
python .\wakppu_widget.py
```

If you are using the Codex bundled Python in this workspace:

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\wakppu_widget.py
```

## Controls

- Drag the ball: move widget
- Right-click: quit menu
- `Ctrl + Shift + Q`: quit

## Optional Custom Sound

The public build does not include third-party MP3 files. To use your own sound locally, place this file next to the executable:

```text
assets/sounds/wakppu-asmr-source.mp3
```

If that file is missing, the app uses its built-in fallback crunch sound.

You can preview sound behavior from source:

```powershell
python .\wakppu_widget.py --sound-test
python .\wakppu_widget.py --sound-scan
```

## Privacy

The widget counts Windows virtual-key press transitions only. It does not read, store, or transmit typed characters.

## Development Checks

```powershell
python -m py_compile .\wakppu_widget.py
python .\wakppu_widget.py --self-test
```
