"""Build offline ZIP distributions. Windows embedded build can run on Linux."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import io
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'
PYTHON_WINDOWS = '3.13.17'
PYTHON_WINDOWS_SHA256 = '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38'


def run(command, **kwargs):
    subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def common(folder, target):
    (folder / 'portable.txt').write_text('ElemFrame keeps data/ beside this file. Do not delete data/ when upgrading.\n')
    shutil.copy2(ROOT / 'README.md', folder / 'README.md')
    shutil.copy2(ROOT / 'LICENSE', folder / 'LICENSE')
    (folder / 'README-PORTABLE.txt').write_text(f'''ElemFrame {VERSION} — portable {target} preview

Extract the ENTIRE ZIP to a writable folder before starting.
Windows: double-click "ElemFrame.exe". Kiosk: "Start kiosk.cmd".
Linux: run ./ElemFrame (chmod +x ElemFrame if your ZIP tool loses permissions).
Linux kiosk: ./ElemFrame --kiosk

No Python/pip/FFmpeg installation is needed. A browser must already be installed.
Data, settings, playback copies, browser profile, and logs live under data/.
Keep data/ when upgrading; to relocate data use --data-dir /path/to/data.
The launcher uses localhost:8000, or 8081 if 8000 is occupied. It does not use 8080.
A second launch reuses the existing server for that data directory.
Closing the browser leaves the server available. Stop with ./ElemFrame --stop
or "Stop ElemFrame.cmd". Kiosk mode is browser fullscreen, not OS lockdown.
Startup registration and an installer are intentionally deferred to the installer phase.

Diagnostic checks: ./ElemFrame --self-test (Linux), "Check package.cmd" (Windows).
Windows preview needs a Windows 10/11 x64 runtime check; assembling on Linux
cannot validate real Windows USB detection or Windows browser launching.
Linux builds depend on the build host's glibc baseline (see build-manifest.json).
''', encoding='utf-8')


def manifest(folder, target, method):
    versions = {}
    metadata_roots = [folder / 'runtime/site-packages'] if target == 'windows' else []
    for base in metadata_roots:
        for dist in importlib.metadata.distributions(path=[str(base)]):
            versions[dist.metadata['Name']] = dist.version
    result = {'app':'ElemFrame', 'version':VERSION, 'target':target, 'architecture':'x86_64',
              'method':method, 'build_host':platform.platform(),
              'python':PYTHON_WINDOWS if target == 'windows' else platform.python_version(),
              'libc':None if target == 'windows' else platform.libc_ver(),
              'dependencies':versions,
              'files':{str(p.relative_to(folder)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(folder.rglob('*')) if p.is_file()}}
    (folder / 'build-manifest.json').write_text(json.dumps(result, indent=2)+'\n')


def windows(build, folder):
    runtime = folder / 'runtime'
    runtime.mkdir()
    archive = build / f'python-{PYTHON_WINDOWS}-embed-amd64.zip'
    if not archive.exists():
        urllib.request.urlretrieve(f'https://www.python.org/ftp/python/{PYTHON_WINDOWS}/{archive.name}', archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PYTHON_WINDOWS_SHA256:
        raise RuntimeError('Python runtime checksum does not match python.org release metadata')
    with zipfile.ZipFile(archive) as package:
        package.extractall(runtime)
    run([sys.executable,'-m','pip','install','--target',runtime/'site-packages',
         '--platform','win_amd64','--python-version','313','--implementation','cp','--abi','cp313',
         '--only-binary=:all:','--no-compile','-r',ROOT/'requirements.txt','colorama'])
    (runtime / 'python313._pth').write_text('python313.zip\n.\nsite-packages\n../app\nimport site\n')
    app = folder / 'app'
    app.mkdir()
    for name in ['launcher.py','server.py','media.py','removable.py']:
        shutil.copy2(ROOT / name, app / name)
    shutil.copytree(ROOT/'static', app/'static')
    for name, flags, wait in [('Start ElemFrame.cmd','',False),('Start kiosk.cmd','--kiosk',False),
                               ('Stop ElemFrame.cmd','--stop',True),('Check package.cmd','--self-test',True)]:
        command = '"%~dp0runtime\\python.exe"' if wait else 'start "" "%~dp0runtime\\pythonw.exe"'
        text = f'@echo off\nset "ELEMFRAME_HOME=%~dp0"\n{command} "%~dp0app\\launcher.py" {flags} %*\n'
        if wait:
            text += 'pause\n'
        (folder/name).write_bytes(text.replace('\n','\r\n').encode('utf-8'))
    # distlib's native Windows launcher supports interpreter paths relative to itself.
    # Its appended zip runs our entry point with the bundled Python, regardless of CWD.
    import distlib
    launcher_root = Path(distlib.__file__).parent
    bootstrap = """import os, runpy, sys
from pathlib import Path
home = Path(sys.argv[0]).resolve().parent
os.environ['ELEMFRAME_HOME'] = str(home)
runpy.run_path(str(home / 'app' / 'launcher.py'), run_name='__main__')
"""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as package:
        package.writestr('__main__.py', bootstrap)
    (folder / 'ElemFrame.exe').write_bytes((launcher_root / 'w64.exe').read_bytes()
        + b'#!<launcher_dir>\\runtime\\pythonw.exe\n' + payload.getvalue())
    license_dir = folder / 'licenses'
    license_dir.mkdir()
    dist = importlib.metadata.distribution('distlib')
    for file in dist.files or []:
        if 'license' in str(file).lower() and Path(dist.locate_file(file)).is_file():
            shutil.copy2(dist.locate_file(file), license_dir / 'distlib-LICENSE.txt')
    # Validate target payloads, not just archive existence.
    assert (runtime/'python.exe').read_bytes()[:2] == b'MZ'
    for name in ['fastapi','uvicorn','PIL','rawpy','pillow_heif','numpy','pydantic_core']:
        assert (runtime/'site-packages'/name).is_dir(),name
    assert list((runtime/'site-packages/imageio_ffmpeg/binaries').glob('*.exe'))
    assert not list(runtime.rglob('*.so'))
    common(folder,'windows')
    manifest(folder,'windows','embedded CPython + Windows x64 wheels + relocatable distlib native launcher')


def linux(build, folder):
    if sys.platform != 'linux':
        raise RuntimeError('Build the Linux native package on Linux')
    sys.path.insert(0, str(ROOT))
    import media
    ffmpeg = Path(media.ffmpeg())
    # Our development venv may contain a shell wrapper around a Debian executable.
    native = Path(sys.prefix)/'lib/elemframe-ffmpeg/ffmpeg'
    environment = os.environ.copy()
    if native.exists():
        ffmpeg = native
        environment['LD_LIBRARY_PATH'] = str(native.parent) + ':' + environment.get('LD_LIBRARY_PATH','')
    if ffmpeg.read_bytes()[:4] != b'\x7fELF':
        raise RuntimeError('Linux packaging needs a native ELF FFmpeg executable (set up system ffmpeg)')
    output = build/'pyinstaller-dist'
    command = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','ElemFrame',
               '--distpath',output,'--workpath',build/'pyinstaller-work','--specpath',build,
               '--paths',ROOT,'--add-data',str(ROOT/'static')+':static',
               '--add-binary',str(ffmpeg)+':ffmpeg',
               '--collect-all','rawpy','--collect-all','pillow_heif',
               '--collect-submodules','uvicorn','--copy-metadata','imageio-ffmpeg']
    if native.exists():
        for extra in native.parent.glob('*.so*'):
            command += ['--add-binary',str(extra)+':.']
    command += [ROOT/'launcher.py']
    run(command,env=environment,cwd=ROOT)
    shutil.copytree(output/'ElemFrame',folder,dirs_exist_ok=True)
    common(folder,'linux')
    # Preserve installed license information for bundled runtime dependencies.
    license_dir = folder/'licenses'
    license_dir.mkdir()
    for distribution in ['fastapi','starlette','uvicorn','pydantic','pydantic-core','anyio','numpy','pillow','rawpy','pillow-heif','imageio-ffmpeg']:
        dist = importlib.metadata.distribution(distribution)
        for file in dist.files or []:
            if any(word in str(file).lower() for word in ['license','copyright','copying']):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target=license_dir/distribution/file.name
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source,target)
    for source in [Path('/usr/share/doc/libavcodec61/copyright'),Path('/tmp/elemframe-ffmpeg-package/extracted/usr/share/doc/ffmpeg/copyright')]:
        if source.exists():
            shutil.copy2(source,license_dir/'FFmpeg-copyright.txt')
            break
    (license_dir/'FFmpeg-build.txt').write_text(subprocess.run([str(ffmpeg),'-version'],env=environment,capture_output=True,text=True,check=True).stdout + '\nDebian FFmpeg source: https://sources.debian.org/src/ffmpeg/\n')
    manifest(folder,'linux','PyInstaller onedir; native Linux build')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('target',choices=['linux','windows'])
    args=parser.parse_args()
    build=ROOT/'build'/args.target
    build.mkdir(parents=True,exist_ok=True)
    folder=build/'ElemFrame'
    if folder.exists():shutil.rmtree(folder)
    folder.mkdir()
    (linux if args.target=='linux' else windows)(build,folder)
    destination=ROOT/'dist'
    destination.mkdir(exist_ok=True)
    archive=destination/f'ElemFrame-{VERSION}-{args.target}-x86_64.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as package:
        for source in sorted(folder.rglob('*')):
            if source.is_file():package.write(source,source.relative_to(build))
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n')
    print(archive,flush=True)


if __name__=='__main__':main()
