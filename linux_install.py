"""Per-user Linux installation with separate data and managed desktop entries."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from runtime_control import stop_instance

MARKER = 'X-ElemFrame-Managed=true'


def xdg(name, fallback):
    return Path(os.environ.get(name, str(Path.home() / fallback))).expanduser().resolve()


def quoted_exec(value):
    # Desktop-entry values have both string-value and Exec argument escaping.
    value = str(value).replace('%', '%%')
    for character in ['\\', '"', '`', '$']:
        value = value.replace(character, '\\' + character)
    return '"' + value.replace('\\', '\\\\') + '"'


def desktop_entry(executable, *, uninstall=False, kiosk=False):
    arguments = ' --uninstall-linux' if uninstall else (' --kiosk' if kiosk else '')
    return ('[Desktop Entry]\nType=Application\nVersion=1.0\n'
            + 'Name=' + ('Uninstall ElemFrame' if uninstall else 'ElemFrame') + '\n'
            + 'Comment=' + ('Remove the application; keep media and settings' if uninstall else 'Offline photo and video frame') + '\n'
            + 'Exec=' + quoted_exec(executable) + arguments + '\n'
            + 'Terminal=' + ('true' if uninstall else 'false') + '\n'
            + 'Categories=Graphics;Photography;\n' + MARKER + '\n')


def atomic_text(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(text)
    try:
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def state_for(target):
    path = target / 'install-state.json'
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    if state.get('app') != 'ElemFrame' or state.get('format') != 1 or Path(state['install_dir']) != target:
        raise RuntimeError('This directory is not a managed ElemFrame installation.')
    return state


def prompt(question, default):
    answer = input(question + (' [Y/n] ' if default else ' [y/N] ')).strip().lower()
    return default if not answer else answer in ('y', 'yes')


def install(source, args):
    raw_target = Path(args.install_dir).expanduser() if args.install_dir else Path.home() / '.local/lib/elemframe'
    if raw_target.is_symlink():
        raise RuntimeError('The application directory cannot be a symbolic link.')
    target = raw_target.resolve()
    previous = state_for(target) if target.exists() else None
    if target.exists() and any(target.iterdir()) and not previous:
        raise RuntimeError('The install directory contains unrelated files. Choose an empty directory.')
    data = Path(args.data_dir).expanduser().resolve() if args.data_dir else Path((previous or {}).get('data_dir', xdg('XDG_DATA_HOME', '.local/share') / 'elemframe')).resolve()
    if data == target or data in target.parents or target in data.parents:
        raise RuntimeError('Media/settings and application directories must be separate.')
    options = {}
    for key, default in [('startup', False), ('kiosk', False), ('desktop', True)]:
        value = getattr(args, key)
        if value is None:
            value = (previous or {}).get(key, default)
            if not args.yes:
                value = prompt({'startup':'Start automatically when you sign in?', 'kiosk':'Open in fullscreen kiosk mode?', 'desktop':'Create a desktop shortcut?'}[key], value)
        options[key] = value
    if not args.yes:
        print(f'Application: {target}\nMedia/settings: {data}')
        if not prompt('Install ElemFrame?', True):
            return 0
    if previous:
        stop_instance(Path(previous['data_dir']))
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.elemframe-stage-', dir=target.parent))
    backup = target.with_name('.elemframe-backup-' + uuid.uuid4().hex)
    prior_files = {}
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('portable.txt', 'data', 'launch.json', 'install-state.json', '__pycache__'))
        executable = target / 'ElemFrame'
        (stage / 'ElemFrame').chmod(0o755)
        configuration = xdg('XDG_CONFIG_HOME', '.config')
        shared = xdg('XDG_DATA_HOME', '.local/share')
        entries = {
            shared/'applications/org.elemframe.ElemFrame.desktop': desktop_entry(executable, kiosk=options['kiosk']),
            shared/'applications/org.elemframe.ElemFrame.Uninstall.desktop': desktop_entry(executable, uninstall=True),
        }
        if options['startup']:
            entries[configuration/'autostart/org.elemframe.ElemFrame.desktop'] = desktop_entry(executable, kiosk=options['kiosk'])
        if options['desktop']:
            desktop = Path.home() / 'Desktop'
            utility = shutil.which('xdg-user-dir')
            if utility:
                result = subprocess.run([utility, 'DESKTOP'], capture_output=True, text=True)
                if result.returncode == 0 and result.stdout.strip() and Path(result.stdout.strip()).is_absolute():
                    desktop = Path(result.stdout.strip())
            entries[desktop/'ElemFrame.desktop'] = desktop_entry(executable, kiosk=options['kiosk'])
        old_entries = [Path(path) for path in (previous or {}).get('entries', [])]
        for path in set(entries) | set(old_entries):
            if path.exists():
                text = path.read_text()
                if MARKER not in text:
                    raise RuntimeError(f'Refusing to overwrite an unrelated shortcut: {path}')
                prior_files[path] = (text, path.stat().st_mode & 0o777)
            else:
                prior_files[path] = None
        state = {'app':'ElemFrame', 'format':1, 'install_dir':str(target), 'data_dir':str(data),
                 'entries':[str(path) for path in entries], **options}
        atomic_text(stage/'launch.json', json.dumps({'data_dir':str(data), 'kiosk':options['kiosk']}, indent=2)+'\n')
        atomic_text(stage/'install-state.json', json.dumps(state, indent=2)+'\n')
        if target.exists():
            target.rename(backup)
        stage.rename(target)
        try:
            for path in old_entries:
                if path not in entries:
                    path.unlink(missing_ok=True)
            for path, text in entries.items():
                atomic_text(path, text, 0o755)
        except Exception:
            shutil.rmtree(target)
            if backup.exists():
                backup.rename(target)
            for path, old in prior_files.items():
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_text(path, *old)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        print(f'Installed ElemFrame: {executable}\nMedia and settings: {data}')
        if args.launch or (not args.yes and prompt('Open ElemFrame now?', True)):
            subprocess.Popen([str(executable)], start_new_session=True)
        return 0
    finally:
        if backup.exists() and not target.exists():
            backup.rename(target)
        if stage.exists():
            shutil.rmtree(stage)


def uninstall(home, args):
    target = (Path(args.install_dir).expanduser() if args.install_dir else home).resolve()
    state = state_for(target)
    if not state:
        raise RuntimeError('No managed ElemFrame installation was found here.')
    data = Path(state['data_dir']).resolve()
    if data == target or target in data.parents:
        raise RuntimeError('Refusing uninstall: media directory is inside the application directory.')
    if not args.yes and not prompt(f'Remove ElemFrame from {target}? Media and settings will be kept.', False):
        return 0
    stop_instance(data)
    for name in state['entries']:
        path = Path(name)
        if path.is_file() and MARKER in path.read_text():
            path.unlink()
    shutil.rmtree(target)
    print(f'Uninstalled ElemFrame. Media and settings were kept in {data}.')
    return 0


def main(home, argv):
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        raise RuntimeError('Run this user-level installer as your normal user, without sudo.')
    parser = argparse.ArgumentParser(description='Install/remove ElemFrame for the current Linux user.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--install-linux', action='store_true')
    group.add_argument('--uninstall-linux', action='store_true')
    parser.add_argument('--install-dir')
    parser.add_argument('--data-dir')
    parser.add_argument('--startup', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--kiosk', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--desktop', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--yes', action='store_true', help='Install/uninstall without prompts; startup remains opt-in')
    parser.add_argument('--launch', action='store_true')
    args = parser.parse_args(argv)
    return install(home, args) if args.install_linux else uninstall(home, args)
