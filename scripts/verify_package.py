"""Check release checksums, contents, and per-file manifests without executing them."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile


def verify(path):
    expected=path.with_suffix('.zip.sha256').read_text().split()[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest()==expected,'ZIP checksum mismatch'
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None,'ZIP corruption'
        names=set(archive.namelist())
        assert not any(n.startswith(('ElemFrame/data/','ElemFrame/library/')) for n in names),'Personal data bundled'
        assert 'ElemFrame/config.json' not in names,'Personal configuration bundled'
        manifest=json.loads(archive.read('ElemFrame/build-manifest.json'))
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(archive.read('ElemFrame/'+name)).hexdigest()==digest,name
        assert names=={'ElemFrame/'+name for name in manifest['files']}|{'ElemFrame/build-manifest.json'},'Unmanifested files'
        if manifest['target']=='windows':
            for name in ['ElemFrame/ElemFrame.exe','ElemFrame/runtime/python.exe','ElemFrame/runtime/pythonw.exe']:
                data=archive.read(name)
                assert data[:2]==b'MZ'
                pe_offset=struct.unpack_from('<I',data,0x3c)[0]
                assert data[pe_offset:pe_offset+4]==b'PE\0\0'
                assert struct.unpack_from('<H',data,pe_offset+4)[0]==0x8664,'Not Windows x64'
            assert b'../app' in archive.read('ElemFrame/runtime/python313._pth')
            assert not any(n.endswith('.so') for n in names),'Linux binary in Windows ZIP'
        else:
            assert archive.read('ElemFrame/ElemFrame')[:4]==b'\x7fELF'
    print(f'PASS archive, checksums, manifest, architecture, and data exclusions: {path}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('path',type=Path,nargs='?',default=Path('dist'));args=parser.parse_args()
    for path in sorted(args.path.glob('*.zip')) if args.path.is_dir() else [args.path]:verify(path)
