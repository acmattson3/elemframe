"""Portable desktop entry point; starts the private server and browser together."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser

from runtime_control import stop_instance

VERSION = '0.1.0'


def application_home():
    if os.environ.get('ELEMFRAME_HOME'):
        return Path(os.environ['ELEMFRAME_HOME']).resolve()
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


def launch_settings():
    path = application_home() / 'launch.json'
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}


def data_directory(args):
    if args.data_dir:
        return Path(args.data_dir).expanduser().resolve()
    if launch_settings().get('data_dir'):
        return Path(launch_settings()['data_dir']).expanduser().resolve()
    if args.portable or (application_home() / 'portable.txt').exists():
        return application_home() / 'data'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'ElemFrame'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'elemframe'


class InstanceLock:
    def __init__(self, directory):
        self.file = open(directory / '.instance.lock', 'a+b')
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)

    def acquire(self):
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def close(self):
        self.file.close()


def request(url, token=None):
    req = urllib.request.Request(url, data=b'' if token else None,
                                 headers={'X-ElemFrame-Token': token} if token else {})
    with urllib.request.urlopen(req, timeout=2) as response:
        return json.load(response)


def browser_command(url, data, kiosk):
    profile = data / 'browser-profile'
    profile.mkdir(exist_ok=True)
    candidates = []
    if sys.platform == 'win32':
        for var in ['PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA']:
            if os.environ.get(var):
                candidates.extend([(Path(os.environ[var]) / 'Microsoft/Edge/Application/msedge.exe', 'chromium'),
                                   (Path(os.environ[var]) / 'Google/Chrome/Application/chrome.exe', 'chromium'),
                                   (Path(os.environ[var]) / 'Mozilla Firefox/firefox.exe', 'firefox')])
    for name, kind in [('msedge', 'chromium'), ('chromium', 'chromium'), ('chromium-browser', 'chromium'),
                       ('google-chrome', 'chromium'), ('firefox', 'firefox'), ('firefox-esr', 'firefox')]:
        found = shutil.which(name)
        if found:
            candidates.append((Path(found), kind))
    for executable, kind in candidates:
        if not executable.is_file():
            continue
        if kind == 'firefox':
            return [str(executable), '--no-remote', '--profile', str(profile), *(['--kiosk'] if kiosk else []), url]
        flags = [f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check']
        if kiosk:
            flags += ['--kiosk']
            if 'msedge' in executable.name.lower():
                flags += ['--edge-kiosk-type=fullscreen']
        else:
            flags += ['--new-window']
        return [str(executable), *flags, url]
    if kiosk:
        raise RuntimeError('Install Firefox, Chrome, or Edge to use kiosk mode.')
    return None


def open_browser(url, data, kiosk):
    command = browser_command(url, data, kiosk)
    environment = os.environ.copy()
    # Frozen applications modify library lookup; system browsers need the original.
    if getattr(sys, 'frozen', False) and sys.platform != 'win32':
        if 'LD_LIBRARY_PATH_ORIG' in environment:
            environment['LD_LIBRARY_PATH'] = environment['LD_LIBRARY_PATH_ORIG']
        else:
            environment.pop('LD_LIBRARY_PATH', None)
    if command:
        if getattr(sys, 'frozen', False) and sys.platform == 'win32':
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            return subprocess.Popen(command, env=environment)
        finally:
            if getattr(sys, 'frozen', False) and sys.platform == 'win32':
                ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
    webbrowser.open(url)
    return None


def native_parent_pid():
    if sys.platform != 'win32':
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    parent = os.getppid()
    handle = kernel.OpenProcess(0x1000, False, parent)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            if Path(buffer.value).resolve() == (application_home() / 'ElemFrame.exe').resolve():
                return parent
    finally:
        kernel.CloseHandle(handle)
    return None


def show_error(message):
    logging.error(message)
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(None, message, 'ElemFrame', 0x10)
    else:
        print(message, file=sys.stderr)


def self_test():
    import rawpy
    import pillow_heif
    from PIL import Image
    import media
    with tempfile.TemporaryDirectory(prefix='elemframe-self-test-') as temporary:
        root = Path(temporary)
        photo = root / 'sample.tiff'
        Image.new('RGB', (64, 48), (20, 100, 150)).save(photo)
        assert media.playback_path(photo, root).is_file()
        video = root / 'sample.mts'
        subprocess.run([media.ffmpeg(), '-nostdin', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=10',
                        '-t', '0.3', '-c:v', 'libx264', '-f', 'mpegts', str(video)], check=True)
        prepared = media.playback_path(video, root)
        assert prepared.suffix == '.mp4' and prepared != video
        print(json.dumps({'app': 'ElemFrame', 'version': VERSION, 'platform': sys.platform,
                          'image': 'ok', 'transport_stream': 'ok', 'raw': rawpy.__version__,
                          'heif': pillow_heif.__version__}), flush=True)


def main():
    if '--install-linux' in sys.argv or '--uninstall-linux' in sys.argv:
        if sys.platform != 'linux':
            raise RuntimeError('Use Windows Apps settings to install or uninstall ElemFrame on Windows.')
        from linux_install import main as install_main
        return install_main(application_home(), sys.argv[1:])
    parser = argparse.ArgumentParser(description='Start ElemFrame and open its local interface.')
    parser.add_argument('--kiosk', action=argparse.BooleanOptionalAction, default=None, help='Open a dedicated fullscreen browser')
    parser.add_argument('--no-browser', action='store_true', help='Run just the local server')
    parser.add_argument('--portable', action='store_true', help='Store settings/media beside the application')
    parser.add_argument('--data-dir', help='Override the writable data directory')
    parser.add_argument('--port', type=int, help='Use a specific localhost port (default: 8000, then 8081)')
    parser.add_argument('--stop', action='store_true', help='Stop the launcher for this data directory')
    parser.add_argument('--self-test', action='store_true', help='Check bundled decoders without modifying user data')
    parser.add_argument('--version', action='version', version=f'ElemFrame {VERSION}')
    args = parser.parse_args()
    if args.kiosk is None:
        args.kiosk = bool(launch_settings().get('kiosk', False))
    if args.self_test:
        self_test()
        return 0
    data = data_directory(args)
    data.mkdir(parents=True, exist_ok=True)
    logs = data / 'logs'
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / 'elemframe.log', maxBytes=2_000_000, backupCount=2)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    state_path = data / '.runtime.json'
    if args.stop:
        stop_instance(data)
        return 0
    lock = InstanceLock(data)
    if not lock.acquire():
        try:
            for _ in range(50):
                try:
                    state = json.loads(state_path.read_text())
                    health = request(state['url'] + '/api/health')
                    if health.get('app') == 'ElemFrame' and Path(health['data_dir']) == data:
                        if not args.no_browser:
                            open_browser(state['url'], data, args.kiosk)
                        return 0
                except (OSError, ValueError):
                    pass
                time.sleep(.1)
            raise RuntimeError('ElemFrame is already starting. Try again shortly.')
        finally:
            lock.close()
    sock = None
    try:
        for port in ([args.port] if args.port is not None else [8000, 8081]):
            if not 1 <= port <= 65535:
                raise RuntimeError('Port must be between 1 and 65535.')
            candidate = socket.socket()
            if os.name == 'nt':
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                candidate.bind(('127.0.0.1', port))
                candidate.listen(128)
                sock = candidate
                break
            except OSError:
                candidate.close()
        if sock is None:
            raise RuntimeError('The requested localhost port is occupied. Close the other application or choose --port.')
        os.environ['ELEMFRAME_DATA_DIR'] = str(data)
        import server
        import uvicorn
        token = secrets.token_hex(32)
        app_server = uvicorn.Server(uvicorn.Config(server.app, log_config=None, access_log=False))
        server.app.state.launcher_token = token
        server.app.state.shutdown = lambda: setattr(app_server, 'should_exit', True)
        url = f'http://127.0.0.1:{sock.getsockname()[1]}'
        state_path.write_text(json.dumps({'url': url, 'token': token, 'pid': os.getpid(), 'launcher_pid': native_parent_pid()}))
        if os.name != 'nt':
            state_path.chmod(0o600)
        def launch_when_ready():
            for _ in range(300):
                if app_server.should_exit:
                    return
                if app_server.started:
                    try:
                        if not args.no_browser:
                            open_browser(url, data, args.kiosk)
                    except Exception as error:
                        show_error(str(error))
                    return
                time.sleep(.1)
        threading.Thread(target=launch_when_ready, daemon=True).start()
        logging.info('Starting ElemFrame at %s; data: %s', url, data)
        print(f'ElemFrame: {url}\nData: {data}', flush=True)
        app_server.run(sockets=[sock])
        return 0
    finally:
        if sock:
            sock.close()
        state_path.unlink(missing_ok=True)
        lock.close()


if __name__ == '__main__':
    # pythonw / Windows GUI bundles may have no stdout/stderr handles.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception('ElemFrame failed')
        if any(flag in sys.argv for flag in ['--self-test', '--no-browser', '--stop', '--install-linux', '--uninstall-linux']):
            print(f'ElemFrame: {error}', file=sys.stderr)
        else:
            show_error(f'ElemFrame could not start: {error}')
        raise SystemExit(1)
