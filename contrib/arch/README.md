# Arch Linux packages

## AUR package

`aur/` contains the standalone AUR recipe for
`qc71-laptop-lapac71-dkms-git`. It follows the `master` branch of
<https://github.com/PaveLiArcH/qc71_laptop>, including LAPAC71G/H support,
and retains support for the original LAPQC71 systems.

Build from the published Git sources (requires `base-devel`, `git` and `dkms`):

```sh
cd contrib/arch/aur
makepkg
```

Install the headers matching every kernel for which DKMS should build the
module, for example `linux-headers` or `linux-lts-headers`. Review and install
the resulting package with `pacman -U`; Arch's DKMS hooks build the module.
The package conflicts with `qc71-laptop-dkms-git`, `qc71-laptop-dkms` and
`qc71_laptop`, so only one package supplies this driver. The DKMS module name
remains `qc71_laptop`; its version and `/usr/src` directory match `pkgver`.

The package installs driver sources only. It does not reload the running
module or install module options. Existing `/etc/modprobe.d` settings remain
effective. On LAPAC71G/H, keyboard RGB and direct fan control still require the
explicit `keyboard_backlight=1` and `fan_control=1` module options; enabling
the interfaces leaves fan control with the BIOS. See the main README and
`memory-bank/testing.md` for supported hardware and experimental features.
Physical validation of this fork has been performed on LAPAC71G; LAPAC71H
shares its register protocol and software tests.

For publication, the AUR Git repository needs only `PKGBUILD`, `dkms.conf` and
`.SRCINFO` from `aur/`. Regenerate metadata after changing the recipe:

```sh
cd contrib/arch/aur
makepkg --printsrcinfo > .SRCINFO
```

`pkgver()` updates the version from the published repository during a build.
When refreshing the AUR recipe, build first and then regenerate `.SRCINFO` so
the checked-in version matches. Driver changes must be published to the fork
before they can be consumed by this package.

## Local snapshot and rollback

The separate `PKGBUILD` and `build-local.py` in this directory preserve the
original local snapshot/rollback workflow. They are not the AUR recipe and
must not be uploaded to AUR. The script is tied to the previous installed
baseline and intentionally refuses to run after that baseline changes.
See `memory-bank/install.md` for the existing backup and installed package.
