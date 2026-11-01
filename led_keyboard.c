// SPDX-License-Identifier: GPL-2.0
#include "pr.h"

#include <linux/kconfig.h>
#include <linux/kernel.h>
#include <linux/moduleparam.h>

static int keyboard_protocol_get(char *buffer, const struct kernel_param *param)
{
	return sprintf(buffer, "intel-ac-dc-v1");
}

static const struct kernel_param_ops keyboard_protocol_ops = {
	.get = keyboard_protocol_get,
};
module_param_cb(keyboard_backlight_protocol, &keyboard_protocol_ops, NULL, 0444);
MODULE_PARM_DESC(keyboard_backlight_protocol, "keyboard backlight protocol (read-only)");

#if IS_ENABLED(CONFIG_LEDS_CLASS_MULTICOLOR) && IS_ENABLED(CONFIG_POWER_SUPPLY)
#include <linux/delay.h>
#include <linux/dmi.h>
#include <linux/led-class-multicolor.h>
#include <linux/mutex.h>
#include <linux/power_supply.h>
#include <linux/version.h>
#include <linux/workqueue.h>

#include "ec.h"
#include "features.h"
#include "led_keyboard.h"
#include "pdev.h"

/* Intel X15 AC/DC profile protocol, verified on LAPAC71G. */
#define KBD_AC_CTRL_ADDR    ADDR(0x07, 0xea)
#define KBD_DC_CTRL_ADDR    ADDR(0x07, 0xeb)
#define KBD_LEVEL_MASK      GENMASK(2, 0)
#define KBD_APPLY           BIT(3)
#define KBD_OFF             BIT(4)
#define KBD_RAINBOW         BIT(5)
#define KBD_CTRL_MASK       (KBD_LEVEL_MASK | KBD_APPLY | KBD_OFF | KBD_RAINBOW)
#define KBD_MAX_COLOR       50
#define KBD_MAX_LEVEL       4

static bool keyboard_backlight;
module_param(keyboard_backlight, bool, 0444);
MODULE_PARM_DESC(keyboard_backlight,
	"enable experimental LAPAC71G/H single-zone RGB keyboard LED (default=false)");

struct keyboard_profile {
	bool ac;
	uint8_t ctrl;
	uint8_t rgb[3];
};

/* Callbacks take keyboard_lock -> ec_lock, never led_access. Refresh work takes
 * led_access, drains LED work, then takes keyboard_lock -> ec_lock.
 */
static DEFINE_MUTEX(keyboard_lock);
static bool keyboard_registered, keyboard_unregistering, keyboard_notifier_registered;
static bool keyboard_cache_valid, keyboard_cached_ac;
static unsigned int keyboard_published_colors[3];
static struct led_classdev_mc keyboard_led;
static void keyboard_refresh_workfn(struct work_struct *work);
static DECLARE_WORK(keyboard_refresh_work, keyboard_refresh_workfn);
static const uint16_t keyboard_color_addrs[2][3] = {
	{ ADDR(0x07, 0xec), ADDR(0x07, 0xed), ADDR(0x07, 0xee) },
	{ ADDR(0x07, 0x69), ADDR(0x07, 0x6a), ADDR(0x07, 0x6b) },
};

static struct mc_subled keyboard_colors[] = {
	{ .color_index = LED_COLOR_ID_RED },
	{ .color_index = LED_COLOR_ID_GREEN },
	{ .color_index = LED_COLOR_ID_BLUE },
};

static uint16_t keyboard_ctrl_addr(bool ac)
{
	return ac ? KBD_AC_CTRL_ADDR : KBD_DC_CTRL_ADDR;
}

static int keyboard_active_power(bool *ac)
{
	struct power_supply *adapter = power_supply_get_by_name("AC0");
	union power_supply_propval online;
	int supplied, err;

	/* This board has AC0. Avoid the API's no-supplies-means-AC fallback. */
	if (!adapter)
		return -ENODEV;
	err = power_supply_get_property(adapter, POWER_SUPPLY_PROP_ONLINE, &online);
	power_supply_put(adapter);
	if (err)
		return err;
	supplied = power_supply_is_system_supplied();
	if (supplied < 0)
		return supplied;
	*ac = !!supplied;
	return 0;
}

static int keyboard_check_power(bool ac)
{
	bool current_ac;
	int err = keyboard_active_power(&current_ac);

	return err ? err : (ac == current_ac ? 0 : -EAGAIN);
}

static void keyboard_queue_refresh(void)
{
	if (READ_ONCE(keyboard_registered) && !READ_ONCE(keyboard_unregistering))
		schedule_work(&keyboard_refresh_work);
}

static int keyboard_read_profile(bool ac, struct keyboard_profile *profile)
{
	int value;
	size_t i;

	profile->ac = ac;
	value = ec_read_byte(keyboard_ctrl_addr(ac));
	if (value < 0)
		return value;
	if ((value & KBD_LEVEL_MASK) > KBD_MAX_LEVEL)
		return -EOPNOTSUPP;
	profile->ctrl = value;
	for (i = 0; i < ARRAY_SIZE(profile->rgb); i++) {
		value = ec_read_byte(keyboard_color_addrs[ac][i]);
		if (value < 0)
			return value;
		if (value > KBD_MAX_COLOR)
			return -EOPNOTSUPP;
		profile->rgb[i] = value;
	}
	return keyboard_check_power(ac);
}

static enum led_brightness keyboard_profile_brightness(uint8_t ctrl)
{
	if (ctrl & KBD_OFF)
		return LED_OFF;
	return DIV_ROUND_CLOSEST((ctrl & KBD_LEVEL_MASK) * 255, KBD_MAX_LEVEL);
}

static void keyboard_publish_profile(const struct keyboard_profile *profile)
{
	size_t i;

	for (i = 0; i < ARRAY_SIZE(keyboard_colors); i++) {
		keyboard_published_colors[i] = DIV_ROUND_CLOSEST(profile->rgb[i] * 255,
							       KBD_MAX_COLOR);
		keyboard_colors[i].intensity = keyboard_published_colors[i];
	}
	keyboard_led.led_cdev.brightness = keyboard_profile_brightness(profile->ctrl);
	keyboard_cached_ac = profile->ac;
	keyboard_cache_valid = true;
}

static void keyboard_refresh_workfn(struct work_struct *work)
{
	struct led_classdev *led = &keyboard_led.led_cdev;
	struct keyboard_profile profile;
	bool ac;
	int err;

	mutex_lock(&led->led_access);
	/* Pending requests from the old profile must fail before publishing a new
	 * color cache. The LED callback does not acquire led_access.
	 */
	flush_work(&led->set_brightness_work);
	mutex_lock(&keyboard_lock);
	if (keyboard_unregistering)
		goto out;
	err = keyboard_active_power(&ac);
	if (err)
		goto failed;
	/* Battery property notifications must not discard a user's color request. */
	if (keyboard_cache_valid && keyboard_cached_ac == ac)
		goto out;
	err = keyboard_read_profile(ac, &profile);
	if (err)
		goto failed;
	keyboard_publish_profile(&profile);
	goto out;
failed:
	keyboard_cache_valid = false;
	pr_warn("cannot refresh keyboard profile: %d\n", err);
out:
	mutex_unlock(&keyboard_lock);
	mutex_unlock(&led->led_access);
}

static int keyboard_power_changed(struct notifier_block *notifier,
				   unsigned long event, void *data)
{
	keyboard_queue_refresh();
	return NOTIFY_OK;
}

static struct notifier_block keyboard_power_notifier = {
	.notifier_call = keyboard_power_changed,
};

/* This is the configured target. Native Fn changes the physical output without
 * changing these bytes, so do not advertise LED_BRIGHT_HW_CHANGED.
 */
static enum led_brightness keyboard_get_brightness(struct led_classdev *led)
{
	bool ac;
	int ctrl, err;
	int brightness = -ENODEV;

	mutex_lock(&keyboard_lock);
	if (keyboard_unregistering)
		goto out;
	err = keyboard_active_power(&ac);
	if (err) {
		brightness = err;
		goto out;
	}
	if (!keyboard_cache_valid || keyboard_cached_ac != ac)
		keyboard_queue_refresh();
	ctrl = ec_read_byte(keyboard_ctrl_addr(ac));
	if (ctrl < 0) {
		brightness = ctrl;
		goto out;
	}
	if ((ctrl & KBD_LEVEL_MASK) > KBD_MAX_LEVEL) {
		brightness = -EOPNOTSUPP;
		goto out;
	}
	err = keyboard_check_power(ac);
	if (err) {
		brightness = err;
		goto out;
	}
	brightness = keyboard_profile_brightness(ctrl);
out:
	mutex_unlock(&keyboard_lock);
	return brightness;
}

/* Restore configured values after an ambiguous failed write. Applying a saved
 * target cannot restore a native Fn output which differs from that target.
 */
static int keyboard_restore_profile(const struct keyboard_profile *profile, bool colors)
{
	int err, first_error = 0;
	size_t i;

	if (colors) {
		for (i = 0; i < ARRAY_SIZE(profile->rgb); i++) {
			err = ec_write_byte(keyboard_color_addrs[profile->ac][i], profile->rgb[i]);
			if (err && !first_error)
				first_error = err;
		}
		msleep(6);
	}
	err = ec_update_bits(keyboard_ctrl_addr(profile->ac), KBD_CTRL_MASK,
			     (profile->ctrl & ~KBD_APPLY) | KBD_APPLY);
	return first_error ? first_error : err;
}

static int keyboard_set_brightness(struct led_classdev *led,
				   enum led_brightness brightness)
{
	struct led_classdev_mc *mc = lcdev_to_mccdev(led);
	struct keyboard_profile old;
	unsigned int intensity[3], level, value, mask;
	bool ac, color_changed = false, black = true, wrote = false;
	int err = 0, restore_error;
	size_t i;

	mutex_lock(&keyboard_lock);
	if (keyboard_unregistering)
		goto out;
	if ((unsigned int)brightness > 255) {
		err = -EINVAL;
		goto out;
	}
	err = keyboard_active_power(&ac);
	if (err)
		goto out;
	if (!keyboard_cache_valid || keyboard_cached_ac != ac) {
		keyboard_queue_refresh();
		err = -EAGAIN;
		goto out;
	}
	for (i = 0; i < ARRAY_SIZE(intensity); i++) {
		intensity[i] = READ_ONCE(mc->subled_info[i].intensity);
		if (intensity[i] > 255) {
			err = -EINVAL;
			goto out;
		}
		color_changed |= intensity[i] != keyboard_published_colors[i];
		black &= DIV_ROUND_CLOSEST(intensity[i] * KBD_MAX_COLOR, 255) == 0;
	}
	err = keyboard_read_profile(ac, &old);
	if (err)
		goto refresh;
	level = brightness ? max_t(unsigned int, 1,
		DIV_ROUND_CLOSEST(brightness * KBD_MAX_LEVEL, 255)) : 0;
	if (black)
		level = 0;

	if (color_changed && !black) {
		for (i = 0; i < ARRAY_SIZE(intensity); i++) {
			err = keyboard_check_power(ac);
			if (err)
				goto failed;
			wrote = true; /* An error does not prove the EC ignored the write. */
			err = ec_write_byte(keyboard_color_addrs[ac][i],
				DIV_ROUND_CLOSEST(intensity[i] * KBD_MAX_COLOR, 255));
			if (err)
				goto failed;
		}
		msleep(6);
	}
	err = keyboard_check_power(ac);
	if (err)
		goto failed;
	mask = KBD_LEVEL_MASK | KBD_APPLY | KBD_OFF;
	value = KBD_APPLY | (level ? level : (old.ctrl & KBD_LEVEL_MASK) | KBD_OFF);
	if (color_changed)
		mask |= KBD_RAINBOW; /* An explicit color change requests static color. */
	wrote = true;
	err = ec_update_bits(keyboard_ctrl_addr(ac), mask, value);
	if (err)
		goto failed;
	err = keyboard_check_power(ac);
	if (err)
		goto failed;
	for (i = 0; i < ARRAY_SIZE(intensity); i++)
		keyboard_published_colors[i] = intensity[i];
	goto out;
failed:
	if (wrote) {
		restore_error = keyboard_restore_profile(&old, color_changed && !black);
		if (restore_error)
			pr_err("keyboard profile restore failed: %d (original error %d)\n",
			       restore_error, err);
	}
refresh:
	keyboard_cache_valid = false;
	keyboard_queue_refresh();
out:
	mutex_unlock(&keyboard_lock);
	return err;
}

static struct led_classdev_mc keyboard_led = {
	.led_cdev = {
		.name = KBUILD_MODNAME ":rgb:kbd_backlight",
		.max_brightness = 255,
		.brightness_get = keyboard_get_brightness,
		.brightness_set_blocking = keyboard_set_brightness,
	},
	.num_colors = ARRAY_SIZE(keyboard_colors),
	.subled_info = keyboard_colors,
};

int __init qc71_led_keyboard_setup(void)
{
	struct keyboard_profile profile;
	bool ac;
	int err;

	if (!keyboard_backlight)
		return -ENODEV;
	if (!qc71_features.keyboard_backlight || !qc71_is_lapac71())
		return -ENODEV;
	err = keyboard_active_power(&ac);
	if (err)
		return err;
	err = keyboard_read_profile(ac, &profile);
	if (err)
		return err;
	keyboard_publish_profile(&profile);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(7, 2, 0)
	for (size_t i = 0; i < ARRAY_SIZE(keyboard_colors); i++)
		keyboard_colors[i].max_intensity = 255;
#endif
	err = led_classdev_multicolor_register(&qc71_platform_dev->dev, &keyboard_led);
	if (err)
		return err;
	WRITE_ONCE(keyboard_registered, true);
	err = power_supply_reg_notifier(&keyboard_power_notifier);
	if (err) {
		qc71_led_keyboard_cleanup();
		return err;
	}
	keyboard_notifier_registered = true;
	keyboard_queue_refresh();
	return 0;
}

void qc71_led_keyboard_cleanup(void)
{
	if (!keyboard_registered)
		return;
	mutex_lock(&keyboard_lock);
	WRITE_ONCE(keyboard_unregistering, true);
	mutex_unlock(&keyboard_lock);
	if (keyboard_notifier_registered) {
		power_supply_unreg_notifier(&keyboard_power_notifier);
		keyboard_notifier_registered = false;
	}
	cancel_work_sync(&keyboard_refresh_work);
	led_classdev_multicolor_unregister(&keyboard_led);
	WRITE_ONCE(keyboard_registered, false);
}
#endif
