// SPDX-License-Identifier: GPL-2.0
#include "pr.h"

#include <linux/init.h>
#include <linux/moduleparam.h>
#include <linux/notifier.h>
#include <linux/suspend.h>
#include <linux/types.h>
#include <uapi/asm-generic/errno-base.h>

#include "hwmon.h"
#include "fan.h"
#include "hwmon_fan.h"
#include "hwmon_pwm.h"

/* ========================================================================== */

static bool nohwmon;
module_param(nohwmon, bool, 0444);
MODULE_PARM_DESC(nohwmon, "do not report to the hardware monitoring subsystem (default=false)");

/* ========================================================================== */

static int qc71_hwmon_pm_notify(struct notifier_block *nb,
			       unsigned long action, void *data)
{
	int err;

	switch (action) {
	case PM_HIBERNATION_PREPARE:
	case PM_SUSPEND_PREPARE:
	case PM_RESTORE_PREPARE:
		/* Leave fan curves to firmware across sleep; do not replay PWM. */
		err = qc71_fan_suspend();
		if (err)
			return notifier_from_errno(err);
		break;
	case PM_POST_HIBERNATION:
	case PM_POST_SUSPEND:
	case PM_POST_RESTORE:
		qc71_fan_resume();
		break;
	}

	return NOTIFY_DONE;
}

static struct notifier_block qc71_hwmon_pm_notifier = {
	.notifier_call = qc71_hwmon_pm_notify,
};

int __init qc71_hwmon_setup(void)
{
	int err;

	if (nohwmon)
		return -ENODEV;

	err = qc71_hwmon_fan_setup();
	if (err)
		return err;

	err = qc71_hwmon_pwm_setup();
	if (err && err != -ENODEV) {
		qc71_hwmon_fan_cleanup();
		return err;
	}

	err = register_pm_notifier(&qc71_hwmon_pm_notifier);
	if (err) {
		qc71_hwmon_pwm_cleanup();
		qc71_hwmon_fan_cleanup();
		return err;
	}

	return 0;
}

void qc71_hwmon_cleanup(void)
{
	unregister_pm_notifier(&qc71_hwmon_pm_notifier);
	qc71_hwmon_pwm_cleanup();
	qc71_hwmon_fan_cleanup();
}
