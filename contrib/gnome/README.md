# LAPAC71G / LAPAC71H Keyboard Color for GNOME 51

An optional GNOME Shell extension for the single-zone RGB keyboard exposed by
`qc71_laptop` on LAPAC71G/H. Quick Settings offers nine colors; **Custom color…**
opens a GTK4/libadwaita palette and a `#RRGGBB` field. Russian and English labels
follow the session language. Colors are applied explicitly, never on enable,
login, resume or opening preferences. Brightness stays in GNOME's existing control.

The kernel module must already expose
`/sys/class/leds/qc71_laptop:rgb:kbd_backlight` with protocol `intel-ac-dc-v1`
and `keyboard_backlight=1`. This UI requires no kernel changes or module reload.

## Install on Arch

The AUR package is
[`lapac71g-lapac71h-keyboard-gnome-git`](https://aur.archlinux.org/packages/lapac71g-lapac71h-keyboard-gnome-git).
It builds the extension and D-Bus bridge from this repository. Install the
LAPAC71G/H-capable `qc71-laptop-lapac71-dkms-git` driver separately and enable
its `keyboard_backlight=1` module option. The UI does not install module options.

Build the AUR recipe as a normal user:

```sh
git clone https://aur.archlinux.org/lapac71g-lapac71h-keyboard-gnome-git.git
cd lapac71g-lapac71h-keyboard-gnome-git
makepkg -si
```

For a local snapshot instead, run from `contrib/gnome`:

```sh
python3 build-package.py
```

The command prints the exact package path in `/tmp/qc71-keyboard-build-…/`.
Install that file with `sudo pacman -U /tmp/…/lapac71g-lapac71h-keyboard-gnome-0.1.0-1-any.pkg.tar.zst`.
The package contains the system-wide extension, a system D-Bus activation file,
the service unit, a bus policy and a polkit action. It does not enable a boot daemon.
The bridge starts on the first UI request and does not write anything on startup.

Newly installed extensions require **logging out and back in on Wayland** for
GNOME to discover them. Then enable **LAPAC71G / LAPAC71H Keyboard Color** in Extensions, or:

```sh
gnome-extensions enable qc71-keyboard@paveliarch.github.io
gnome-extensions prefs qc71-keyboard@paveliarch.github.io
```

The **Keyboard color** tile appears in Quick Settings. Open it and choose a
color, or open **Custom color…**, choose a palette color/enter HEX, then press
**Apply color**. An ordinary built-in keyboard key wakes firmware idle lighting.
The existing GNOME brightness menu can turn the light on if its level is zero.

For distributions without pacman, review and use `sudo make install`, then
`sudo systemctl daemon-reload` and reload the system bus configuration. Paths
are intended for `/usr`; the Makefile's `DESTDIR` supports package staging.
Dependencies: Python 3 with PyGObject, polkit, GTK >=4.10, libadwaita >=1.5,
GNOME Shell 51, systemd. Other Shell versions have not been validated.

## D-Bus and permissions

Service/interface: `io.github.PaveLiArcH.Qc71Keyboard1`, object:
`/io/github/PaveLiArcH/Qc71Keyboard1` on the **system bus**.

* `GetState() → (u red, u green, u blue, u brightness, s source)` is read-only.
* `SetColor(u red, u green, u blue, s expected_source) → same state` accepts
  components 0..255 and source `ac` or `dc`. It writes only the fixed LED's
  `multi_intensity` file, using `multi_index` order. It validates the qc71
  protocol, requires a stable power source and checks bounded stable readback.
* Each write uses polkit `CheckAuthorization` with the **actual system bus
  sender**, not a client-supplied UID/PID. The supplied action permits active
  local sessions without a password; inactive/remote sessions are denied.
  Files remain root-owned; no global sysfs write permission or user group is added.
* Calls run on one worker, with no unbounded queue or synchronous Shell I/O.
  Disabling the extension cancels pending UI callbacks and destroys its actors.

AC and battery store separate firmware profiles. Refresh the menu/preferences
after plugging/unplugging. A request from an older source is rejected; a source
change during apply is reported without replaying or restoring another bank.
The sysfs ABI cannot atomically bind a request to a power source, so a switch
at the exact write boundary can still race; check the active profile and select
again. The kernel's own source guards remain effective.

Firmware quantizes channels to 0..50. Near-black `(0..2, 0..2, 0..2)` is rejected
because this driver's black handling turns the light off rather than storing
black; use GNOME brightness for OFF. A new color selects static lighting, subject
to the driver's existing semantics for an unchanged RGB value. Only configured
state is reported: stable sysfs readback does not prove the visible color.
No raw EC, `manual_control`, fan, battery-limit or brightness writes are made.

## Checks and troubleshooting

```sh
make check
dbus-run-session -- python3 ../../tests/test_gnome_dbus.py
systemctl status qc71-keyboard.service
journalctl -u qc71-keyboard.service -b
gdbus call --system --dest io.github.PaveLiArcH.Qc71Keyboard1 \
  --object-path /io/github/PaveLiArcH/Qc71Keyboard1 \
  --method io.github.PaveLiArcH.Qc71Keyboard1.GetState
gnome-extensions info qc71-keyboard@paveliarch.github.io
```

Tests use temporary files and mocked authorization; they never write hardware.
If the driver was absent when systemd started the bridge, load the driver and
restart `qc71-keyboard.service` so systemd can mount its single writable sysfs
exception. After upgrading the bridge, restart this service and log in again
to load updated Shell JavaScript. The GUI itself does not unload/reload drivers.

To remove: disable the extension, `sudo systemctl stop qc71-keyboard.service`,
then `sudo pacman -R lapac71g-lapac71h-keyboard-gnome-git` (or the snapshot
package name without `-git`). A manual installation can instead use
`sudo make uninstall`, daemon-reload and reload the system bus configuration.
Stored keyboard colors are retained.

The package replaces the earlier local `qc71-keyboard-gnome` package. The
extension UUID, D-Bus name and service paths are retained so existing enabled
state and settings continue working. The AUR recipe is in `aur/`; regenerate
its `.SRCINFO` with `makepkg --printsrcinfo` after updating it. Only `PKGBUILD`
and `.SRCINFO` are needed in the AUR Git repository.

Color selection has been physically confirmed by the user on LAPAC71G with
GNOME 51. LAPAC71H shares the driver protocol but has not been physically tested.

## Existing projects checked

* [Tuxedo Backlight Keyboard](https://extensions.gnome.org/extension/3121/tuxedo-backlight-keyboard/)
  targets GNOME 3.36 and the old `/sys/devices/platform/tuxedo_keyboard/color_*` API.
* [RoGB](https://github.com/Tejaromalius/RoGB) uses ASUS `asusctl`.
* [Customization Keyboard Backlight](https://extensions.gnome.org/extension/8779/keyboard-accent-color-sync/)
  uses OpenRGB; the published version lists GNOME 46–49.
* [Lamplight](https://extensions.gnome.org/extension/11264/lamplight/) supports
  GNOME 51 but uses HID LampArray, not the qc71 LED API.
* [KeyRGB](https://github.com/Rainexn0b/keyRGB) is a separate application with a
  generic sysfs backend, worth considering when Shell integration is unnecessary.

No ready-made extension supporting both qc71's multicolor LED and GNOME 51 was
found in this search (2026-11-01). GNOME's standard
[UPower keyboard interface](https://upower.freedesktop.org/docs/KbdBacklight.html)
only offers brightness. The extension uses the documented
[Quick Settings API](https://gjs.guide/extensions/topics/quick-settings.html).
