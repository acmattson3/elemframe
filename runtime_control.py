"""Graceful, authenticated shutdown shared by the launcher and installers."""
import json
import os
import ctypes
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


def stop_instance(data: Path, timeout=20):
    state_path = data / '.runtime.json'
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text(encoding='utf-8'))
    url = state['url']
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port:
        raise RuntimeError('Invalid local runtime address; close ElemFrame manually.')
    try:
        with urllib.request.urlopen(url + '/api/health', timeout=3) as response:
            health = json.load(response)
    except urllib.error.URLError as error:
        # Refused connection means a stale record, not permission to kill a PID.
        code = getattr(error.reason, 'errno', None)
        if code in (61, 111, 10061) or getattr(error.reason, 'winerror', None) == 10061:
            state_path.unlink(missing_ok=True)
            return
        raise RuntimeError('ElemFrame is busy; wait for file operations to finish and retry.') from error
    if health.get('app') != 'ElemFrame' or Path(health['data_dir']).resolve() != data.resolve():
        raise RuntimeError('Runtime belongs to another application or data folder.')
    handles = []
    kernel = None
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        for pid in {state.get('pid'), state.get('launcher_pid')} - {None, os.getpid()}:
            handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE only; never terminate.
            if handle:
                handles.append(handle)
    try:
        req = urllib.request.Request(url + '/api/shutdown', data=b'{}',
                                     headers={'X-ElemFrame-Token': state['token'], 'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=3):
            pass
        deadline = time.monotonic() + timeout
        while state_path.exists() or any(kernel.WaitForSingleObject(handle, 0) == 258 for handle in handles):
            if time.monotonic() >= deadline:
                raise RuntimeError('ElemFrame is still closing; wait and retry.')
            time.sleep(.1)
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
