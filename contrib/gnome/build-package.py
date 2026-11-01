#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build an isolated local Arch package from an exact source snapshot."""
import gzip
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    if os.geteuid() == 0:
        raise RuntimeError('Run makepkg as your normal user')
    destination = Path(tempfile.mkdtemp(prefix='qc71-keyboard-build-'))
    name = 'lapac71g-lapac71h-keyboard-gnome-0.1.0'
    archive = destination / (name + '.tar.gz')
    files = [HERE / item for item in (
        'backend.py', 'service.py', 'Makefile', 'README.md', 'qc71-keyboard.service',
        'io.github.PaveLiArcH.Qc71Keyboard1.service',
        'io.github.PaveLiArcH.Qc71Keyboard1.conf',
        'io.github.PaveLiArcH.qc71-keyboard.policy',
        'extension/metadata.json', 'extension/extension.js',
        'extension/prefs.js', 'extension/shared.js', 'extension/stylesheet.css')]
    with archive.open('wb') as output, gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as bundle:
            for path in [*files, HERE.parents[1] / 'LICENSE']:
                relative = 'LICENSE' if path.name == 'LICENSE' else path.relative_to(HERE).as_posix()
                contents = path.read_bytes()
                entry = tarfile.TarInfo(name + '/' + relative)
                entry.mode, entry.mtime, entry.size = 0o644, 0, len(contents)
                bundle.addfile(entry, io.BytesIO(contents))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    recipe = (HERE / 'PKGBUILD').read_text().replace('@SOURCE_SHA256@', digest)
    (destination / 'PKGBUILD').write_text(recipe)
    environment = os.environ.copy()
    environment.update({key: str(destination) for key in ('PKGDEST', 'SRCDEST', 'SRCPKGDEST', 'LOGDEST')})
    environment.update(BUILDDIR=str(destination / 'build'), PKGEXT='.pkg.tar.zst')
    subprocess.run(['makepkg', '--cleanbuild', '--noconfirm'], cwd=destination,
                   env=environment, check=True)
    print('Package:', *destination.glob('*.pkg.tar.zst'))


if __name__ == '__main__':
    main()
