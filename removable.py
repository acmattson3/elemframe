"""Discover mounted camera cards/USB drives without exposing internal disks."""
from __future__ import annotations

import ctypes
import os
import string
import struct
import sys
from pathlib import Path


def _windows_drives():
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetLogicalDrives.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    kernel.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                           wintypes.LPWSTR, wintypes.DWORD]
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mask = kernel.GetLogicalDrives()
    system_drive = os.environ.get('SystemDrive', 'C:').upper()
    result = []
    for index, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << index) or letter + ':' == system_drive:
            continue
        root = letter + ':\\'
        kind = kernel.GetDriveTypeW(root)
        usb = False
        if kind == 3:  # USB hard disks can report fixed rather than removable media.
            handle = kernel.CreateFileW('\\\\.\\' + letter + ':', 0, 3, None, 3, 0, None)
            if handle not in (None, ctypes.c_void_p(-1).value):
                try:
                    query = ctypes.create_string_buffer(struct.pack('<III', 0, 0, 0))
                    descriptor = ctypes.create_string_buffer(4096)
                    returned = wintypes.DWORD()
                    ok = kernel.DeviceIoControl(handle, 0x2D1400, query, 12, descriptor,
                                                 len(descriptor), ctypes.byref(returned), None)
                    usb = bool(ok and returned.value >= 32 and struct.unpack_from('<I', descriptor.raw, 28)[0] == 7)
                finally:
                    kernel.CloseHandle(handle)
        if kind != 2 and not usb:
            continue
        label = ctypes.create_unicode_buffer(261)
        if not kernel.GetVolumeInformationW(root, label, len(label), None, None, None, None, 0):
            continue  # Empty card-reader slot or disconnected drive.
        if Path(root).is_dir():
            result.append({'name': f'{label.value or "USB / SD"} ({letter}:)',
                           'path': f'drive-{letter}', 'root': Path(root).resolve()})
    return result


def locations(roots=None):
    """Selectors are opaque, stable during a mount, and always use forward slashes."""
    custom = os.environ.get('PICTURE_REMOVABLE_ROOTS')
    if custom:
        roots = [Path(value).expanduser().resolve() for value in custom.split(',') if value]
        return [{'name': root.name, 'path': str(i), 'root': root}
                for i, root in enumerate(roots) if root.is_dir()]
    if sys.platform == 'win32':
        return _windows_drives()
    roots = roots if roots is not None else [Path('/media'), Path('/run/media')]
    result = []
    for i, root in enumerate(roots):
        if not root.is_dir():
            continue
        try:
            for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                if not entry.is_dir() or entry.is_symlink():
                    continue
                if entry.is_mount():
                    result.append({'name': entry.name, 'path': f'{i}/{entry.name}', 'root': entry.resolve()})
                else:
                    for child in sorted(entry.iterdir(), key=lambda p: p.name.lower()):
                        if child.is_dir() and not child.is_symlink() and child.is_mount():
                            result.append({'name': child.name, 'path': f'{i}/{entry.name}/{child.name}', 'root': child.resolve()})
        except OSError:
            continue
    return result
