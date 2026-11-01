// SPDX-License-Identifier: GPL-2.0
#include "pr.h"

#include <linux/debugfs.h>
#include <linux/init.h>
#include <linux/moduleparam.h>
#include <linux/uaccess.h>
#include <linux/sched/signal.h>
#include <linux/types.h>

#include "debugfs.h"
#include "ec.h"

#if IS_ENABLED(CONFIG_DEBUG_FS)

#define DEBUGFS_DIR_NAME KBUILD_MODNAME

static const struct qc71_debugfs_attr {
	const char *name;
	uint16_t addr;
} qc71_debugfs_attrs[] = {
	{"1108", 1108},

	{"ap_bios_byte",     AP_BIOS_BYTE_ADDR},

	{"batt_alert",       BATT_ALERT_ADDR},
	{"batt_charge_ctrl", BATT_CHARGE_CTRL_ADDR},
	{"batt_status",      BATT_STATUS_ADDR},
	{"batt_temp",        BATT_TEMP_ADDR},
	{"bios_ctrl_1",      BIOS_CTRL_1_ADDR},
	{"bios_ctrl_2",      BIOS_CTRL_2_ADDR},
	{"bios_ctrl_3",      BIOS_CTRL_3_ADDR},
	{"bios_info_1",      BIOS_INFO_1_ADDR},
	{"bios_info_5",      BIOS_INFO_5_ADDR},

	{"ctrl_1",           CTRL_1_ADDR},
	{"ctrl_2",           CTRL_2_ADDR},
	{"ctrl_3",           CTRL_3_ADDR},
	{"ctrl_4",           CTRL_4_ADDR},
	{"ctrl_5",           CTRL_5_ADDR},
	{"ctrl_6",           CTRL_6_ADDR},

	{"device_status",    DEVICE_STATUS_ADDR},

	{"fan_ctrl",         FAN_CTRL_ADDR},
	{"fan_mode_index",   FAN_MODE_INDEX_ADDR},
	{"fan_temp_1",       FAN_TEMP_1_ADDR},
	{"fan_temp_2",       FAN_TEMP_2_ADDR},
	{"fan_pwm_1",        FAN_PWM_1_ADDR},
	{"fan_pwm_2",        FAN_PWM_2_ADDR},

	/* setting these don't seem to work */
	{"fan_l1_pwm",       ADDR(0x07, 0x43)},
	{"fan_l2_pwm",       ADDR(0x07, 0x44)},
	{"fan_l3_pwm",       ADDR(0x07, 0x45)},
	/* seemingly there is another level here, fan_ctrl=0x84, pwm=0x5a */
	{"fan_l4_pwm",       ADDR(0x07, 0x46)},
	{"fan_l5_pwm",       ADDR(0x07, 0x47)}, /* this is seemingly ignored, fan_ctrl=0x86, pwm=0xb4 */

	{"fan_l1_pwm_default", ADDR(0x07, 0x86)},
	{"fan_l2_pwm_default", ADDR(0x07, 0x87)},
	{"fan_l3_pwm_default", ADDR(0x07, 0x88)},
	{"fan_l4_pwm_default", ADDR(0x07, 0x89)},
	{"fan_l5_pwm_default", ADDR(0x07, 0x8A)},

	/* these don't seem to work */
	{"fan_min_speed",   1950},
	{"fan_min_temp",    1951},
	{"fan_extra_speed", 1952},

	{"lightbar_ctrl",    LIGHTBAR_CTRL_ADDR},
	{"lightbar_red",     LIGHTBAR_RED_ADDR},
	{"lightbar_green",   LIGHTBAR_GREEN_ADDR},
	{"lightbar_blue",    LIGHTBAR_BLUE_ADDR},

	{"keyboard_type",    KEYBOARD_TYPE_ADDR},

	{"support_1",        SUPPORT_1_ADDR},
	{"support_2",        SUPPORT_2_ADDR},
	{"support_5",        SUPPORT_5_ADDR},
	{"status_1",         STATUS_1_ADDR},

	{"platform_id",      PLATFORM_ID_ADDR},
	{"power_source",     POWER_SOURCE_ADDR},
	{"project_id",       PROJ_ID_ADDR},
	{"power_status",     POWER_STATUS_ADDR},
	{"pl_1",             PL1_ADDR},
	{"pl_2",             PL2_ADDR},
	{"pl_4",             PL4_ADDR},

	{"trigger_1",        TRIGGER_1_ADDR},
	{"trigger_2",        TRIGGER_2_ADDR},

	{"ADDR_BAT_POWER_UNIT_BYTE1", ADDR(0x04, 0x00)},
	{"ADDR_BAT_POWER_UNIT_BYTE2", ADDR(0x04, 0x01)},
	{"ADDR_BAT_DESIGN_CAPACITY_BYTE1", ADDR(0x04, 0x02)},
	{"ADDR_BAT_DESIGN_CAPACITY_BYTE2", ADDR(0x04, 0x03)},
	{"ADDR_BAT_LAST_FULL_CHARGE_CAPACITY_BYTE1", ADDR(0x04, 0x04)},
	{"ADDR_BAT_LAST_FULL_CHARGE_CAPACITY_BYTE2", ADDR(0x04, 0x05)},
	{"ADDR_BAT_DESIGN_VOL_BYTE1", ADDR(0x04, 0x08)},
	{"ADDR_BAT_DESIGN_VOL_BYTE2", ADDR(0x04, 0x09)},
	{"ADDR_BAT_STATE_BYTE1", ADDR(0x04, 0x32)},
	{"ADDR_BAT_STATE_BYTE2", ADDR(0x04, 0x33)},
	{"ADDR_BAT_CURRENT_BYTE1", ADDR(0x04, 0x34)},
	{"ADDR_BAT_CURRENT_BYTE2", ADDR(0x04, 0x35)},
	{"ADDR_BAT_REMAINING_CAPACITY_BYTE1", ADDR(0x04, 0x36)},
	{"ADDR_BAT_REMAINING_CAPACITY_BYTE2", ADDR(0x04, 0x37)},
	{"ADDR_BAT_VOLTAGE_BYTE1", ADDR(0x04, 0x38)},
	{"ADDR_BAT_VOLTAGE_BYTE2", ADDR(0x04, 0x39)},
	{"ADDR_EC_CPU_TEMPERATURE", ADDR(0x04, 0x3e)},
	{"ADDR_EC_APC_WATT", ADDR(0x04, 0x4c)},
	{"ADDR_EC_GPU_TEMPERATURE", ADDR(0x04, 0x4f)},
	{"ADDR_EC_MAIN_FAN_RPM_BYTE1", ADDR(0x04, 0x64)},
	{"ADDR_EC_MAIN_FAN_RPM_BYTE2", ADDR(0x04, 0x65)},
	{"ADDR_EC_BIOS_INFO5", ADDR(0x04, 0x66)},
	{"ADDR_EC_SECOND_FAN_RPM_BYTE1", ADDR(0x04, 0x6c)},
	{"ADDR_EC_SECOND_FAN_RPM_BYTE2", ADDR(0x04, 0x6d)},
	{"ADDR_BATTERY_ALERT_BYTE", ADDR(0x04, 0x94)},
	{"ADDR_EC_BT1CycleCount_BYTE1", ADDR(0x04, 0xa6)},
	{"ADDR_EC_BT1CycleCount_BYTE2", ADDR(0x04, 0xa7)},
	{"ADDR_PSYS_PL1_VALUE_BYTE1", ADDR(0x07, 0x20)},
	{"ADDR_PSYS_PL1_VALUE_BYTE2", ADDR(0x07, 0x21)},
	{"ADDR_GPU_PL1_SETTING_VALUE", ADDR(0x07, 0x2d)},
	{"ADDR_GPU_PL2_SETTING_VALUE", ADDR(0x07, 0x2e)},
	{"ADDR_MODE0_PL1_DEFAULT_VALUE", ADDR(0x07, 0x30)},
	{"ADDR_MODE0_PL2_DEFAULT_VALUE", ADDR(0x07, 0x31)},
	{"ADDR_MODE0_PL4_DEFAULT_VALUE", ADDR(0x07, 0x32)},
	{"ADDR_MODE0_DState_DEFAULT_VALUE", ADDR(0x07, 0x33)},
	{"ADDR_MODE1_PL1_DEFAULT_VALUE", ADDR(0x07, 0x34)},
	{"ADDR_MODE1_PL2_DEFAULT_VALUE", ADDR(0x07, 0x35)},
	{"ADDR_MODE1_PL4_DEFAULT_VALUE", ADDR(0x07, 0x36)},
	{"ADDR_MODE1_DState_DEFAULT_VALUE", ADDR(0x07, 0x37)},
	{"ADDR_EC_MAIN_FAN_DUTY", ADDR(0x07, 0x5b)},
	{"ADDR_EC_SECOND_FAN_DUTY", ADDR(0x07, 0x5c)},
	{"ADDR_TRIGGER_BYTE", ADDR(0x07, 0x67)},
	{"ADDR_RGBKB_LEVEL_R", ADDR(0x07, 0x69)},
	{"ADDR_RGBKB_LEVEL_G", ADDR(0x07, 0x6a)},
	{"ADDR_RGBKB_LEVEL_B", ADDR(0x07, 0x6b)},
	{"ADDR_RGBKBDC_LEVEL_R", ADDR(0x07, 0xec)},
	{"ADDR_RGBKBDC_LEVEL_G", ADDR(0x07, 0xed)},
	{"ADDR_RGBKBDC_LEVEL_B", ADDR(0x07, 0xee)},
	{"ADDR_RGBKB_LEVEL_DEFAULT_R", ADDR(0x07, 0x6c)},
	{"ADDR_RGBKB_LEVEL_DEFAULT_G", ADDR(0x07, 0x6d)},
	{"ADDR_RGBKB_LEVEL_DEFAULT_B", ADDR(0x07, 0x6e)},
	{"ADDR_MODE2_PL1_DEFAULT_VALUE", ADDR(0x07, 0xa7)},
	{"ADDR_MODE2_PL2_DEFAULT_VALUE", ADDR(0x07, 0xa8)},
	{"ADDR_MODE2_PL4_DEFAULT_VALUE", ADDR(0x07, 0xa9)},
	{"ADDR_MODE2_DState_DEFAULT_VALUE", ADDR(0x07, 0xaa)},
	{"MEZone_2n1p_ID_BYTE", ADDR(0x07, 0x3c)},
	{"ADDR_NV_OC_CONTROL_BYTE", ADDR(0x07, 0x43)},
	{"ADDR_NV_OC_CTGP_BYTE", ADDR(0x07, 0x44)},
	{"ADDR_NV_OC_CPU_POWER_TARGET_BYTE", ADDR(0x07, 0x45)},
	{"ADDR_NV_OC_MAXTGP_BYTE", ADDR(0x07, 0x46)},
	{"ADDR_LIGHTBAR_CONTROL_BYTE", ADDR(0x07, 0x48)},
	{"ADDR_REDBAR_CONTROL_BYTE", ADDR(0x07, 0x49)},
	{"ADDR_GREENBAR_CONTROL_BYTE", ADDR(0x07, 0x4a)},
	{"ADDR_BLUEBAR_CONTROL_BYTE", ADDR(0x07, 0x4b)},
	{"ADDR_SWITCH_TRIGGER_BYTE", ADDR(0x07, 0x67)},
	{"ADDR_SWITCH_STATUS_BYTE", ADDR(0x07, 0x68)},
	{"ADDR_PL1_SETTING_VALUE", ADDR(0x07, 0x83)},
	{"ADDR_PL2_SETTING_VALUE", ADDR(0x07, 0x84)},
	{"ADDR_PL4_SETTING_VALUE", ADDR(0x07, 0x85)},
	{"ADDR_TCC_OFFSET", ADDR(0x07, 0x86)},
	{"ADDR_L1_PWM_DEFAULT_MYFAN3", ADDR(0x07, 0x86)},
	{"ADDR_L2_PWM_DEFAULT_MYFAN3", ADDR(0x07, 0x87)},
	{"ADDR_L3_PWM_DEFAULT_MYFAN3", ADDR(0x07, 0x88)},
	{"ADDR_L4_PWM_DEFAULT_MYFAN3", ADDR(0x07, 0x89)},
	{"ADDR_L5_PWM_DEFAULT_MYFAN3", ADDR(0x07, 0x8a)},
	{"ADDR_MYFAN3_GPU_SETTING", ADDR(0x07, 0x8b)},
	{"ADDR_MYFAN3_CPU_TAU", ADDR(0x07, 0x38)},
	{"ADDR_AP_PROJECT_ID", ADDR(0x07, 0x40)},
	{"ADDR_AP_OEM_BYTE", ADDR(0x07, 0x41)},
	{"ADDR_BIOS_OEM_BYTE", ADDR(0x07, 0x4e)},
	{"ADDR_MAFAN_CONTROL_BYTE", ADDR(0x07, 0x51)},
	{"ADDR_BIOS_OEM_BYTE2", ADDR(0x07, 0x82)},
	{"ADDR_INTELAC_AC_SINGLEBL_ENABLE", ADDR(0x07, 0xea)},
	{"ADDR_INTELAC_DC_SINGLEBL_ENABLE", ADDR(0x07, 0xeb)},
	{"ADDR_AP_OEM_BYTE7", ADDR(0x07, 0xc7)},
	{"ADDR_INTELAC_TIMTER_ENABLE", ADDR(0x07, 0xc7)},
	{"ADDR_SINGLEKBL_ENABLE", ADDR(0x07, 0x8c)},
	{"ADDR_SINGLEKBL_SUPPORTPOWER", ADDR(0x07, 0x8e)},
	{"ADDR_MYFANI_MIN_SPEED", ADDR(0x07, 0x9e)},
	{"ADDR_MYFANI_MIN_TEMP", ADDR(0x07, 0x9f)},
	{"ADDR_MYFANI_EXTRA_SPEED", ADDR(0x07, 0xa0)},
	{"ADDR_BIOS_OEM_BYTE3", ADDR(0x07, 0xa3)},
	{"ADDR_AP_OEM_BYTE3", ADDR(0x07, 0xa5)},
	{"ADDR_AP_BIOS_BYTE", ADDR(0x07, 0xa4)},
	{"ADDR_AP_OEM_BYTE4", ADDR(0x07, 0xa6)},
	{"ADDR_BATTERYSAVER_PL1_DEFAULT_VALUE", ADDR(0x07, 0xa7)},
	{"ADDR_BATTERYSAVER_PL2_DEFAULT_VALUE", ADDR(0x07, 0xa8)},
	{"ADDR_BATTERYSAVER_PL4_DEFAULT_VALUE", ADDR(0x07, 0xa9)},
	{"ADDR_BATTERYSAVER_D_DEFAULT_VALUE", ADDR(0x07, 0xaa)},
	{"ADDR_MyFanCCI_Mode_Index", ADDR(0x07, 0xab)},
	{"ADDR_MyFanCCI_Mode_Profile1", ADDR(0x07, 0xb0)},
	{"ADDR_MyFanCCI_Mode_Profile2", ADDR(0x07, 0xb1)},
	{"ADDR_MyFanCCI_Mode_Profile3", ADDR(0x07, 0xb2)},
	{"ADDR_ChargingLimit", ADDR(0x07, 0xb9)},
	{"ADDR_AP_OEM_BYTE6", ADDR(0x07, 0xc6)},
	{"ADDR_COMPLEX_POWER_STATUS", ADDR(0x07, 0xcc)},
	{"ADDR_TYPEC_ADAPTER1_POWER", ADDR(0x07, 0xcd)},
	{"ADDR_TYPEC_ADAPTER2_POWER", ADDR(0x07, 0xce)},
	{"ADDR_SECOND_CHARGE_RATE_START_TIME_H", ADDR(0x07, 0xdc)},
	{"ADDR_SECOND_CHARGE_RATE_START_TIME_L", ADDR(0x07, 0xdd)},
	{"ADDR_SECOND_CHARGE_RATE_END_TIME_H", ADDR(0x07, 0xde)},
	{"ADDR_SECOND_CHARGE_RATE_END_TIME_L", ADDR(0x07, 0xdf)},
	{"ADDR_SECOND_CHARGE_RATE", ADDR(0x07, 0xe0)},
	{"ADDR_FIRST_CHARGE_RATE", ADDR(0x07, 0xe1)},
	{"ADDR_GPU_MOUDLE_ID", ADDR(0x07, 0xd3)},
	{"ADDR_RamFan_Load_Magic1", ADDR(0x0f, 0x5d)},
	{"ADDR_RamFan_Load_Magic2", ADDR(0x0f, 0x5e)},
	{"ADDR_RamFan_Mode", ADDR(0x0f, 0x5f)},
};

/* ========================================================================== */

static bool debugregs;
module_param(debugregs, bool, 0444);
MODULE_PARM_DESC(debugregs, "expose various EC registers in debugfs (default=false)");

static struct dentry *qc71_debugfs_dir,
		     *qc71_debugfs_regs_dir;

/* ========================================================================== */

static int get_debugfs_byte(void *data, u64 *value)
{
	const struct qc71_debugfs_attr *attr = data;
	int status = ec_read_byte(attr->addr);

	if (status < 0)
		return status;

	*value = status;

	return 0;
}

static int set_debugfs_byte(void *data, u64 value)
{
	const struct qc71_debugfs_attr *attr = data;
	int status;

	if (value > U8_MAX)
		return -EINVAL;

	status = ec_write_byte(attr->addr, (uint8_t) value);

	if (status < 0)
		return status;

	return status;
}

DEFINE_DEBUGFS_ATTRIBUTE(qc71_debugfs_fops, get_debugfs_byte, set_debugfs_byte, "0x%02llx\n");

/* ========================================================================== */

static ssize_t qc71_debugfs_ec_read(struct file *f, char __user *buf, size_t count, loff_t *offset)
{
	size_t i;

	for (i = 0; *offset + i < U16_MAX && i < count; i++) {
		int err = ec_read_byte(*offset + i);
		u8 byte;

		if (signal_pending(current))
			return -EINTR;

		if (err < 0) {
			if (i)
				break;

			return err;
		}

		byte = err;

		if (put_user(byte, buf + i))
			return -EFAULT;
	}

	*offset += i;

	return i;
}

static ssize_t qc71_debugfs_ec_write(struct file *f, const char __user *buf, size_t count, loff_t *offset)
{
	size_t i;

	for (i = 0; *offset + i < U16_MAX && i < count; i++) {
		int err;
		u8 byte;

		if (get_user(byte, buf + i))
			return -EFAULT;

		err = ec_write_byte(*offset + i, byte);
		if (err) {
			if (i)
				break;

			return err;
		}

		if (signal_pending(current))
			return -EINTR;
	}

	*offset += i;

	return i;
}

static const struct file_operations qc71_debugfs_ec_fops = {
	.owner = THIS_MODULE,
	.open = simple_open,
	.read = qc71_debugfs_ec_read,
	.write = qc71_debugfs_ec_write,
	.llseek = default_llseek,
};

/* ========================================================================== */

int __init qc71_debugfs_setup(void)
{
	struct dentry *d;
	int err = 0;
	size_t i;

	if (!debugregs)
		return -ENODEV;

	qc71_debugfs_dir = debugfs_create_dir(DEBUGFS_DIR_NAME, NULL);
	if (IS_ERR(qc71_debugfs_dir)) {
		err = PTR_ERR(qc71_debugfs_dir);
		goto out_error;
	}

	qc71_debugfs_regs_dir = debugfs_create_dir("regs", qc71_debugfs_dir);
	if (IS_ERR(qc71_debugfs_regs_dir)) {
		err = PTR_ERR(qc71_debugfs_regs_dir);
		goto out_error_remove_dir;
	}

	for (i = 0; i < ARRAY_SIZE(qc71_debugfs_attrs); i++) {
		const struct qc71_debugfs_attr *attr = &qc71_debugfs_attrs[i];

		d = debugfs_create_file(attr->name, 0600, qc71_debugfs_regs_dir,
					(void *) attr, &qc71_debugfs_fops);
		if (IS_ERR(d)) {
			err = PTR_ERR(d);
			goto out_error_remove_dir;
		}
	}

	debugfs_create_file_size("ec", 0600, qc71_debugfs_dir, NULL, &qc71_debugfs_ec_fops, U16_MAX);

	return 0;

out_error_remove_dir:
	debugfs_remove_recursive(qc71_debugfs_dir);
out_error:
	return err;
}

void qc71_debugfs_cleanup(void)
{
	/* checks if IS_ERR_OR_NULL() */
	debugfs_remove_recursive(qc71_debugfs_dir);
}

#endif
