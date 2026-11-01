#!/usr/bin/env python3
"""Exercise real DMI/BIOS/capability detection without accessing hardware."""
import os
from pathlib import Path
import re
import shlex
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def without_includes(name):
    return re.sub(r'^#include[^\n]*\n', '', (ROOT / name).read_text(), flags=re.MULTILINE)


STUBS = r'''
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define __init
#define __initconst
#define __pure
#define __must_check
#define BIT(n) (1U << (n))
#define GENMASK(h,l) (((~0U) << (l)) & ((~0U) >> (31 - (h))))
#define GFP_KERNEL 0
#define pr_warn(...) ((void)0)
#define pr_info(...) ((void)0)
#define strlen(s) __builtin_strlen((const char *)(s))
#define kstrdup(s,f) strdup((const char *)(s))
#define kfree(p) free((void *)(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p) || IS_ERR(p))
#define str_has_prefix(s,p) (strncmp((s), (p), strlen(p)) == 0)
enum { DMI_BOARD_NAME = 1, DMI_CHASSIS_VENDOR, DMI_PRODUCT_NAME, DMI_BIOS_VERSION };
struct dmi_strmatch { int slot; const char *text; bool exact; };
struct dmi_system_id { struct dmi_strmatch matches[4]; };
struct dmi_header { uint8_t type, length; uint16_t handle; };
#define DMI_MATCH(f,v) { .slot = (f), .text = (v) }
#define DMI_EXACT_MATCH(f,v) { .slot = (f), .text = (v), .exact = true }
static const char *board = "LAPAC71G", *bios = "ACADL357.0060.2024.0101.0000";
static const char *oem = "                ";
static const char *dmi_get_system_info(int field) {
    if (field == DMI_BOARD_NAME) return board;
    if (field == DMI_BIOS_VERSION) return bios;
    return "other";
}
static bool dmi_match(int field, const char *value) {
    const char *actual = dmi_get_system_info(field);
    return actual && strcmp(actual, value) == 0;
}
static bool dmi_check_system(const struct dmi_system_id *table) {
    for (; table->matches[0].slot; table++) {
        bool match = true;
        for (int i = 0; i < 4 && table->matches[i].slot; i++) {
            const struct dmi_strmatch *m = &table->matches[i];
            const char *actual = dmi_get_system_info(m->slot);
            if (!actual || (m->exact ? strcmp(actual, m->text) != 0 : !strstr(actual, m->text)))
                match = false;
        }
        if (match) return true;
    }
    return false;
}
static int dmi_walk(void (*callback)(const struct dmi_header *, void *), void *data) {
    _Alignas(struct dmi_header) uint8_t bytes[256] = {11, 5, 0, 0, 19};
    char *next = (char *)bytes + 5;
    for (int i = 0; i < 18; i++) { *next++ = 'x'; *next++ = 0; }
    strcpy(next, oem);
    callback((const struct dmi_header *)bytes, data);
    return 0;
}
static int support1, support2;
'''

TESTS = r'''
int qc71_ec_transaction(uint16_t addr, uint16_t data, union qc71_ec_result *r, bool read) {
    assert(read);
    int value;
    if (addr == SUPPORT_1_ADDR) value = support1;
    else { assert(addr == SUPPORT_2_ADDR); value = support2; }
    if (value < 0) return value;
    r->dword = value;
    return 0;
}
static void reset(void) {
    memset(&qc71_features, 0, sizeof(qc71_features));
    support1 = 0;
    support2 = SUPPORT_2_SINGLE_ZONE_KBD;
    oem = "                ";
}
int main(void) {
    const char *boards[] = { "LAPAC71G", "LAPAC71H" };
    for (size_t i = 0; i < sizeof(boards)/sizeof(boards[0]); i++) {
        board = boards[i];
        assert(qc71_is_lapac71());
        reset(); bios = "ACADL357.0060.2024.0101.0000";
        assert(qc71_check_features() == 0);
        assert(qc71_features.keyboard_backlight && qc71_features.batt_charge_limit);
        assert(qc71_features.fn_lock && qc71_features.fan_extras && !qc71_features.fan_boost);
        reset(); bios = "ACADL357.0059.2024.0101.0000";
        assert(check_features_bios() == 0 && !qc71_features.batt_charge_limit);
        reset(); bios = "QCCFL357.0114.2024.0101.0000";
        assert(check_features_bios() == -EOPNOTSUPP && !qc71_features.batt_charge_limit);
        reset(); bios = "ACADL357.invalid.2024.0101.0000";
        assert(check_features_bios() == -EINVAL && !qc71_features.batt_charge_limit);
        reset(); bios = NULL;
        assert(check_features_bios() == -ENOENT && !qc71_features.batt_charge_limit);
        reset(); bios = "ACADL357.0060.2024.0101.0000"; oem = "";
        assert(check_features_bios() == 0 && !qc71_features.batt_charge_limit);
        reset(); oem = "not a feature string";
        assert(check_features_bios() == 0 && !qc71_features.batt_charge_limit);
        reset(); support2 = 0;
        check_features_ec(); assert(!qc71_features.keyboard_backlight);
        reset(); support2 = -EIO;
        check_features_ec(); assert(!qc71_features.keyboard_backlight);
    }
    const char *others[] = { "LAPAC71G-other", "LAPAC71H-other", "LAPAC71", "LAPAC71X" };
    for (size_t i = 0; i < sizeof(others)/sizeof(others[0]); i++) {
        board = others[i]; reset();
        assert(!qc71_is_lapac71());
        assert(check_features_bios() == -ENODEV);
        check_features_ec(); assert(!qc71_features.keyboard_backlight);
    }
    board = "LAPQC71A"; reset(); bios = "QCCFL357.0113.2024.0101.0000";
    assert(check_features_bios() == 0 && !qc71_features.batt_charge_limit);
    bios = "QCCFL357.0114.2024.0101.0000";
    assert(check_features_bios() == 0 && qc71_features.batt_charge_limit);
    assert(!qc71_is_lapac71());
    check_features_ec(); assert(!qc71_features.keyboard_backlight);
    puts("PASS: LAPAC71G/H exact DMI, shared ACADL357 >=0060 gate, OEM/capability guards, original QC71 >=0114 gate");
}
'''

with TemporaryDirectory(prefix='qc71-features-tests-') as directory:
    source = Path(directory) / 'test_features.c'
    binary = Path(directory) / 'test_features'
    source.write_text(STUBS + without_includes('ec.h') + without_includes('features.h')
                      + without_includes('features.c') + TESTS)
    subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + [
        '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
        '-fsanitize=address,undefined', '-g', str(source), '-o', str(binary),
    ], check=True)
    environment = os.environ.copy()
    environment.setdefault('ASAN_OPTIONS', 'detect_leaks=0')
    subprocess.run([str(binary)], check=True, env=environment)
