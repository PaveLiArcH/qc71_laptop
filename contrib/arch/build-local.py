#!/usr/bin/env python3
"""Prepare local DKMS/rollback packages and backups; never install or load them."""
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PACKAGE = 'qc71-laptop-dkms-git'
OLD_VERSION = 'r81.ebab4af'
OLD_SOURCE = Path('/usr/src') / f'qc71_laptop-{OLD_VERSION}'


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def archive(destination, directory_name, files):
    """Create a deterministic, local-only source archive from captured bytes."""
    with destination.open('wb') as output, gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as bundle:
            for name, contents in sorted(files.items()):
                entry = tarfile.TarInfo(f'{directory_name}/{name}')
                entry.mode, entry.mtime = 0o644, 0
                entry.size = len(contents)
                bundle.addfile(entry, io.BytesIO(contents))
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def build_package(directory, version, files, template):
    directory.mkdir()
    source_dir = f'qc71_laptop-{version}'
    digest = archive(directory / f'{source_dir}.tar.gz', source_dir, files)
    recipe = template.replace('@SOURCE_SHA256@', digest)
    recipe = re.sub(r'^pkgver=.*$', f'pkgver={version}', recipe, flags=re.MULTILINE)
    (directory / 'PKGBUILD').write_text(recipe)
    environment = os.environ.copy()
    environment.update({name: str(directory) for name in
                        ('PKGDEST', 'SRCDEST', 'SRCPKGDEST', 'LOGDEST')})
    environment.update(BUILDDIR=str(directory / 'build'), PKGEXT='.pkg.tar.zst',
                       PACKAGER='Local LAPAC71G snapshot <local@localhost.invalid>')
    subprocess.run(['makepkg', '--cleanbuild', '--noconfirm'], cwd=directory,
                   env=environment, check=True)
    packages = list(directory.glob('*.pkg.tar.zst'))
    if len(packages) != 1:
        raise RuntimeError(f'Expected one package in {directory}, found {packages}')
    return packages[0]


def main():
    if os.geteuid() == 0:
        raise RuntimeError('Run as your normal user; this script never uses sudo or installs packages')
    for executable in ('makepkg', 'fakeroot', 'pacman', 'dkms', 'modinfo'):
        if not shutil.which(executable):
            raise RuntimeError(f'Missing build/read tool: {executable}')
    template = (HERE / 'PKGBUILD').read_text()
    version = re.search(r'^pkgver=([A-Za-z0-9._]+)$', template, re.MULTILINE).group(1)
    if command('pacman', '-Q', PACKAGE) != f'{PACKAGE} {OLD_VERSION}-1':
        raise RuntimeError('Installed package changed; review the backup/rollback plan before rebuilding')
    if command('modinfo', '-F', 'srcversion', str(ROOT / 'qc71_laptop.ko')) != \
            Path('/sys/module/qc71_laptop/srcversion').read_text().strip():
        raise RuntimeError('Local .ko differs from the loaded tested module; review/retest first')

    run = HERE / 'out' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = run / 'backup'
    backup.mkdir(parents=True)
    shutil.copytree(OLD_SOURCE, backup / 'old-source')
    installed = Path(command('modinfo', '-n', 'qc71_laptop'))
    shutil.copy2(installed, backup / 'installed-qc71_laptop.ko.zst')
    shutil.copy2(ROOT / 'qc71_laptop.ko.zst', backup / 'user-original-qc71_laptop.ko.zst')
    shutil.copy2(ROOT / 'qc71_laptop.ko', backup / 'tested-qc71_laptop.ko')
    for name, args in {'pacman-info.txt': ('pacman', '-Qi', PACKAGE),
                       'pacman-files.txt': ('pacman', '-Ql', PACKAGE),
                       'dkms-status.txt': ('dkms', 'status'),
                       'installed-module.txt': ('modinfo', str(installed)),
                       'tested-module.txt': ('modinfo', str(ROOT / 'qc71_laptop.ko'))}.items():
        (backup / name).write_text(command(*args) + '\n')
    configuration = [Path('/etc/mkinitcpio.conf')]
    for directory in ('/etc/modprobe.d', '/etc/modules-load.d', '/etc/mkinitcpio.conf.d',
                      '/etc/dkms/framework.conf.d'):
        if Path(directory).is_dir():
            configuration.extend(Path(directory).glob('*.conf'))
    configuration += [Path('/etc/dkms/framework.conf')]
    configuration += list(Path('/etc/dkms').glob('qc71_laptop*.conf'))
    for path in configuration:
        if path.is_file():
            target = backup / 'config' / path.relative_to('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    (backup / 'config-inventory.json').write_text(json.dumps({
        'qc71_modprobe_conf_existed': Path('/etc/modprobe.d/qc71_laptop.conf').exists(),
        'copied_files': sorted(str(path) for path in configuration if path.is_file()),
        'installed_module_path': str(installed),
    }, indent=2) + '\n')

    sources = [path for path in ROOT.glob('*.c') if not path.name.endswith('.mod.c')]
    files = {path.name: path.read_bytes() for path in
             [ROOT / 'Makefile', ROOT / 'LICENSE', *sources, *ROOT.glob('*.h')]}
    # Use the already installed Arch recipe's explicit kernel/build paths.
    # The repository Makefile and its separate 0.0 install targets stay unchanged.
    files['dkms.conf'] = (f'PACKAGE_NAME="qc71_laptop"\nPACKAGE_VERSION="{version}"\n'
        'MAKE[0]="make -C $kernel_source_dir M=$dkms_tree/$PACKAGE_NAME/$PACKAGE_VERSION/build modules"\n'
        'CLEAN="make -C $kernel_source_dir M=$dkms_tree/$PACKAGE_NAME/$PACKAGE_VERSION/build clean"\n'
        'BUILT_MODULE_NAME[0]="qc71_laptop"\n'
        'DEST_MODULE_LOCATION[0]="/kernel/drivers/platform/x86"\nAUTOINSTALL="yes"\n').encode()
    (run / 'source-manifest.json').write_text(json.dumps({
        'package_version': version,
        'source_files_sha256': {name: hashlib.sha256(contents).hexdigest()
                                for name, contents in sorted(files.items())},
        'dkms_conf': files['dkms.conf'].decode(),
        'tested_srcversion': command('modinfo', '-F', 'srcversion', str(ROOT / 'qc71_laptop.ko')),
        'installed_source': str(OLD_SOURCE),
    }, indent=2) + '\n')
    old_files = {str(path.relative_to(backup / 'old-source')): path.read_bytes()
                 for path in (backup / 'old-source').rglob('*') if path.is_file()}
    rollback_package = build_package(run / 'rollback', OLD_VERSION, old_files, template)
    new_package = build_package(run / 'new', version, files, template)
    checksums = []
    for path in sorted(run.rglob('*')):
        if path.is_file() and ('build' not in path.relative_to(run).parts):
            checksums.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(run)}')
    (run / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
    print(json.dumps({'new_package': str(new_package), 'rollback_package': str(rollback_package),
                      'backup': str(backup), 'checksums': str(run / 'SHA256SUMS'),
                      'installed': False}, indent=2))


if __name__ == '__main__':
    main()
