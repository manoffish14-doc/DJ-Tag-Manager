"""Detached helper: swap a verified update after the main app exits."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
import zipfile


def main():
    archive, pid, workspace = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    destination = Path('/Applications/DJ Tag Manager.app')
    if not destination.exists():
        destination = Path.home() / 'Applications/DJ Tag Manager.app'
    if not destination.exists():
        raise RuntimeError('Install DJ Tag Manager in /Applications or ~/Applications first.')
    for _ in range(120):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('App did not exit; update cancelled.')
    extracted = workspace / 'extracted'
    extracted.mkdir()
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            target = (extracted / item.filename).resolve()
            if not target.is_relative_to(extracted.resolve()):
                raise ValueError('Unsafe archive path.')
        z.extractall(extracted)
    incoming = extracted / 'DJ Tag Manager.app'
    if not (incoming / 'Contents/Info.plist').exists():
        raise ValueError('Downloaded archive does not contain the expected Mac application.')
    backup = destination.with_name('DJ Tag Manager.previous.app')
    if backup.exists():
        shutil.rmtree(backup)
    destination.rename(backup)
    try:
        shutil.move(str(incoming), str(destination))
    except Exception:
        backup.rename(destination)
        raise
    subprocess.Popen(['/usr/bin/open', str(destination)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        Path.home().joinpath('Desktop', 'DJ-Tag-Manager-update-error.txt').write_text(str(exc))
        raise
