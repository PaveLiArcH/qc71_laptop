#ifndef QC71_LAPTOP_FAN_H
#define QC71_LAPTOP_FAN_H

#include <linux/types.h>

#include "ec.h"

/* ========================================================================== */

#define FAN_MAX_PWM        200
#define FAN_CTRL_MAX_LEVEL   7
#define FAN_CTRL_LEVEL(level) (128 + (level))

/* ========================================================================== */

int qc71_fan_get_rpm(uint8_t fan_index);
int qc71_fan_query_abnorm(void);
int qc71_fan_get_pwm(uint8_t fan_index);
int qc71_fan_set_pwm(uint8_t fan_index, unsigned int pwm);
int qc71_fan_get_temp(uint8_t fan_index);
int qc71_fan_get_mode(void);
int qc71_fan_set_mode(unsigned int mode);
int qc71_fan_suspend(void);
void qc71_fan_resume(void);
void qc71_fan_cleanup(void);

#if IS_ENABLED(CONFIG_HWMON)
int qc71_fan_release_control(void);
#else
static inline int qc71_fan_release_control(void)
{
	int err = ec_update_bits(FAN_CTRL_ADDR, FAN_CTRL_FAN_BOOST, 0);

	if (err)
		return err;
	return ec_update_bits(CTRL_1_ADDR, CTRL_1_MANUAL_MODE, 0);
}
#endif

#endif /* QC71_LAPTOP_FAN_H */
