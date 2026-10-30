"""Platform and confinement regression checks; no real drives are modified."""
import ctypes
import importlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import removable


class WindowsDrives(unittest.TestCase):
    def test_removable_and_usb_fixed_only(self):
        kernel = MagicMock()
        kernel.GetLogicalDrives.return_value = sum(1 << (ord(c)-65) for c in 'CDEFGH')
        kernel.GetDriveTypeW.side_effect = lambda root: {'C':2,'D':2,'E':3,'F':3,'G':5,'H':4}[root[0]]
        kernel.CreateFileW.side_effect = lambda name,*args: ord(name[-2])
        def ioctl(handle, code, query, query_size, output, size, returned, overlap):
            self.assertEqual(code, 0x2D1400)
            self.assertEqual(query_size, 12)
            raw = bytearray(36)
            struct.pack_into('<I', raw, 28, 7 if handle == ord('E') else 11)
            ctypes.memmove(output, bytes(raw), len(raw))
            returned._obj.value = len(raw)
            return 1
        kernel.DeviceIoControl.side_effect = ioctl
        def label(root, buffer, *args):
            buffer.value = 'Test card' if root[0]=='D' else 'USB disk'
            return 1
        kernel.GetVolumeInformationW.side_effect = label
        fake_path = MagicMock()
        fake_path.is_dir.return_value = True
        fake_path.resolve.return_value = Path('/tmp/fake-drive')
        with patch.object(ctypes,'WinDLL',return_value=kernel,create=True), patch('removable.Path',return_value=fake_path), patch.dict(os.environ,{'SystemDrive':'C:'}):
            result = removable._windows_drives()
        self.assertEqual([d['path'] for d in result], ['drive-D','drive-E'])
        self.assertEqual(len(result),2)  # System, SATA, optical and network drives excluded.
        self.assertEqual(kernel.CloseHandle.call_count,2)


class FilesystemPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='elemframe-platform-')
        root=Path(cls.temporary.name)
        with patch.dict(os.environ,{'ELEMFRAME_DATA_DIR':str(root),'ELEMFRAME_CONFIG':str(root/'config.json')}):
            import server
            cls.server=importlib.reload(server)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.root=tempfile.TemporaryDirectory(prefix='elemframe-paths-')
        self.base=Path(self.root.name)
        self.library=self.base/'library';self.library.mkdir()
        self.drive=self.base/'usb';self.drive.mkdir()
        self.library_patch=patch.object(self.server,'LIBRARY',self.library)
        self.library_patch.start()
        self.drives_patch=patch.object(self.server,'removable_locations',return_value=[{'name':'USB','path':'drive-E','root':self.drive}])
        self.drives_patch.start()

    def tearDown(self):
        self.library_patch.stop();self.drives_patch.stop();self.root.cleanup()

    def test_windows_selector_and_unplug(self):
        folder=self.drive/'photos';folder.mkdir();(folder/'sample.jpg').write_bytes(b'test')
        self.assertEqual(self.server.resolve('removable','drive-E/photos/sample.jpg'),folder/'sample.jpg')
        with patch.object(self.server,'removable_locations',return_value=[]):
            with self.assertRaises(self.server.HTTPException):self.server.resolve('removable','drive-E/photos/sample.jpg')

    def test_traversal_and_symlink_escape(self):
        for path in ['../secret','drive-E/../secret','C:/Windows','C:Windows','\\\\server\\share','/etc/passwd','a\\..\\secret']:
            with self.subTest(path=path), self.assertRaises(self.server.HTTPException):
                self.server.resolve('local',path,require_exists=False)
        if os.name!='nt':
            (self.library/'escape').symlink_to(self.base,target_is_directory=True)
            with self.assertRaises(self.server.HTTPException):self.server.resolve('local','escape/secret',require_exists=False)

    def test_rename_preserves_extension(self):
        (self.library/'Photo.CR2').write_bytes(b'original')
        self.server.rename(self.server.RenameRequest(side='local',path='Photo.CR2',name='Family.trip',stem_only=True))
        self.assertEqual((self.library/'Family.trip.CR2').read_bytes(),b'original')

    def test_windows_reserved_names(self):
        with patch.object(os,'name','nt'):
            for name in ['CON','nul.txt','COM1.jpg','LPT9','bad:name','bad?name','trailing.','trailing ']:
                with self.subTest(name=name),self.assertRaises(self.server.HTTPException):self.server.validate_name(name)
            self.server.validate_name('Family trip')


if __name__=='__main__':unittest.main()
