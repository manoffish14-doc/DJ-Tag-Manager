"""Public GitHub Releases updater for DJ Tag Manager (Apple Silicon)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse
from importlib.metadata import version as pkg_version
import requests

REPO = 'manoffish14-doc/DJ-Tag-Manager'
VERSION = '3.0.1'
ZIP_NAME = 'DJ-Tag-Manager-Mac.zip'
CHECKSUM_NAME = ZIP_NAME + '.sha256'


def check_release():
    response = requests.get(f'https://api.github.com/repos/{REPO}/releases/latest', timeout=15,
                            headers={'Accept': 'application/vnd.github+json'})
    response.raise_for_status()
    release = response.json()
    assets = {a['name']: a for a in release.get('assets', [])}
    if ZIP_NAME not in assets or CHECKSUM_NAME not in assets:
        raise ValueError('The latest release does not include the Mac app and its checksum.')
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


def _install_worker(release, assets, root, status, button):
    try:
        base = Path(tempfile.mkdtemp(prefix='djtag-update-'))
        archive = base / ZIP_NAME
        checksum = base / CHECKSUM_NAME
        _download(assets[ZIP_NAME]['browser_download_url'], archive)
        _download(assets[CHECKSUM_NAME]['browser_download_url'], checksum)
        expected = checksum.read_text().strip().split()[0].lower()
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if len(expected) != 64 or expected != actual:
            raise ValueError('Update checksum verification failed. Nothing was installed.')
        helper = Path(__file__).with_name('update_helper.py')
        if not helper.exists():
            raise FileNotFoundError('Update helper is missing from the application.')
        # Copy outside the app bundle so it can run after the app quits.
        helper_copy = base / 'update_helper.py'
        helper_copy.write_bytes(helper.read_bytes())
        script = [sys.executable, str(helper_copy), str(archive), str(os.getpid()), str(base)]
        # A bundled GUI executable is not a Python interpreter; use macOS system Python.
        script[0] = '/usr/bin/python3'
        subprocess.Popen(script, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        root.after(0, root.destroy)
    except Exception as exc:
        root.after(0, lambda: (status.config(text='Update failed.'), button.config(state='normal'),
                               messagebox.showerror('Update failed', str(exc))))


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
            tag = release.get('tag_name', '').lstrip('v')
            def display():
                if release.get('prerelease') or release.get('draft'):
                    status.config(text='Latest release is a draft or prerelease; no update offered.')
                elif tag == VERSION:
                    status.config(text=f'You are running the latest release ({VERSION}).')
                elif not tag.startswith('3.') or tuple(int(x) for x in tag.split('.')) <= tuple(int(x) for x in VERSION.split('.')):
                    status.config(text=f'Latest release {tag} is not a v3 update.')
                else:
                    status.config(text=f'Current: {VERSION}    Available: {tag}\nInstall will close and restart the app.')
                    install.config(state='normal', command=lambda: (install.config(state='disabled'),
                        status.config(text='Downloading and verifying update…'),
                        threading.Thread(target=_install_worker, args=(release, assets, root, status, install), daemon=True).start()))
            root.after(0, display)
        except Exception as exc:
            root.after(0, lambda: status.config(text=f'Could not check updates: {exc}'))
    threading.Thread(target=checked, daemon=True).start()
