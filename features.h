// SPDX-License-Identifier: GPL-2.0
#ifndef QC71_FEATURES_H
#define QC71_FEATURES_H

#include <linux/dmi.h>
#include <linux/init.h>
#include <linux/types.h>

struct qc71_features_struct {
	bool super_key_lock    : 1;
	bool lightbar          : 1;
	bool keyboard_backlight : 1; /* LAPAC71G/H with EC single-zone RGB capability */
	bool fan_boost         : 1;
	bool fn_lock           : 1;
	bool batt_charge_limit : 1;
	bool fan_extras        : 1; /* duty cycle reduction, always on mode */
};

/* ========================================================================== */

extern struct qc71_features_struct qc71_features;

/* ========================================================================== */

static inline bool qc71_is_lapac71(void)
{
	return dmi_match(DMI_BOARD_NAME, "LAPAC71G") ||
	       dmi_match(DMI_BOARD_NAME, "LAPAC71H");
}

int __init qc71_check_features(void);

#endif /* QC71_FEATURES_H */
