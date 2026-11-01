# Hardware-free regression checks

Run from the repository root:

```sh
python3 tests/test_features.py
python3 tests/test_fan.py
python3 tests/test_ec_and_led.py
python3 tests/test_hardware_helper.py
python3 tests/test_power_observer.py
```

The fan and EC/LED scripts compile real driver code with fake kernel and EC interfaces. They
require Python 3 and a C compiler; the EC/LED checks also use AddressSanitizer and
UndefinedBehaviorSanitizer. `CC` selects the compiler. No root access, module
loading, or hardware operations are required. Generated source and binaries live
in temporary directories.

`test_ec_and_led.py` exercises malformed/error WMI replies, untouched output on
failure, interrupted locking, read-modify-write bit preservation, Intel AC/DC
profile selection, all raw RGB values 0–50 through brightness changes, apply/off
flags, black handling, power-source changes, notifier refresh, rollback after
ambiguous writes, and probe/unregister without EC writes. It models the current
Linux 7.2 multicolor LED interface, including queued work and power supplies.
Leak detection is disabled by default for compatibility with traced sandboxes.

Mocks cannot verify actual firmware behavior, kernel event scheduling, concurrent
threads, or the physical color and fan speed. Build the kernel module separately
and follow the hardware test instructions in the memory bank.

`test_hardware_helper.py` runs Python unittest cases against temporary files:
restoration after failures, physical-observation prompts, and test preconditions.
It never accesses actual device files.
The helper and power-observer suites run their 80 and 12 cases respectively
for both LAPAC71G and LAPAC71H (160 and 24 cases in total). The EC/LED suite
also runs its complete keyboard checks for both boards. DMI/BIOS detection
tests cover both exact board names, rejected lookalikes, ACADL357 revision
0060, missing/invalid BIOS and capability data, OEM string guards, and the
unchanged original QC71 revision 0114 threshold. These are software checks;
physical testing of this fork has been performed on LAPAC71G only.

The new `keyboard-led` checks model the Intel callback and asynchronous writes:
bright RED, DIMMER RED, OFF, and restoration of configured color/brightness.
They reject the old backend, default/black/rainbow baselines, and prevent saved
AC colors being restored through the active DC API. Standard LED writes are
the only mutations in this test; raw EC paths are diagnostic reads.

`keyboard-led --power-source dc` exercises the separate DC bank with BLUE,
DIMMER BLUE, and OFF, restores its own profile, and checks the inactive AC bank.
Tests cover adapter insertion during DC phases/restoration and verify that
saved DC colors are never written through the active AC interface.
The DC guard also checks other system supplies: AC0 being offline alone does
not imply that the driver's generic power-supply API selected the DC bank.

`fans-suspend` checks cover an owned 90% PWM request followed by a simulated
user-performed sleep: auto mode and cleared boost must be observed before the
final BIOS handoff. They cover unchanged mode without sleep, firmware clearing
the global application bit, hot resume, partial setup failures, source changes,
Ctrl-C/EOF, cleanup failures, and rejection of noninteractive operation. The
helper never invokes a suspend command; real entry/exit evidence is collected
separately from the kernel journal.

Legacy keyboard helper checks still cover the old RGB/CTRL2 raw restoration
path for the first experimental module. All device paths in tests are temporary.

`keyboard-observe` is checked through CLI dispatch: it only reads registers,
requests one native Fn+F7 transition, and reports physical confirmation. Tests
also cover exact-board gating and missing optional observation registers.

Intel AC brightness checks verify the only writes are 0x07ea level4 (0x0c) and
configured level2 with APPLY (0x0a) in finally. They distinguish stored settings
from applied output: writing 0x02 alone must not count as physical restoration.
They cover baseline revalidation, adapter changes, interruptions and errors
after a write. Diagnostics read five known immediate EC bytes using unbuffered
one-byte reads; they never write those addresses.

`test_power_observer.py` covers the separate read-only `tools/observe_power.py`.
It verifies AC -> DC -> AC cache settlement before this script's first brightness
getter at each stage, unchanged raw profiles, timeout/source/profile errors,
rainbow prompts, and identical-color INCONCLUSIVE results. Tests reject writes
and accesses outside temporary fixtures. Other applications can still read the
LED getter during a real observation, so this is evidence of the observed cache
switching, not exclusive attribution to the notifier.
