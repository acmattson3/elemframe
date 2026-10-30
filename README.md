# ElemFrame

ElemFrame turns a Windows or Linux computer into a touchscreen digital photo and video frame. Import and organize media from USB drives or camera cards, then enjoy a shuffled slideshow with adjustable timing, crossfades, and volume control. It runs entirely offline and prepares older camera formats for playback when needed while preserving the originals.

[Repository](https://github.com/acmattson3/elemframe) · [MIT License](LICENSE)

The application uses a Python FastAPI backend and a vanilla HTML/JavaScript interface, with regular-browser and kiosk launch modes.

## Installers (preview)

Installers are built in `dist/` and bundle the same Python runtime and media decoders as the portable packages. A supported browser must already be installed. These are unsigned preview builds.

- **Windows 10/11 x64:** run `ElemFrame-0.1.0-windows-x86_64-setup.exe`. The per-user wizard offers desktop shortcuts, **Start ElemFrame when I sign in**, fullscreen kiosk mode, and a separate media/settings directory. The default program directory is `%LOCALAPPDATA%/Programs/ElemFrame`; data defaults to `%LOCALAPPDATA%/ElemFrame`. Uninstall through Windows Apps settings or the Start menu entry.
- **Linux x86_64:** run `chmod +x ElemFrame-0.1.0-linux-x86_64-setup.run`, then `./ElemFrame-0.1.0-linux-x86_64-setup.run`. The terminal installer asks about shortcuts, startup, and kiosk mode. It installs for the current user without `sudo`, defaults to `~/.local/lib/elemframe`, and keeps data in `$XDG_DATA_HOME/elemframe` (`~/.local/share/elemframe`). Uninstall through the menu entry or `~/.local/lib/elemframe/ElemFrame --uninstall-linux`.

Installation, upgrade, and uninstall have passed lifecycle checks on the Linux development host and Windows 11 x64. Physical USB/SD insertion, real sign-in startup, interactive kiosk behavior, and Windows 10 still need manual checks.

Both installers preserve media and settings during upgrades and uninstall. Startup is **off unless selected** and runs at user sign-in; automatic OS sign-in is a separate operating-system setting. Neither installer changes OS login credentials or locks down the desktop. Closing a browser leaves the local server running; the Stop shortcut or `--stop` shuts it down gracefully.

Linux unattended installation supports `--yes`, `--startup`/`--no-startup`, `--kiosk`/`--no-kiosk`, `--desktop`/`--no-desktop`, `--install-dir`, and `--data-dir`. Rerunning the installer upgrades the application and updates its shortcuts. Without explicit switches it retains the previous selections.

Windows unattended installation supports Inno Setup's standard `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`, plus `/DIR=...`, `/DATADIR=...`, and `/TASKS=desktopicon,startup,kiosk`. `/TASKS=` deselects optional tasks. Choosing a different data directory does not migrate files from the old location; the old data stays intact.

### Build and test installers

Build the corresponding portable package first, then run:

```bash
python scripts/build_installer.py linux
# On Windows with Inno Setup 6/7 installed:
python scripts/build_installer.py windows --iscc "C:/path/to/ISCC.exe"
```

Installer builders also accept `--package /path/to/extracted/ElemFrame` and `--output /path/to/output`. Outputs have adjacent SHA-256 checksums. Linux builds inherit the portable runtime's glibc compatibility limits.

```bash
python scripts/smoke_installer.py linux dist/ElemFrame-0.1.0-linux-x86_64-setup.run
# On a Windows test account:
python scripts/smoke_installer.py windows dist/ElemFrame-0.1.0-windows-x86_64-setup.exe
```

The Linux test isolates HOME and XDG directories. The Windows test temporarily creates actual per-user shortcuts and uninstall registration, refuses an existing ElemFrame installation, and uninstalls afterward. Both verify installing, upgrading a running application, updating startup/kiosk selections, and uninstalling while preserving disposable media/settings. Run these tests on a test account, not over an installation you depend on.

## Portable ZIP packages (preview)

Build scripts create portable ZIP files in `dist/`. ZIP files and build artifacts are excluded from this source repository; cloning it does not download a prebuilt application. Extract the entire ZIP to a writable folder before running it. They include Python, FFmpeg, and the image/RAW decoders; end users do not need pip or a Python installation. A supported web browser must already be installed.

- **Windows 10/11 x64:** double-click `ElemFrame.exe`. `Start kiosk.cmd` opens kiosk mode. `Stop ElemFrame.cmd` stops the server, and `Check package.cmd` runs decoder checks. The native launcher uses a bundled CPython runtime and Windows x64 wheels. The extracted package has passed native Windows 11 x64 checks; run `Check package.cmd` on your target device before deployment.
- **Linux x86_64:** run `./ElemFrame`, or `./ElemFrame --kiosk`. Run `chmod +x ElemFrame` if the ZIP extraction tool did not preserve executable permissions. `./ElemFrame --stop` stops it; `./ElemFrame --self-test` checks the decoders. The ZIP built on this machine uses its glibc baseline; `build-manifest.json` records that baseline. The CI Linux build targets Ubuntu 22.04 for broader compatibility. It is not a universal binary for every Linux distribution.

The portable marker `portable.txt` keeps settings, media, playback copies, browser profile, and logs under **`data/` beside the launcher**. No personal media/settings from this checkout are shipped. Preserve `data/` during upgrades. `--data-dir /path/to/data` overrides the location. Without the marker (or `--portable`), the launcher defaults to `%LOCALAPPDATA%/ElemFrame` on Windows or `$XDG_DATA_HOME/elemframe` (`~/.local/share/elemframe`) on Linux.

The launcher binds only to localhost, prefers port 8000, falls back to 8081, and waits for its server before opening a browser. It reuses an existing instance for the same data directory. `--no-browser` runs just the server. Installed kiosk preferences are saved in `launch.json`; `--kiosk` or `--no-kiosk` overrides them for an individual launch. Closing the browser leaves the server running until stopped. Kiosk mode uses a dedicated browser profile. Windows supports Edge, Chrome, and Firefox; Linux supports Chromium/Chrome and Firefox. Browser fullscreen does not lock down the OS.

Windows drive discovery includes removable drives and USB-connected fixed disks, excluding the system drive, internal SATA disks, network shares, and optical drives. Linux uses mounted removable locations under `/media` and `/run/media`. Both refresh automatically.

**Validation status:** the Linux package has passed extracted-package runtime, decoder, and Firefox checks on the development machine. The Windows ZIP has passed native Windows 11 x64 checks for the `.exe` launcher, bundled decoders (including a real Canon RAW image and AVCHD), Unicode filenames, settings, instance reuse, and shutdown. The packaged dashboard also rendered successfully in headless Microsoft Edge. Windows drive discovery ran successfully, with no removable device attached. Physical USB/SD insertion/removal, interactive fullscreen kiosk behavior, and Windows 10 remain untested. The cross-platform CI workflow is configured but has not yet been run for this repository.

Portable ZIPs do not register startup or uninstall entries. Use an installer for those features. Automatic OS login and OS lockdown remain separate deployment steps.

### Building and validating packages

```bash
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
python scripts/build_portable.py linux
python scripts/build_portable.py windows
```

Build Linux on Linux with a native FFmpeg installed. Windows ZIP assembly works on either platform: the builder checks the official CPython ZIP checksum and installs only Windows x64 wheels. Its relocatable `.exe` entry point uses the PyPA distlib launcher. Runtime packages retain their license information. The ZIPs include a file-hash/dependency manifest and have adjacent SHA-256 checksum files.

After extracting a ZIP, validate it using:

```bash
python scripts/smoke_portable.py /path/to/extracted/ElemFrame
```

That check launches the **packaged runtime**, exercises settings, USB fixtures, TIFF import/playback, instance reuse, and authenticated shutdown. `.github/workflows/portable-packages.yml` builds and smoke-tests both targets on their native operating systems when manually triggered or on version tags. Windows USB detection still needs a physical-device check on Windows; API mocks do not substitute for that.

## Run from source

Use Python 3.13, the version used for development and package checks. Clone the repository first:

```bash
git clone https://github.com/acmattson3/elemframe.git
cd elemframe
```

### Linux

Ensure removable media auto-mounts, as it does in most Linux desktop environments.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# Recommended on Debian/Ubuntu for camera and camcorder video decoding:
sudo apt install ffmpeg
python server.py
```

### Windows (PowerShell)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py
```

The source setup includes a bundled FFmpeg fallback; a compatible system FFmpeg can also be used. See the portable validation status above for tested Windows behavior and the remaining device/kiosk checks.

Open **http://127.0.0.1:8000** in a browser. For a source checkout, `python launcher.py --kiosk` starts the server and a dedicated kiosk browser together. To run fullscreen manually on Linux with Chromium installed:

```bash
chromium --kiosk --no-first-run http://127.0.0.1:8000
```

`library/` is created automatically and contains all imported files. You can override it using `PICTURE_LIBRARY=/path/to/library`. On Windows, removable and USB-connected fixed drives are discovered using Windows storage APIs. By default, Linux removable media mounted under `/media` and `/run/media` is detected. `PICTURE_REMOVABLE_ROOTS=/path/to/test-usb` treats a specified folder as an inserted drive for testing. This is intended for development, not production.

## Features

- Dashboard: **Manage media**, **Play slideshow**, **Shuffle slideshow** toggle. A visible 30-second countdown starts on each dashboard visit and then starts the slideshow. Manage media cancels this countdown and never starts the slideshow automatically.
- Two independent folder browsers, USB/SD left, local storage right. Drives are detected automatically; unplugging an open drive returns to the drive list.
- Click/tap a file to select it; use **Copy →** to import or **← Copy** to export. Copies leave originals unchanged.
- A drag carries the entire selection; dragging an unselected item adds it to that selection. Drag onto a folder to move the selected media or folders into it, including across panes. Drop on the other pane’s empty area or use Copy to copy instead.
- Each file list begins with Go back, disabled at the Library or Drives root.
- Open folders, create folders, rename and delete files/folders on both sides. Deselect all clears the selection; Delete all deletes the selected items after confirmation. Deletions are permanent.
- Duplicate copies offer Replace, Rename, or Skip for each item. Rename adds the next available number before the extension, such as `photo (1).jpg`.
- Media within library folders are recursively included in the slideshow. Images: JPG/JPEG, PNG, GIF, WebP, BMP, AVIF, TIFF, HEIC/HEIF/HIF, MPO, and camera RAW formats (CR2/CR3/CRW, NEF/NRW, ARW/SR2/SRF, ORF, RW2, RAF, PEF, DNG, RAW, RWL, 3FR, IIQ). Video: MP4, MOV, WebM, M4V, AVI, MPG/MPEG/MPE, MTS/M2TS/M2T, MOD/TOD, VOB, DV, 3GP/3G2, WMV/ASF, MKV, TS, MXF, and FLV. Actual RAW/model and codec support depends on the installed decoders.
- Supported browser formats play directly. Imports that need compatibility work get hidden playback copies in `library/.elemframe-cache/`. Compatible streams are remuxed without re-encoding; other video becomes H.264/AAC MP4, and other photos become JPEG. Original files remain intact and are what gets copied back to removable media. Existing library media is prepared on first playback, with a fallback if the browser cannot decode a directly served file.
- Media names omit extensions in the file lists, slideshow, and rename dialog. Renaming preserves the original extension automatically. Folder names remain unchanged. Playback copies do not appear as extra slideshow entries and are removed when their originals are deleted or replaced.
- Image display time is adjustable from 3–15 seconds, with crossfades from 0–5 seconds, both in half-second steps. Videos start after the crossfade completes and remain on their final frame until the next crossfade. Shuffle uses a refreshing queue: every item plays once per round. Recent-history tracking keeps repeats at least ten selections apart when there are ten or more items; smaller libraries cycle through all available items before repeating.
- The bottom-right speaker opens a vertical volume slider, which collapses after five idle seconds. Playback initially starts muted; volume changes are remembered. Tap outside the volume control to return to the dashboard.

## Settings

For `python server.py` runs, `config.json` in the project directory stores `display_time`, `transition_time`, `shuffle`, and `volume`. UI changes save automatically and survive page reloads and server restarts. The server creates defaults when the file is missing and saves changes using an atomic file replacement. Portable launcher runs use `data/config.json` instead. You can also edit the file directly; reload the page to apply it. `ELEMFRAME_CONFIG=/path/to/config.json` overrides the location.

## Security and limitations

**This is an MVP, not a fully secured public kiosk.** Bind to localhost only. A regular Chromium `--kiosk` window is not a complete OS lockdown; for deployment, configure a restricted OS account, disable escape paths and switch to a dedicated kiosk session such as Cage. Keep untrusted USB devices away from the host until you have assessed that risk.

The backend confines library requests to the library root, restricts removable requests to discovered mountpoints, and rejects basic traversal and symlink escapes. It does not implement per-user authentication, quotas, copy progress, or cancellation. USB unplug during a copy will produce an error and can leave a partial destination. Large imports can take time while copying and preparing playback. Files that cannot be decoded remain stored, with an import error reported. A system FFmpeg is preferred; a virtual-environment FFmpeg executable or the bundled imageio-ffmpeg binary is used otherwise. Children should not remove the drive until **Copied** appears in the footer.

If you want fully offline operation, install dependencies once, then disconnect the network. The running application requires no internet access.

## Repository configuration

[`config.example.json`](config.example.json) contains safe default settings. The application creates a local `config.json` automatically if absent; do not commit your personal configuration.

The [`.gitignore`](.gitignore) excludes:

- Local settings, media, playback caches, and portable application data (`config.json`, `library/`, `data/`).
- Credentials and local tool configuration (`.aws/`, `.codex/`, `.agents/`, `.ssh/`, `.gnupg/`, `.env` files, and private-key files).
- Virtual environments, generated packages, build output, runtime state, logs, and editor configuration.

These exclusions keep local files out of Git without deleting them. Only sanitized examples should be committed when configuration templates are needed. The `config.example.json` template is tracked; `.env.example` is also allowed if one is added later.

## License

ElemFrame is licensed under the [MIT License](LICENSE). Bundled third-party
components retain their respective licenses.
