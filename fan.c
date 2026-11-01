// SPDX-License-Identifier: GPL-2.0
#include "pr.h"

#include <linux/version.h>

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 12, 0)
static inline int fixp_linear_interpolate(int x0, int y0, int x1, int y1, int x)
{
	if (y0 == y1 || x == x0)
		return y0;
	if (x1 == x0 || x == x1)
		return y1;

	return y0 + ((y1 - y0) * (x - x0) / (x1 - x0));
}
#else
#include <linux/bug.h> /* fixp-arith.h needs it, but doesn't include it */
#include <linux/fixp-arith.h>
#endif

#include <linux/lockdep.h>
#include <linux/mutex.h>
#include <linux/types.h>

#include "ec.h"
#include "fan.h"
#include "util.h"

/* ========================================================================== */

static const uint16_t qc71_fan_rpm_addrs[] = {
	FAN_RPM_1_ADDR,
	FAN_RPM_2_ADDR,
};

static const uint16_t qc71_fan_pwm_addrs[] = {
	FAN_PWM_1_ADDR,
	FAN_PWM_2_ADDR,
};

static const uint16_t qc71_fan_temp_addrs[] = {
	FAN_TEMP_1_ADDR,
	FAN_TEMP_2_ADDR,
};

/* ========================================================================== */

static DEFINE_MUTEX(fan_lock);
/* Only release direct control automatically if this driver requested it. */
static bool fan_control_owned;
static bool fan_full_speed;
static bool fan_suspended;

/* ========================================================================== */

static int qc71_fan_set_auto_unlocked(void)
{
	int err;

	lockdep_assert_held(&fan_lock);

	/* Preserve the selected firmware profile and its other control bits. */
	err = ec_update_bits(FAN_CTRL_ADDR, FAN_CTRL_FAN_BOOST, 0);
	if (!err) {
		fan_control_owned = false;
		fan_full_speed = false;
	}

	return err;
}

/* 'fan_lock' must be held */
static int qc71_fan_get_mode_unlocked(void)
{
	int err;

	lockdep_assert_held(&fan_lock);

	err = ec_read_byte(CTRL_1_ADDR);
	if (err < 0)
		return err;

	if (!(err & CTRL_1_MANUAL_MODE))
		return 2; /* firmware fan control */

	err = ec_read_byte(FAN_CTRL_ADDR);
	if (err < 0)
		return err;
	if (!(err & FAN_CTRL_FAN_BOOST))
		return 2; /* firmware fan curve, including an app-selected profile */

	/* A manually selected 100% PWM remains manual mode. */
	return fan_full_speed ? 0 : 1;
}

/* ========================================================================== */

int qc71_fan_get_rpm(uint8_t fan_index)
{
	union qc71_ec_result res;
	int err;

	if (fan_index >= ARRAY_SIZE(qc71_fan_rpm_addrs))
		return -EINVAL;

	err = qc71_ec_read(qc71_fan_rpm_addrs[fan_index], &res);

	if (err)
		return err;

	return res.bytes.b1 << 8 | res.bytes.b2;
}

int qc71_fan_query_abnorm(void)
{
	int res = ec_read_byte(CTRL_1_ADDR);

	if (res < 0)
		return res;

	return !!(res & CTRL_1_FAN_ABNORMAL);
}

int qc71_fan_get_pwm(uint8_t fan_index)
{
	int err;

	if (fan_index >= ARRAY_SIZE(qc71_fan_pwm_addrs))
		return -EINVAL;

	err = ec_read_byte(qc71_fan_pwm_addrs[fan_index]);
	if (err < 0)
		return err;

	return fixp_linear_interpolate(0, 0, FAN_MAX_PWM, U8_MAX,
				       min(err, FAN_MAX_PWM));
}

int qc71_fan_set_pwm(uint8_t fan_index, unsigned int pwm)
{
	int err, restore_err;

	if (fan_index >= ARRAY_SIZE(qc71_fan_pwm_addrs) || pwm > U8_MAX)
		return -EINVAL;

	err = mutex_lock_interruptible(&fan_lock);
	if (err)
		return err;

	if (fan_suspended) {
		err = -EBUSY;
		goto out;
	}

	err = qc71_fan_get_mode_unlocked();
	if (err < 0)
		goto out;
	if (err != 1) {
		err = -EBUSY;
		goto out;
	}

	/* An I/O error may be reported after firmware has performed the write. */
	fan_control_owned = true;
	err = ec_write_byte(qc71_fan_pwm_addrs[fan_index],
			    fixp_linear_interpolate(0, 0, U8_MAX,
						    FAN_MAX_PWM, pwm));
	if (err) {
		restore_err = qc71_fan_set_auto_unlocked();
		if (restore_err)
			pr_err("failed to restore firmware fan control: %d\n",
			       restore_err);
	}
out:
	mutex_unlock(&fan_lock);
	return err;
}

int qc71_fan_get_temp(uint8_t fan_index)
{
	if (fan_index >= ARRAY_SIZE(qc71_fan_temp_addrs))
		return -EINVAL;

	return ec_read_byte(qc71_fan_temp_addrs[fan_index]);
}

int qc71_fan_get_mode(void)
{
	int err = mutex_lock_interruptible(&fan_lock);

	if (err)
		return err;

	err = qc71_fan_get_mode_unlocked();

	mutex_unlock(&fan_lock);
	return err;
}

int qc71_fan_set_mode(unsigned int mode)
{
	int err, restore_err, oldpwm[ARRAY_SIZE(qc71_fan_pwm_addrs)];
	size_t i;

	if (mode > 2)
		return -EINVAL;

	err = mutex_lock_interruptible(&fan_lock);
	if (err)
		return err;

	if (mode == 2) {
		err = qc71_fan_set_auto_unlocked();
		goto out;
	}
	if (fan_suspended) {
		err = -EBUSY;
		goto out;
	}

	/* AppIsRunning also affects power profiles; do not enable it implicitly. */
	err = ec_read_byte(CTRL_1_ADDR);
	if (err < 0)
		goto out;
	if (!(err & CTRL_1_MANUAL_MODE)) {
		err = -EBUSY;
		goto out;
	}

	for (i = 0; i < ARRAY_SIZE(qc71_fan_pwm_addrs); i++) {
		if (mode == 0) {
			oldpwm[i] = FAN_MAX_PWM;
			continue;
		}
		/* Preserve raw values: PWM -> sysfs -> PWM loses precision. */
		err = ec_read_byte(qc71_fan_pwm_addrs[i]);
		if (err < 0)
			goto out;
		oldpwm[i] = min(err, FAN_MAX_PWM);
	}

	/* Keep ownership until rollback succeeds, even for an ambiguous error. */
	fan_control_owned = true;
	err = ec_update_bits(FAN_CTRL_ADDR, FAN_CTRL_FAN_BOOST,
			     FAN_CTRL_FAN_BOOST);
	if (err)
		goto restore_auto;

	for (i = 0; i < ARRAY_SIZE(qc71_fan_pwm_addrs); i++) {
		err = ec_write_byte(qc71_fan_pwm_addrs[i], oldpwm[i]);
		if (err)
			goto restore_auto;
	}
	fan_full_speed = mode == 0;
	goto out;

restore_auto:
	restore_err = qc71_fan_set_auto_unlocked();
	if (restore_err)
		pr_err("failed to restore firmware fan control: %d\n", restore_err);

out:
	mutex_unlock(&fan_lock);
	return err;
}

int qc71_fan_release_control(void)
{
	int err = mutex_lock_interruptible(&fan_lock);

	if (err)
		return err;

	/* This explicit request restores the global firmware mode as well. */
	err = qc71_fan_set_auto_unlocked();
	if (!err)
		err = ec_update_bits(CTRL_1_ADDR, CTRL_1_MANUAL_MODE, 0);

	mutex_unlock(&fan_lock);
	return err;
}

int qc71_fan_suspend(void)
{
	int err = 0;

	mutex_lock(&fan_lock);
	/* Block new direct-control requests until the PM post notification. */
	fan_suspended = true;
	if (fan_control_owned)
		err = qc71_fan_set_auto_unlocked();
	if (err) {
		fan_suspended = false;
		pr_err("failed to restore firmware fan control before sleep: %d\n", err);
	}
	mutex_unlock(&fan_lock);
	return err;
}

void qc71_fan_resume(void)
{
	mutex_lock(&fan_lock);
	fan_suspended = false;
	mutex_unlock(&fan_lock);
}

void qc71_fan_cleanup(void)
{
	int err;

	mutex_lock(&fan_lock);
	if (fan_control_owned) {
		err = qc71_fan_set_auto_unlocked();
		if (err)
			pr_err("failed to restore firmware fan control: %d\n", err);
	}
	mutex_unlock(&fan_lock);
}
