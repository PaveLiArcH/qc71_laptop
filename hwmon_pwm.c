// SPDX-License-Identifier: GPL-2.0
#include "pr.h"

#include <linux/device.h>
#include <linux/dmi.h>
#include <linux/hwmon.h>
#include <linux/hwmon-sysfs.h>
#include <linux/init.h>
#include <linux/lockdep.h>
#include <linux/mutex.h>
#include <linux/moduleparam.h>
#include <linux/sysfs.h>
#include <linux/types.h>

#include "fan.h"
#include "features.h"
#include "hwmon_pwm.h"
#include "pdev.h"

/* ========================================================================== */

static struct device *qc71_hwmon_pwm_dev;

static bool fan_control;
module_param(fan_control, bool, 0444);
MODULE_PARM_DESC(fan_control,
	"expose experimental LAPAC71G/H PWM controls even without EC capability bit (default=false)");

/* ========================================================================== */

static umode_t qc71_hwmon_pwm_is_visible(const void *data, enum hwmon_sensor_types type,
					 u32 attr, int channel)
{
	if (type != hwmon_pwm || channel < 0 || channel > 1)
		return 0;
	if (attr != hwmon_pwm_input &&
	    (attr != hwmon_pwm_enable || channel != 0))
		return 0;

	return 0644;
}

static int qc71_hwmon_pwm_read(struct device *device, enum hwmon_sensor_types type,
			       u32 attr, int channel, long *value)
{
	int err;

	switch (type) {
	case hwmon_pwm:
		switch (attr) {
		case hwmon_pwm_enable:
			err = qc71_fan_get_mode();
			if (err < 0)
				return err;

			*value = err;
			break;
		case hwmon_pwm_input:
			err = qc71_fan_get_pwm(channel);
			if (err < 0)
				return err;

			*value = err;
			break;
		default:
			return -EOPNOTSUPP;
		}
		break;
	default:
		return -EOPNOTSUPP;
	}

	return 0;
}

static int qc71_hwmon_pwm_write(struct device *device, enum hwmon_sensor_types type,
			    u32 attr, int channel, long value)
{
	if (channel < 0 || channel > 1)
		return -EINVAL;

	switch (type) {
	case hwmon_pwm:
		switch (attr) {
		case hwmon_pwm_enable:
			if (channel != 0 || value < 0 || value > 2)
				return -EINVAL;
			return qc71_fan_set_mode(value);
		case hwmon_pwm_input:
			if (value < 0 || value > U8_MAX)
				return -EINVAL;
			return qc71_fan_set_pwm(channel, value);
		default:
			return -EOPNOTSUPP;
		}
	default:
		return -EOPNOTSUPP;
	}

	return 0;
}

static const struct hwmon_channel_info *qc71_hwmon_pwm_ch_info[] = {
	/* The EC has one shared control mode for both fan outputs. */
	HWMON_CHANNEL_INFO(pwm, HWMON_PWM_INPUT | HWMON_PWM_ENABLE,
			   HWMON_PWM_INPUT),
	NULL
};

static const struct hwmon_ops qc71_hwmon_pwm_ops = {
	.is_visible  = qc71_hwmon_pwm_is_visible,
	.read        = qc71_hwmon_pwm_read,
	.write       = qc71_hwmon_pwm_write,
};

static const struct hwmon_chip_info qc71_hwmon_pwm_chip_info = {
	.ops  = &qc71_hwmon_pwm_ops,
	.info =  qc71_hwmon_pwm_ch_info,
};

/* ========================================================================== */

int __init qc71_hwmon_pwm_setup(void)
{
	if (!qc71_features.fan_boost &&
	    !(fan_control && qc71_is_lapac71()))
		return -ENODEV;

	qc71_hwmon_pwm_dev = hwmon_device_register_with_info(
		&qc71_platform_dev->dev, KBUILD_MODNAME ".hwmon.pwm", NULL,
		&qc71_hwmon_pwm_chip_info, NULL);

	if (IS_ERR(qc71_hwmon_pwm_dev))
		return PTR_ERR(qc71_hwmon_pwm_dev);

	return 0;
}

void qc71_hwmon_pwm_cleanup(void)
{
	if (!IS_ERR_OR_NULL(qc71_hwmon_pwm_dev))
		hwmon_device_unregister(qc71_hwmon_pwm_dev);
	qc71_hwmon_pwm_dev = NULL;
	qc71_fan_cleanup();
}
