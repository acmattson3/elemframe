"""Install, upgrade, and remove a real installer using disposable application data.

Linux desktop integration is confined to a temporary HOME. Windows tests use the
current user's shortcuts/registration briefly and refuse an existing installation.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request


def get_json(url, body=None):
    request=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,
                                  headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)


def run(command, env):
    subprocess.run([str(value) for value in command],env=env,check=True,timeout=180)


def windows_folder(number):
    buffer=ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None,number,None,0,buffer):raise RuntimeError('Cannot locate Windows shortcut folder')
    return Path(buffer.value)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('target',choices=['linux','windows']);parser.add_argument('installer',type=Path)
    args=parser.parse_args();installer=args.installer.resolve();windows=args.target=='windows'
    env=os.environ.copy()
    for key in ['ELEMFRAME_HOME','ELEMFRAME_DATA_DIR','ELEMFRAME_CONFIG','PICTURE_LIBRARY','PICTURE_REMOVABLE_ROOTS']:
        env.pop(key,None)
    with tempfile.TemporaryDirectory(prefix='ElemFrame installer check ') as temporary:
        root=Path(temporary);app=root/'program files'/'ElemFrame';data=root/'preserved media';home=root/'home';home.mkdir()
        if windows:
            import winreg
            reg=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{0B839027-2575-4F5B-8BE3-D8A836C6DA53}_is1'
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,reg):pass
                raise RuntimeError('Existing ElemFrame installation detected; test will not replace it.')
            except FileNotFoundError:pass
            desktop=windows_folder(0x10)/'ElemFrame.lnk';startup=windows_folder(7)/'ElemFrame.lnk';menu=windows_folder(2)/'ElemFrame'
            if any(p.exists() for p in [desktop,startup,menu]):raise RuntimeError('Existing ElemFrame shortcuts detected; refusing to overwrite them.')
            def install(first):
                tasks='/TASKS=desktopicon,startup,kiosk' if first else '/TASKS='
                run([installer,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={app}',f'/DATADIR={data}',tasks,f'/LOG={root / ("initial.log" if first else "upgrade.log")}'],env)
            def uninstall():
                log=root/'uninstall.log'
                run([app/'unins000.exe','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/LOG={log}'],env)
                # Inno's uninstaller hands off to a temporary child to remove itself.
                deadline=time.monotonic()+20
                while True:
                    try:
                        if native.exists():raise PermissionError('Uninstaller is still running')
                        if log.exists():log.rename(root/'uninstall-complete.log')
                        break
                    except PermissionError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
            native=app/'ElemFrame.exe'
        else:
            env.update({'HOME':str(home),'XDG_CONFIG_HOME':str(home/'.config'),'XDG_DATA_HOME':str(home/'.local/share')})
            # Avoid consulting the real user's desktop settings in isolated tests.
            tools=root/'test tools';tools.mkdir()
            shim=tools/'xdg-user-dir';shim.write_text('#!/bin/sh\nprintf "%s/Desktop\\n" "$HOME"\n');shim.chmod(0o755)
            env['PATH']=str(tools)+os.pathsep+env.get('PATH','')
            desktop=home/'Desktop/ElemFrame.desktop';startup=home/'.config/autostart/org.elemframe.ElemFrame.desktop';menu=home/'.local/share/applications/org.elemframe.ElemFrame.desktop'
            def install(first):
                run([installer,'--yes','--install-dir',app,'--data-dir',data,
                     '--startup' if first else '--no-startup','--kiosk' if first else '--no-kiosk',
                     '--desktop' if first else '--no-desktop'],env)
            def uninstall():run([native,'--uninstall-linux','--yes'],env)
            native=app/'ElemFrame'
        process=None;installed=False
        try:
            install(True);installed=True
            assert native.is_file() and not (app/'portable.txt').exists()
            preferences=json.loads((app/'launch.json').read_text(encoding='utf-8-sig'))
            assert Path(preferences['data_dir'])==data and preferences['kiosk'] is True
            assert desktop.exists() and startup.exists() and menu.exists()
            print('PASS user-level install, shortcuts, startup opt-in, and kiosk preferences',flush=True)
            with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            # GUI launchers must not inherit the test runner's redirected terminal pipes.
            process=subprocess.Popen([str(native),'--no-browser','--port',str(port)],env=env,
                                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(150):
                if process.poll() is not None:raise RuntimeError('Installed application exited before startup')
                try:health=get_json(url+'/api/health');break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('Installed server did not start')
            assert Path(health['data_dir'])==data
            get_json(url+'/api/config',{'display_time':8.5,'shuffle':True,'volume':.3})
            media=data/'library/keep-this-photo.jpg';media.write_bytes(b'disposable preservation sentinel')
            expected=(data/'config.json').read_bytes()
            install(False)
            assert process.wait(timeout=20)==0;process=None
            assert (data/'config.json').read_bytes()==expected and media.read_bytes()==b'disposable preservation sentinel'
            assert not desktop.exists() and not startup.exists() and menu.exists()
            preferences=json.loads((app/'launch.json').read_text(encoding='utf-8-sig'));assert preferences['kiosk'] is False
            print('PASS upgrade stops running application, preserves data/settings, and removes deselected startup/desktop shortcuts',flush=True)
            uninstall();installed=False
            assert not native.exists() and not desktop.exists() and not startup.exists() and not menu.exists()
            assert (data/'config.json').read_bytes()==expected and media.exists()
            print('PASS uninstall removes program and shortcuts while keeping media and settings',flush=True)
        except Exception:
            if windows:
                for path in [root/'initial.log',root/'upgrade.log',root/'uninstall.log']:
                    if path.exists():print(path.name+' tail:\n'+'\n'.join(path.read_text(encoding='utf-8-sig',errors='replace').splitlines()[-35:]),flush=True)
            raise
        finally:
            if process and process.poll() is None:
                try:run([native,'--stop','--no-browser'],env);process.wait(timeout=20)
                except Exception:process.terminate();process.wait(timeout=10)
            if installed and native.exists():uninstall()


if __name__=='__main__':main()
