#!/usr/bin/env python3
"""Compile real EC/keyboard LED code against a fake mailbox, without hardware."""

from pathlib import Path
import os
import re
import shlex
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def without_includes(path):
    return re.sub(r'^#include[^\n]*\n', '', path.read_text(), flags=re.MULTILINE)


STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define __init
#define __must_check
#define current get_current()
#define __aligned(n) __attribute__((aligned(n)))
#define static_assert _Static_assert
#define BIT(n) (1U << (n))
#define GENMASK(h,l) (((~0U) << (l)) & ((~0U) >> (31 - (h))))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x) = (v))
#define max_t(t,a,b) ((t)(a) > (t)(b) ? (t)(a) : (t)(b))
#define pr_err(...) ((void)0)
#define min(a,b) ((a) < (b) ? (a) : (b))
#define DIV_ROUND_CLOSEST(n,d) (((n) + (d) / 2) / (d))
#define pr_debug(...) ((void)0)
#define pr_warn(...) ((void)0)
#define ALLOW_ERROR_INJECTION(...)
struct kernel_param { int unused; };
struct kernel_param_ops { int (*get)(char *, const struct kernel_param *); };
#define module_param_cb(name,ops,arg,mode) static const void *used_##name __attribute__((unused)) = (ops)
#define module_param(...)
#define MODULE_PARM_DESC(...)
#define KBUILD_MODNAME "qc71_laptop"
#define KERNEL_VERSION(a,b,c) (((a) << 16) | ((b) << 8) | (c))
#define LINUX_VERSION_CODE KERNEL_VERSION(7,2,0)
#define CONFIG_LEDS_CLASS_MULTICOLOR 1
#define CONFIG_LEDS_CLASS 1
#define CONFIG_POWER_SUPPLY 1
#define IS_ENABLED(x) (x)
#define ACPI_TYPE_BUFFER 3
#define AE_OK 0
#define ACPI_FAILURE(x) ((x) != AE_OK)
#define QC71_WMI_WMBC_GUID "ABBC0F6F-8EA1-11D1-00A0-C90629100000"
#define QC71_WMBC_GETSETULONG_ID 4

typedef int acpi_status;
union acpi_object {
    int type;
    struct { int type; unsigned int length; uint8_t *pointer; } buffer;
};
struct acpi_buffer { size_t length; void *pointer; };
struct mock_mutex { bool held; };
#define DEFINE_MUTEX(name) struct mock_mutex name
static int interrupted_lock;
static void mutex_lock(struct mock_mutex *lock) {
    assert(!lock->held);
    lock->held = true;
}
static int mutex_lock_killable(struct mock_mutex *lock) {
    if (interrupted_lock) return interrupted_lock;
    mutex_lock(lock);
    return 0;
}
static void mutex_unlock(struct mock_mutex *lock) {
    assert(lock->held);
    lock->held = false;
}
static acpi_status wmi_evaluate_method(const char *, unsigned int, unsigned int,
                                      struct acpi_buffer *, struct acpi_buffer *);
static struct mock_mutex *keyboard_mutex_for_work;
struct work_struct { void (*fn)(struct work_struct *); bool pending; };
#define DECLARE_WORK(name,callback) struct work_struct name = { .fn = (callback) }
static bool schedule_work(struct work_struct *work) { work->pending = true; return true; }
static bool flush_work(struct work_struct *work) {
    if (keyboard_mutex_for_work) assert(!keyboard_mutex_for_work->held);
    if (!work->pending) return false;
    work->pending = false;
    work->fn(work);
    return true;
}
static bool cancel_work_sync(struct work_struct *work) { work->pending = false; return true; }
static unsigned int sleeps;
static void msleep(unsigned int delay) { assert(delay >= 6); sleeps++; }
static int supplied = 1, power_error, power_queries, flip_power_on_query;
struct power_supply { int unused; };
union power_supply_propval { int intval; };
#define POWER_SUPPLY_PROP_ONLINE 1
static struct power_supply mock_adapter;
static bool adapter_present = true;
static int adapter_error, adapter_refs;
static struct power_supply *power_supply_get_by_name(const char *name) {
    assert(strcmp(name, "AC0") == 0);
    if (!adapter_present) return NULL;
    adapter_refs++;
    return &mock_adapter;
}
static int power_supply_get_property(struct power_supply *psy, int property,
                                     union power_supply_propval *value) {
    assert(psy == &mock_adapter && property == POWER_SUPPLY_PROP_ONLINE);
    value->intval = supplied;
    return adapter_error;
}
static void power_supply_put(struct power_supply *psy) {
    assert(psy == &mock_adapter && adapter_refs > 0);
    adapter_refs--;
}
static int power_supply_is_system_supplied(void) {
    power_queries++;
    if (power_queries == flip_power_on_query) supplied = !supplied;
    return power_error ? power_error : supplied;
}
#define NOTIFY_OK 0
struct notifier_block { int (*notifier_call)(struct notifier_block *, unsigned long, void *); };
static bool notifier_live;
static int notifier_error;
static int power_supply_reg_notifier(struct notifier_block *notifier) {
    assert(notifier->notifier_call);
    if (notifier_error) return notifier_error;
    notifier_live = true;
    return 0;
}
static void power_supply_unreg_notifier(struct notifier_block *notifier) {
    (void)notifier;
    assert(notifier_live);
    notifier_live = false;
}
#define DMI_BOARD_NAME 1
static const char *mock_board = "LAPAC71G";
static bool dmi_match(int field, const char *value) { (void)field; return strcmp(mock_board,value) == 0; }
enum led_brightness { LED_OFF = 0, LED_FULL = 255 };
#define LED_COLOR_ID_RED 1
#define LED_COLOR_ID_GREEN 2
#define LED_COLOR_ID_BLUE 3
#define LED_BRIGHT_HW_CHANGED BIT(21)
struct led_classdev {
    const char *name;
    unsigned int max_brightness;
    enum led_brightness brightness;
    enum led_brightness (*brightness_get)(struct led_classdev *);
    int (*brightness_set_blocking)(struct led_classdev *, enum led_brightness);
    unsigned long flags;
    struct mock_mutex led_access;
    struct work_struct set_brightness_work;
};
struct mc_subled { unsigned int color_index, intensity, max_intensity; };
struct led_classdev_mc {
    struct led_classdev led_cdev;
    unsigned int num_colors;
    struct mc_subled *subled_info;
};
static struct led_classdev_mc *lcdev_to_mccdev(struct led_classdev *led) {
    return (struct led_classdev_mc *)led;
}
struct device { int unused; };
static struct { struct device dev; } platform;
static typeof(platform) *qc71_platform_dev = &platform;
static struct { bool keyboard_backlight; } qc71_features;
static unsigned int registrations, unregistrations;
static int registration_error;
static struct led_classdev *mock_led;
static enum led_brightness pending_brightness;
static int pending_result;
static void mock_led_work(struct work_struct *work) {
    (void)work;
    pending_result = mock_led->brightness_set_blocking(mock_led, pending_brightness);
}
static int led_classdev_multicolor_register(struct device *parent,
                                            struct led_classdev_mc *led) {
    assert(parent == &platform.dev && led->num_colors == 3);
    registrations++;
    mock_led = &led->led_cdev;
    mock_led->set_brightness_work.fn = mock_led_work;
    return registration_error;
}
static void led_classdev_multicolor_unregister(struct led_classdev_mc *led) {
    unregistrations++;
    /* Exercise the LED core's shutdown callback, not just an inert stub. */
    assert(led->led_cdev.brightness_set_blocking(&led->led_cdev, LED_OFF) == 0);
}
'''

MAILBOX = r'''
static uint8_t registers[UINT16_MAX + 1];
static uint8_t request[8];
static unsigned int transactions, writes;
static unsigned int switch_on_transaction;
static bool fail_after_write, trace_enabled;
static uint16_t written_addrs[1024];
static uint8_t written_values[1024];
static unsigned int trace_count, last_rgb_sleep;
static bool dirty_rgb;
enum reply_kind { VALID, NULL_OBJECT, WRONG_TYPE, NULL_BUFFER, SHORT_BUFFER,
                  SENTINEL, STATUS_FAILURE };
static enum reply_kind reply_kind;
static unsigned int reply_length = 40;
static unsigned int fail_on_transaction;
static acpi_status wmi_evaluate_method(const char *guid, unsigned int instance,
                                      unsigned int method, struct acpi_buffer *in,
                                      struct acpi_buffer *out) {
    assert(ec_lock.held);
    assert(strcmp(guid, QC71_WMI_WMBC_GUID) == 0 && instance == 0 && method == 4);
    assert(in->length == 8);
    memcpy(request, in->pointer, 8);
    assert(request[4] == 0 && request[5] <= 1 && request[6] == 0 && request[7] == 0);
    uint16_t addr = request[0] | ((uint16_t)request[1] << 8);
    bool read = request[5];
    transactions++;
    if (transactions == switch_on_transaction) supplied = !supplied;
    if (!read) {
        writes++;
        if (trace_enabled) {
            assert(trace_count < ARRAY_SIZE(written_addrs));
            written_addrs[trace_count] = addr;
            written_values[trace_count++] = request[2];
        }
    }
    enum reply_kind kind = fail_on_transaction && transactions != fail_on_transaction
                         ? VALID : reply_kind;
    if (kind == STATUS_FAILURE) {
        if (fail_after_write && !read) registers[addr] = request[2];
        return 1;
    }
    if (kind == NULL_OBJECT) { out->pointer = NULL; return AE_OK; }
    assert(out->length >= sizeof(union acpi_object) + 40);
    union acpi_object *obj = out->pointer;
    uint8_t *payload = (uint8_t *)(obj + 1);
    memset(payload, 0, 40);
    obj->buffer.type = kind == WRONG_TYPE ? 1 : ACPI_TYPE_BUFFER;
    obj->buffer.length = kind == SHORT_BUFFER ? reply_length : 40;
    obj->buffer.pointer = kind == NULL_BUFFER ? NULL : payload;
    if (kind == SENTINEL) memset(payload, 0xfe, 4);
    else if (kind == VALID) {
        if (read) payload[0] = registers[addr];
        else {
            if (trace_enabled && ((addr >= 0x0769 && addr <= 0x076b) ||
                                  (addr >= 0x07ec && addr <= 0x07ee))) {
                dirty_rgb = true;
                last_rgb_sleep = sleeps;
            }
            if ((addr == 0x07ea || addr == 0x07eb) && (request[2] & 8)) {
                if (dirty_rgb) assert(sleeps > last_rgb_sleep);
                dirty_rgb = false;
                registers[addr] = request[2] & ~8; /* Apply is self-clearing. */
            } else registers[addr] = request[2];
            memcpy(payload, request, 4);
        }
    }
    return AE_OK;
}
'''

TESTS = r'''
static void reset(void) {
    memset(registers, 0, sizeof(registers));
    memset(keyboard_colors, 0, sizeof(keyboard_colors));
    transactions = writes = registrations = unregistrations = 0;
    reply_kind = VALID;
    reply_length = 40;
    fail_on_transaction = 0;
    interrupted_lock = registration_error = 0;
    keyboard_backlight = true;
    qc71_features.keyboard_backlight = true;
    keyboard_registered = keyboard_unregistering = false;
    keyboard_cache_valid = keyboard_notifier_registered = false;
    keyboard_refresh_work.pending = keyboard_led.led_cdev.set_brightness_work.pending = false;
    keyboard_mutex_for_work = &keyboard_lock;
    supplied = 1;
    power_error = power_queries = flip_power_on_query = 0;
    notifier_live = false;
    notifier_error = 0;
    sleeps = trace_count = switch_on_transaction = 0;
    fail_after_write = trace_enabled = dirty_rgb = false;
    mock_board = "LAPAC71G";
    adapter_present = true;
    adapter_error = 0;
    assert(adapter_refs == 0);
    assert(!ec_lock.held && !keyboard_lock.held && !keyboard_led.led_cdev.led_access.held);
}

static void test_ec(void) {
    reset();
    union qc71_ec_result output;
    static const enum reply_kind invalid[] = {
        NULL_OBJECT, WRONG_TYPE, NULL_BUFFER, SHORT_BUFFER, SENTINEL, STATUS_FAILURE
    };
    for (size_t i = 0; i < ARRAY_SIZE(invalid); i++) {
        reply_kind = invalid[i];
        reply_length = 3;
        output.dword = 0x12345678;
        int expected = reply_kind >= SENTINEL ? -EIO : -ENODATA;
        assert(qc71_ec_read(0x1234, &output) == expected);
        assert(output.dword == 0x12345678 && !ec_lock.held);
        assert(qc71_ec_write(0x1234, 0x5678) == expected);
    }
    for (reply_length = 0; reply_length < 4; reply_length++) {
        reply_kind = SHORT_BUFFER;
        assert(qc71_ec_read(0x1234, &output) == -ENODATA);
    }
    reply_kind = VALID;
    registers[0x1234] = 0xab;
    assert(qc71_ec_read(0x1234, &output) == 0 && output.dword == 0xab);
    assert(request[0] == 0x34 && request[1] == 0x12 && request[5] == 1);
    assert(qc71_ec_write(0x1234, 0x5678) == 0);
    assert(request[2] == 0x78 && request[3] == 0x56 && request[5] == 0);
    unsigned int before = transactions;
    interrupted_lock = -EINTR;
    assert(qc71_ec_read(0, &output) == -EINTR);
    assert(ec_update_bits(0, 0xff, 0) == -EINTR && transactions == before);
    interrupted_lock = 0;

    static const uint8_t masks[] = { 0, 1, 0x0f, 0x7f, 0x80, 0xf0, 0xff };
    for (unsigned int old = 0; old < 256; old++)
        for (unsigned int value = 0; value < 256; value++)
            for (size_t i = 0; i < ARRAY_SIZE(masks); i++) {
                registers[0x1234] = old;
                assert(ec_update_bits(0x1234, masks[i], value) == 0);
                assert(registers[0x1234] == ((old & ~masks[i]) | (value & masks[i])));
            }
    writes = 0;
    reply_kind = STATUS_FAILURE;
    assert(ec_update_bits(0x1234, 0x7f, 80) == -EIO && writes == 0);
    fail_on_transaction = transactions + 2;
    assert(ec_update_bits(0x1234, 0x7f, 80) == -EIO && writes == 1);
}


static void seed_profiles(void) {
    registers[0x07ea] = 0xe2; /* AC level two, rainbow, unrelated upper flags. */
    registers[0x07eb] = 0x51; /* DC level one, off, unrelated upper flag. */
    registers[0x0769] = registers[0x076a] = registers[0x076b] = 50;
    registers[0x07ec] = 50; /* DC red must never be replaced by cached AC white. */
    registers[0x07ed] = registers[0x07ee] = 0;
    registers[0x0741] = 0x14;
    registers[0x078c] = 0x23;
    registers[0x0751] = 0x20;
    trace_enabled = true;
}

static void assert_old_registers_untouched(void) {
    assert(registers[0x0741] == 0x14 && registers[0x078c] == 0x23 && registers[0x0751] == 0x20);
    for (unsigned int i = 0; i < trace_count; i++)
        assert(written_addrs[i] != 0x0741 && written_addrs[i] != 0x078c &&
               written_addrs[i] != 0x0751 && (written_addrs[i] & 0xff00) != 0x1800);
}

static void test_led(void) {
    reset();
    char protocol[64];
    assert(keyboard_protocol_ops.get(protocol, NULL) == 14);
    assert(strcmp(protocol, "intel-ac-dc-v1") == 0);
    keyboard_backlight = false;
    assert(qc71_led_keyboard_setup() == -ENODEV && transactions == 0);
    keyboard_backlight = true;
    qc71_features.keyboard_backlight = false;
    assert(qc71_led_keyboard_setup() == -ENODEV && transactions == 0);
    qc71_features.keyboard_backlight = true;
    mock_board = "LAPAC71G-other";
    assert(qc71_led_keyboard_setup() == -ENODEV && transactions == 0);
    mock_board = "LAPAC71G";
    adapter_present = false;
    assert(qc71_led_keyboard_setup() == -ENODEV && transactions == 0 && adapter_refs == 0);
    adapter_present = true;
    adapter_error = -EIO;
    assert(qc71_led_keyboard_setup() == -EIO && transactions == 0 && adapter_refs == 0);
    adapter_error = 0;
    power_error = -ENODEV;
    assert(qc71_led_keyboard_setup() == -ENODEV && transactions == 0);
    power_error = 0;
    seed_profiles();
    registers[0x0769] = 51;
    assert(qc71_led_keyboard_setup() == -EOPNOTSUPP && writes == 0);
    registers[0x0769] = 50;
    registers[0x07ea] = 5;
    assert(qc71_led_keyboard_setup() == -EOPNOTSUPP && writes == 0);
    reply_kind = STATUS_FAILURE;
    assert(qc71_led_keyboard_setup() == -EIO && writes == 0);

    static const enum led_brightness levels[] = { 64, 128, 191, 255 };
    for (unsigned int raw = 0; raw <= 50; raw++) {
        reset(); seed_profiles();
        registers[0x0769] = raw;
        registers[0x076a] = 50 - raw;
        registers[0x076b] = raw;
        assert(qc71_led_keyboard_setup() == 0 && writes == 0 && registrations == 1);
        flush_work(&keyboard_refresh_work);
        assert(writes == 0 && notifier_live);
        for (size_t i = 0; i < ARRAY_SIZE(levels); i++) {
            unsigned int before = writes;
            assert(keyboard_set_brightness(&keyboard_led.led_cdev, levels[i]) == 0);
            assert(writes == before + 1); /* Brightness never rewrites RGB. */
            assert(registers[0x0769] == raw && registers[0x076a] == 50 - raw && registers[0x076b] == raw);
            assert(registers[0x07ea] == (0xe0 | (i + 1)));
            assert(written_values[trace_count - 1] & 8);
            assert(keyboard_get_brightness(&keyboard_led.led_cdev) == levels[i]);
            assert(registers[0x07eb] == 0x51 && registers[0x07ed] == 0);
        }
        assert(keyboard_set_brightness(&keyboard_led.led_cdev, 1) == 0);
        assert((registers[0x07ea] & 7) == 1); /* Nonzero must never become off. */
        assert_old_registers_untouched();
        unsigned int before = writes;
        qc71_led_keyboard_cleanup();
        assert(writes == before && !keyboard_registered && !notifier_live && unregistrations == 1);
        assert(!keyboard_refresh_work.pending);
    }

    reset(); seed_profiles();
    assert(qc71_led_keyboard_setup() == 0);
    power_error = -ENODEV;
    assert((int)keyboard_get_brightness(&keyboard_led.led_cdev) == -ENODEV);
    power_error = 0;
    reply_kind = STATUS_FAILURE;
    assert((int)keyboard_get_brightness(&keyboard_led.led_cdev) == -EIO);
    reply_kind = VALID;
    assert(keyboard_set_brightness(&keyboard_led.led_cdev, 256) == -EINVAL && writes == 0);
    keyboard_colors[0].intensity = 0;
    keyboard_colors[1].intensity = 255;
    keyboard_colors[2].intensity = 0;
    assert(keyboard_set_brightness(&keyboard_led.led_cdev, LED_FULL) == 0);
    assert(registers[0x0769] == 0 && registers[0x076a] == 50 && registers[0x076b] == 0);
    assert(registers[0x07ea] == 0xc4 && sleeps >= 1); /* Explicit green clears rainbow. */
    unsigned int before = writes;
    for (size_t i = 0; i < 3; i++) keyboard_colors[i].intensity = 0;
    assert(keyboard_set_brightness(&keyboard_led.led_cdev, LED_FULL) == 0);
    assert(writes == before + 1 && registers[0x076a] == 50); /* Black -> OFF, keep raw color. */
    assert(registers[0x07ea] == 0xd4 && keyboard_get_brightness(&keyboard_led.led_cdev) == LED_OFF);
    keyboard_power_changed(NULL, 0, NULL);
    flush_work(&keyboard_refresh_work);
    assert(keyboard_colors[1].intensity == 0); /* Same-source battery events keep logical black. */
    before = writes;
    keyboard_colors[0].intensity = 256;
    assert(keyboard_set_brightness(&keyboard_led.led_cdev, LED_FULL) == -EINVAL && writes == before);

    /* Pending old AC color request must be rejected before refreshing DC red. */
    reset(); seed_profiles();
    assert(qc71_led_keyboard_setup() == 0);
    keyboard_colors[0].intensity = 0; keyboard_colors[2].intensity = 0;
    pending_brightness = LED_FULL;
    schedule_work(&keyboard_led.led_cdev.set_brightness_work);
    supplied = 0;
    keyboard_power_changed(NULL, 0, NULL);
    flush_work(&keyboard_refresh_work);
    assert(pending_result == -EAGAIN && writes == 0);
    assert(!keyboard_cached_ac && keyboard_colors[0].intensity == 255 && keyboard_colors[1].intensity == 0);
    assert(keyboard_led.led_cdev.brightness == LED_OFF);
    assert(keyboard_set_brightness(&keyboard_led.led_cdev, 64) == 0);
    assert(registers[0x07eb] == 0x41 && registers[0x07ea] == 0xe2);
    assert(registers[0x07ec] == 50 && registers[0x07ed] == 0 && registers[0x07ee] == 0);
    supplied = 1;
    assert(keyboard_set_brightness(&keyboard_led.led_cdev, LED_FULL) == -EAGAIN);
    unsigned int ac_before = writes;
    assert(keyboard_get_brightness(&keyboard_led.led_cdev) == 128);
    flush_work(&keyboard_refresh_work);
    assert(writes == ac_before && keyboard_cached_ac && keyboard_colors[1].intensity == 255);

    /* A source switch during snapshot must not publish a mixed-profile cache. */
    supplied = 0;
    switch_on_transaction = transactions + 2;
    keyboard_power_changed(NULL, 0, NULL);
    flush_work(&keyboard_refresh_work);
    assert(!keyboard_cache_valid && writes == ac_before);
    switch_on_transaction = 0;
    keyboard_power_changed(NULL, 0, NULL);
    flush_work(&keyboard_refresh_work);
    assert(keyboard_cache_valid && keyboard_cached_ac);

    /* Inject failures at each RGB/control transaction, before and after write. */
    for (unsigned int offset = 5; offset <= 9; offset++)
        for (unsigned int ambiguous = 0; ambiguous < 2; ambiguous++) {
            reset(); seed_profiles();
            assert(qc71_led_keyboard_setup() == 0);
            flush_work(&keyboard_refresh_work);
            keyboard_colors[0].intensity = 0;
            keyboard_colors[1].intensity = 255;
            keyboard_colors[2].intensity = 0;
            reply_kind = STATUS_FAILURE;
            fail_on_transaction = transactions + offset;
            fail_after_write = ambiguous;
            assert(keyboard_set_brightness(&keyboard_led.led_cdev, LED_FULL) == -EIO);
            assert(!keyboard_cache_valid);
            assert(registers[0x0769] == 50 && registers[0x076a] == 50 && registers[0x076b] == 50);
            assert((registers[0x07ea] & ~8) == 0xe2 && registers[0x07eb] == 0x51);
            reply_kind = VALID; fail_on_transaction = 0; fail_after_write = false;
            flush_work(&keyboard_refresh_work);
            assert(keyboard_cache_valid && keyboard_colors[0].intensity == 255);
            assert_old_registers_untouched();
        }

    for (unsigned int offset = 5; offset <= 9; offset++) {
        reset(); seed_profiles();
        assert(qc71_led_keyboard_setup() == 0);
        flush_work(&keyboard_refresh_work);
        keyboard_colors[0].intensity = 0;
        keyboard_colors[1].intensity = 255;
        keyboard_colors[2].intensity = 0;
        switch_on_transaction = transactions + offset;
        assert(keyboard_set_brightness(&keyboard_led.led_cdev, LED_FULL) == -EAGAIN);
        assert(!keyboard_cache_valid);
        assert(registers[0x07eb] == 0x51 && registers[0x07ec] == 50 && registers[0x07ed] == 0);
        for (unsigned int i = 0; i < trace_count; i++)
            assert(written_addrs[i] != 0x07eb && written_addrs[i] != 0x07ec &&
                   written_addrs[i] != 0x07ed && written_addrs[i] != 0x07ee);
        switch_on_transaction = 0;
        flush_work(&keyboard_refresh_work);
        assert(keyboard_cache_valid && !keyboard_cached_ac && keyboard_colors[0].intensity == 255);
    }
    reset(); seed_profiles(); registration_error = -ENOMEM;
    assert(qc71_led_keyboard_setup() == -ENOMEM && !keyboard_registered && writes == 0);
    reset(); seed_profiles(); notifier_error = -ENOMEM;
    assert(qc71_led_keyboard_setup() == -ENOMEM && !keyboard_registered && writes == 0);
    assert(unregistrations == 1);
    assert(adapter_refs == 0);
}

int main(void) {
    test_ec();
    test_led();
    puts("PASS: EC validation/RMW; Intel AC/DC profiles, flags/apply/delay, RGB/black, source refresh and error rollback, no probe/unload writes");
    return 0;
}
'''

with TemporaryDirectory(prefix="qc71-ec-led-tests-") as directory:
    source = Path(directory) / "test_ec_and_led.c"
    binary = Path(directory) / "test_ec_and_led"
    source.write_text(
        STUBS + without_includes(ROOT / "ec.h")
        + without_includes(ROOT / "ec.c") + MAILBOX
        + without_includes(ROOT / "led_keyboard.h")
        + without_includes(ROOT / "led_keyboard.c") + TESTS
    )
    subprocess.run(
        shlex.split(os.environ.get("CC", "cc"))
        + ["-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
           "-fsanitize=address,undefined", "-g", "-o", str(binary), str(source)],
        check=True,
    )
    environment = os.environ.copy()
    environment.setdefault("ASAN_OPTIONS", "detect_leaks=0")
    subprocess.run([str(binary)], check=True, env=environment)
