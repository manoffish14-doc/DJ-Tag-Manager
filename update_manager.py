"""Public GitHub Releases updater for DJ Tag Manager (Apple Silicon)."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import plistlib
import re
import zipfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse
import requests

REPO = 'manoffish14-doc/DJ-Tag-Manager'
VERSION = '3.1.3'
ZIP_NAME = 'DJ-Tag-Manager-Mac.zip'
CHECKSUM_NAME = ZIP_NAME + '.sha256'


def check_release():
    response = requests.get(f'https://api.github.com/repos/{REPO}/releases/latest', timeout=15,
                            headers={'Accept': 'application/vnd.github+json'})
    response.raise_for_status()
    release = response.json()
    assets = {a['name']: a for a in release.get('assets', [])}
    return release, assets


def _download(url, destination):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'):
        raise ValueError('Unexpected download address.')
    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as response:
        response.raise_for_status()
        with open(destination, 'wb') as output:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    output.write(chunk)


def _running_app():
    """Resolve the actual running PyInstaller .app, never a guessed /Applications path."""
    executable = Path(sys.executable).resolve()
    candidates = [p for p in executable.parents if p.suffix == '.app']
    if not candidates:
        raise RuntimeError('Updater only works when running from the packaged Mac application.')
    app = candidates[0]
    if app.name != 'DJ Tag Manager.app':
        raise RuntimeError('Unexpected application name; refusing to replace another app.')
    info = plistlib.loads((app / 'Contents' / 'Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.djtagmanager.app':
        raise RuntimeError('Unexpected application identity; update cancelled.')
    return app


def _install_worker(release, assets, root, status, button):
    try:
        destination = _running_app()  # Validate before any download.
        base = Path(tempfile.mkdtemp(prefix='djtag-update-'))
        archive = base / ZIP_NAME
        checksum = base / CHECKSUM_NAME
        _download(assets[ZIP_NAME]['browser_download_url'], archive)
        _download(assets[CHECKSUM_NAME]['browser_download_url'], checksum)
        expected = checksum.read_text().strip().split()[0].lower()
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if not re.fullmatch(r'[0-9a-f]{64}', expected) or expected != actual:
            raise ValueError('Update checksum verification failed. Nothing was installed.')
        # Validate archive paths before using macOS ditto to preserve bundle symlinks.
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                parts = Path(item.filename).parts
                if item.filename.startswith('/') or '..' in parts:
                    raise ValueError('Unsafe path in update archive.')
        extracted = base / 'extracted'
        extracted.mkdir()
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(extracted)], check=True)
        incoming = extracted / 'DJ Tag Manager.app'
        info = plistlib.loads((incoming / 'Contents' / 'Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != 'com.djtagmanager.app':
            raise ValueError('Downloaded app has an unexpected bundle identifier.')
        helper = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'update_helper.sh'
        if not helper.exists():
            raise FileNotFoundError('Bundled update_helper.sh is missing.')
        backup = destination.with_name('DJ Tag Manager.previous.app')
        pending = destination.with_name('DJ Tag Manager.incoming.app')
        if backup.exists() or pending.exists():
            raise RuntimeError('A previous backup or pending update exists next to the app. Resolve it before updating.')
        log = base / 'install.log'
        subprocess.Popen(['/bin/bash', str(helper), str(destination), str(incoming), str(os.getpid()), str(log)],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        root.after(0, root.destroy)
    except Exception as exc:
        message = str(exc)
        root.after(0, lambda: (status.config(text='Update failed.'), button.config(state='normal'),
                               messagebox.showerror('Update failed', message)))


def show_update_dialog(root):
    dialog = tk.Toplevel(root)
    dialog.title('DJ Tag Manager Updates')
    dialog.geometry('480x190')
    dialog.transient(root)
    status = ttk.Label(dialog, text='Checking GitHub Releases…', wraplength=430)
    status.pack(padx=20, pady=20)
    install = ttk.Button(dialog, text='Install Update', state='disabled')
    install.pack(pady=8)

    def checked():
        try:
            release, assets = check_release()
            tag = release.get('tag_name', '').removeprefix('v')
            def display():
                if release.get('prerelease') or release.get('draft'):
                    status.config(text='Latest release is a draft or prerelease; no update offered.')
                elif tag == VERSION:
                    status.config(text=f'You are running the latest release ({VERSION}).')
                elif not re.fullmatch(r'3\.\d+\.\d+', tag):
                    status.config(text=f'Release {tag or "(unnamed)"} has an unsupported version format.')
                elif tuple(int(x) for x in tag.split('.')) < tuple(int(x) for x in VERSION.split('.')):
                    status.config(text=f'You are running {VERSION}; latest published release is older ({tag}). No update needed.')
                else:
                    if ZIP_NAME not in assets or CHECKSUM_NAME not in assets:
                        status.config(text=f'Release {tag} is missing the Mac update ZIP or checksum.')
                        return
                    status.config(text=f'Current: {VERSION}    Available: {tag}\nInstall will close and restart the app.')
                    install.config(state='normal', command=lambda: (install.config(state='disabled'),
                        status.config(text='Downloading and verifying update…'),
                        threading.Thread(target=_install_worker, args=(release, assets, root, status, install), daemon=True).start()))
            root.after(0, display)
        except Exception as exc:
            error_message = str(exc) or type(exc).__name__
            root.after(0, lambda message=error_message: status.config(text=f'Could not check updates: {message}'))
    threading.Thread(target=checked, daemon=True).start()
