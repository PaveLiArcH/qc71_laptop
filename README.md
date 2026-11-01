# What is it?
This a Linux kernel platform driver for Intel Whitebook LAPQC71X systems (XMG Fusion 15, Eluktronics MAG 15, Aftershock Vapor 15, ...).

Development notes, device evidence, and testing instructions are kept in the
[memory bank](memory-bank/README.md).

This fork also recognizes the Intel NUC X15 **LAPAC71G** (including the
Maibenben P527) and **LAPAC71H** with ACADL357 BIOS 0060 or newer for battery
charge limits. Both models use the same EC register layout. Keyboard RGB and
legacy fan PWM support are experimental and require explicit module options;
see the [hardware test procedure](memory-bank/testing.md). Battery threshold
changes, AC/DC keyboard RGB/brightness/off, automatic switching between the
keyboard profiles, both fan speeds at 100% and 90%, and returning fan control
to BIOS have been physically confirmed on this device. Short s2idle cycles on
AC on LAPAC71G preserved the settings in BIOS mode and released direct fan PWM without
replaying it after resume. Deep sleep and long manual sessions still need
validation. LAPAC71H uses the same implementation and software tests; physical
testing of this fork has so far been performed on LAPAC71G only.
The original QC71 BIOS threshold remains 0114.


# Disclaimer
**This software is in early stages of developement. Futhermore, to quote GPL: everything is provided as is. There is no warranty for the program, to the extent permitted by applicable law.**

**This software is licensed under the GNU General Public License v2.0**


# Compatibility
The upstream driver was tested on an XMG Fusion 15 device (BIOS 0062 up to 0120) and with the `5.4`, and `5.8`-`5.13` kernel series.
Some functions have been confirmed to work on the Tongfang GK7C chassis (XMG Neo 17, PCS Recoil III, Walmart OP17) (see [#6][issue6]).
This checkout has also been tested on the Maibenben P527 / LAPAC71G with
ACADL357 BIOS 0060 and Linux 7.2.9-arch1-1; the confirmed functions and remaining
checks are listed above and in the memory bank.
LAPAC71H is also recognized, using the same ACADL357 BIOS gate and Intel
AC/DC keyboard and fan protocols. Its hardware behavior has not been tested
with this fork.


# Dependencies
### Required
* Your kernel has been compiled with `CONFIG_ACPI` and `CONFIG_DMI` (it probably was)
* Linux headers for you current kernel

### Optional
* DKMS if you don't want to recompile it manually every time the kernel is upgraded


# Features
## Current
* Integrate fan speeds into the Linux hardware monitoring subsystem (so that `lm_sensors` can pick it up)
* Control the lightbar
* Enable/disable always-on mode, reduced fan duty cycle (BIOS 0114 and above)
* Fn lock (BIOS 0114 and above)
* Change battery charge limit (BIOS 0114 and above)


# How to install
For Arch Linux, the AUR recipe for the LAPAC71G/H-capable fork is
[`qc71-laptop-lapac71-dkms-git`](contrib/arch/aur/PKGBUILD).
See the [Arch packaging instructions](contrib/arch/README.md) for building it
from the published Git sources and replacing the upstream DKMS package.

For the current Maibenben P527 Arch installation, use the
[local package and rollback procedure](memory-bank/install.md). Its hardware
checks have passed; the prepared package replaces the existing DKMS package.
The generic `make dkmsinstall` target below uses version 0.0 and would leave
a second source alongside the installed Arch version.

## Downloading
If you have `git` installed:
```
git clone https://github.com/PaveLiArcH/qc71_laptop.git
```

If you don't, then you can download it [here](https://github.com/PaveLiArcH/qc71_laptop/archive/refs/heads/master.zip).

## Installing
### Linux headers
On Debian and its [many][debian-derivatives] [derivatives][ubuntu-derivatives] (Ubuntu, Pop OS, Linux Mint, ...) , run
```
sudo apt install linux-headers-$(uname -r)
```
to install the necessary header files.

On Arch Linux and its derivatives (Manjaro, ...), run
```
sudo pacman -Syu linux-headers
```

### DKMS (optional)
DKMS should be in your distributions repositories. `sudo apt install dkms`, `sudo pacman -Syu dkms` should work depending on your distribution.

### The module
#### Manually
Navigate in a terminal into the directory, then execute `make`. This should compile the module. If everything went correctly, a file named `qc71_laptop.ko` should appear in the directory.

To test the module try `sudo insmod qc71_laptop.ko`. Now you should see the fan speeds appear in the output of `sensors`, and the directory `/sys/devices/platform/qc71_laptop` should now exist. If you are done testing, unload the module using `sudo rmmod qc71_laptop`.

Now you could create a script that inserts this module at boot from this directory, or you could install it using DKMS.

#### With DKMS
Run
```
sudo make dkmsinstall
```
to install the module with DKMS. Or run
```
sudo make dkmsuninstall
```
to uninstall the module.

The module should automatically load at boot after this. If you want to load it immediately, run `sudo modprobe qc71_laptop`. If it reports an error, and you're convinced your device should be supported, please open an [issue][issues].

## Upgrade

If you installed the module with DKMS, and you wish to upgrade, first open the directory of the old sources, and run
```
sudo make dkmsuninstall
```
then update the sources (pull the repository, download the sources again manually, etc.), then run
```
sudo make dkmsinstall
```


# How to use
## LAPAC71G/H keyboard backlight

Load this checkout with `keyboard_backlight=1`; the LED also needs
`CONFIG_LEDS_CLASS_MULTICOLOR` and `CONFIG_POWER_SUPPLY`. The interface is
`/sys/class/leds/qc71_laptop:rgb:kbd_backlight`.

For example, set red at the maximum configured brightness:

```sh
echo '255 0 0' | sudo tee /sys/class/leds/qc71_laptop:rgb:kbd_backlight/multi_intensity
echo 255 | sudo tee /sys/class/leds/qc71_laptop:rgb:kbd_backlight/brightness
```

RGB order is given by `multi_index`. White is `255 255 255`, green is
`0 255 0`, and blue is `0 0 255`. Brightness 0 turns the light off;
64/128/191/255 select its four levels. The values read back describe the
configured AC or DC profile. Native Fn+F7 and the idle timer can change the
physical light independently; wake the built-in keyboard with an ordinary key
when checking the result. AC and DC have separate colors and levels. Wait for
the profile cache to refresh after plugging or unplugging the adapter, then
retry a request if necessary. Changes can be applied asynchronously by the
LED core, so check readback and the visible result.

This interface does not require `manual_control=1`. For bounded tests with
restoration and physical-observation prompts, see the
[hardware procedure](memory-bank/testing.md).

## Fan speeds
After loading the module the fan speeds and temperatures should immediately appear in the output of `sensors`, and all your favourite monitoring utilities (e.g. the [Freon][gnome-ext-freon] GNOME shell extension) that use `sensors`.

## Controlling the lightbar
The lightbar is integrated into the LED subsystem of the linux kernel. When the module is loaded, `/sys/class/leds/qc71_laptop::lightbar` directory should exist with the following important files:
```
/sys/class/leds/qc71_laptop::lightbar/brightness
```

It contains `1` if the lightbar is turned on in S0 sleep state (aka. when the device is powered on), `0` otherwise. You can turn on/off the lightbar by writing an appropriate number into this file:
```
# echo 1 > /sys/class/leds/qc71_laptop::lightbar/brightness
```
will turn the lightbar on. (Writing `0` will turn it off.)
To check the current state:
```
$ cat /sys/class/leds/qc71_laptop::lightbar/brightness
```

___
```
/sys/class/leds/qc71_laptop::lightbar/brightness_s3
```
It contains `1` if the lightbar is turned on in S3 sleep state (aka. when the device is sleeping). If it is `1`, the lightbar will "breathe" when the device is sleeping. You can control it the same way as `brightness`.

___
```
/sys/class/leds/qc71_laptop::lightbar/rainbow_mode
```
It contains `1` if the "rainbow mode" is enabled (aka. the color will continuously cycle). Controlling works the same way as before.

*Note:* Enabling/disabling the rainbow mode will not turn the lightbar on/off.
*Note:* The rainbow mode takes precedence over the color.

___
```
/sys/class/leds/qc71_laptop::lightbar/color
```
This file controls the color of the lightbar. It is a three digit number (possibly with padding zeroes). The first digit is the red component, the second one is the green componenet, the third one is the blue component.
```
$ cat /sys/class/leds/qc71_laptop::lightbar/color
```
tells you the current color, while
```
# echo 591 > /sys/class/leds/qc71_laptop::lightbar/color
```
will change the current color.

*Note:* Chaning the color will not turn the lightbar on.


## Controlling the fans
These can be controlled directly from the BIOS as well.

### Direct PWM on LAPAC71G/H

`fan_control=1` explicitly enables experimental PWM support on this board.
Locate the hwmon directory whose `name` is `qc71_laptop.hwmon.pwm` under
`/sys/devices/platform/qc71_laptop/hwmon/`; its numeric index can change.

First set `/sys/devices/platform/qc71_laptop/manual_control` to 1. In that hwmon
directory, `pwm1_enable=0` runs both fans at full speed; `pwm1_enable=1`
allows separate `pwm1` and `pwm2` values from 0 to 255. Both channels share
`pwm1_enable`; there is no `pwm2_enable`. The device test confirmed both fans
at full speed and about 90%, not the complete speed range.

Set `/sys/devices/platform/qc71_laptop/manual_control` back to 0 to release
direct control and return the global mode to BIOS. Setting only
`pwm1_enable=2` releases direct PWM while keeping the global application mode.
Suspend and unload release direct PWM owned by this driver; resume does not
replay it automatically. Long manual sessions have not been validated.

The bounded `tools/hardware_test.py fans` command tests the two confirmed
speeds and returns control to BIOS; `tools/hardware_test.py bios` explicitly
requests BIOS control without a speed test.

### Passive cooling
I call this feature "always on" because that's less confusing than "passive cooling".
```
# echo 1 > /sys/devices/platform/qc71_laptop/fan_always_on
```
will cause the fans to run continuously. Writing `0` will turn it off.

### Reduced duty cycle
```
# echo 1 > /sys/devices/platform/qc71_laptop/fan_reduced_duty_cycle
```
will cause the fans to run at 25% of their capacity (about 2300 RPM) at idle (instead of 30% - about 2700 RPM). Writing `0` will restore the 30% idle duty cycle.

## Fn lock
```
# echo 1 > /sys/devices/platform/qc71_laptop/fn_lock_switch
```
will enable changing the Fn lock state by pressing Fn+ESC. If this file contains `1`, then pressing Fn+ESC will toggle the Fn lock; if this file contains `0`, then pressing Fn+ESC will have no effect on the Fn lock.

```
# echo 1 > /sys/devices/platform/qc71_laptop/fn_lock
```
will directly enable the Fn lock. If this file contains `1`, then pressing the functions keys will trigger their secondary functions (mute, brightness up, etc.); if this file contains `0`, then pressing the functions keys will trigger their primary functions (F1, F2, ...).

## Battery charge limit
The file `/sys/class/power_supply/BAT0/charge_control_end_threshold` contains the current charge threshold. Writing a number between 1 and 100 will cause the battery charging limit to be set to that percentage. (I did not test extremely low values, so I cannot say if they work). For example:
```
# echo 60 > /sys/class/power_supply/BAT0/charge_control_end_threshold
```
will cause charging to stop when the battery reaches 60% of its capacity.

## Super key (windows key) lock
It is possible to disable the super (windows) key by pressing Fn+F2 (or just F2 if the Fn lock is enabled). This can be also achieved by changing the writing the appropriate value into `/sys/devices/platform/qc71_laptop/super_key_lock`.
```
# echo 1 > /sys/devices/platform/qc71_laptop/super_key_lock
```
disables the super key, while
```
# echo 0 > /sys/devices/platform/qc71_laptop/super_key_lock
```
enables it. Reading the file will provide information about the current state of the super key. `0` means enabled, `1` means disabled.

## Example use

The XMG Control Center can change the color if the device is on battery or plugged in. Fortunately you can easily achieve the same using [acpid](https://wiki.archlinux.org/index.php/Acpid). Modifying the appropriate part of `/etc/acpi/handler.sh` like this:
```
    ac_adapter)
        case "$2" in
            AC|ACAD|ADP0|ACPI0003:00) # the "ACPI0003:00" part was not there by default
                case "$4" in
                    00000000)
                        logger 'AC unplugged'
                        
                        # change color to red
                        echo 900 > /sys/class/leds/qc71_laptop::lightbar/color
                        ;;
                    00000001)
                        logger 'AC plugged'
                        
                        # change color to blue
                        echo 009 > /sys/class/leds/qc71_laptop::lightbar/color
                        ;;
                esac
                ;;
            *)
                logger "ACPI action undefined: $2"
                ;;
        esac
        ;;
```
You can use `acpi_listen` to see what events are generated when you plug the machine in or disconnect the charger. You might need to modify the third line (in this snippet).


# Troubleshooting

* The [TUXEDO Control Center][tcc-github] may interfere with the operation of this kernel module. I do not recommend using both at the same time.


[issue6]: https://github.com/pobrn/qc71_laptop/issues/6
[debian-derivatives]: https://www.debian.org/derivatives/
[ubuntu-derivatives]: https://wiki.ubuntu.com/DerivativeTeam/Derivatives
[issues]: https://github.com/pobrn/qc71_laptop/issues
[gnome-ext-freon]: https://extensions.gnome.org/extension/841/freon/
[tcc-github]: https://github.com/tuxedocomputers/tuxedo-control-center
