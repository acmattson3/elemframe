"""Wrap a validated portable package as a Windows setup or Linux self-extractor."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import VERSION


def checksum(path):
    path.with_suffix(path.suffix+'.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n')


def build_linux(package, output):
    work=ROOT/'build/installers/linux'
    work.mkdir(parents=True,exist_ok=True)
    payload=work/'payload.tar.gz'
    with tarfile.open(payload,'w:gz',dereference=True) as archive:
        archive.add(package,arcname='ElemFrame',filter=lambda info: None if info.name.startswith('ElemFrame/data/') or info.name=='ElemFrame/data' else info)
    digest=hashlib.sha256(payload.read_bytes()).hexdigest()
    header='''#!/bin/sh
set -eu
if [ "$(uname -m)" != "x86_64" ]; then
  echo "This installer requires Linux x86_64." >&2; exit 1
fi
if [ "$(id -u)" = "0" ]; then
  echo "Run this user-level installer without sudo." >&2; exit 1
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/elemframe-setup.XXXXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM
line=$(awk '/^__ELEMFRAME_ARCHIVE_BELOW__$/ {print NR + 1; exit}' "$0")
tail -n +"$line" "$0" > "$work/payload.tar.gz"
actual=$(sha256sum "$work/payload.tar.gz" | cut -d ' ' -f 1)
if [ "$actual" != "PAYLOAD_HASH" ]; then
  echo "Installer payload checksum failed." >&2; exit 1
fi
tar -xzf "$work/payload.tar.gz" --no-same-owner -C "$work"
chmod u+x "$work/ElemFrame/ElemFrame"
"$work/ElemFrame/ElemFrame" --install-linux "$@"
exit $?
__ELEMFRAME_ARCHIVE_BELOW__
'''.replace('PAYLOAD_HASH',digest)
    target=output/f'ElemFrame-{VERSION}-linux-x86_64-setup.run'
    with target.open('wb') as result:
        result.write(header.encode())
        with payload.open('rb') as data:shutil.copyfileobj(data,result)
    target.chmod(0o755)
    checksum(target)
    return target


def build_windows(package, output, iscc):
    if sys.platform!='win32':
        raise RuntimeError('Compile the Windows installer on Windows using Inno Setup ISCC.exe.')
    compiler=iscc or shutil.which('ISCC.exe')
    if not compiler:
        for base in [os.environ.get('PROGRAMFILES(X86)'),os.environ.get('PROGRAMFILES'),os.environ.get('LOCALAPPDATA')]:
            if not base:continue
            for suffix in ['Inno Setup 7/ISCC.exe','Inno Setup 6/ISCC.exe','Programs/Inno Setup 7/ISCC.exe','Programs/Inno Setup 6/ISCC.exe']:
                candidate=Path(base)/suffix
                if candidate.exists():compiler=str(candidate);break
            if compiler:break
    if not compiler:raise RuntimeError('Install Inno Setup or supply --iscc /path/to/ISCC.exe.')
    subprocess.run([str(compiler),'/Qp',f'/DSourceDir={package}',f'/DOutputDir={output}',
                    f'/DAppVersion={VERSION}',f'/DLicensePath={ROOT / "LICENSE"}',
                    str(ROOT/'installers/ElemFrame.iss')],check=True)
    target=output/f'ElemFrame-{VERSION}-windows-x86_64-setup.exe'
    checksum(target)
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('target',choices=['linux','windows'])
    parser.add_argument('--package',type=Path);parser.add_argument('--output',type=Path,default=ROOT/'dist')
    parser.add_argument('--iscc');args=parser.parse_args()
    package=(args.package or ROOT/'build'/args.target/'ElemFrame').resolve()
    if not package.is_dir():raise SystemExit('Build or extract the portable package first.')
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    print(build_linux(package,args.output) if args.target=='linux' else build_windows(package,args.output,args.iscc),flush=True)
