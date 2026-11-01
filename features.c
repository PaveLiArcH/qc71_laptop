// SPDX-License-Identifier: GPL-2.0
#include "pr.h"

#include <linux/ctype.h>
#include <linux/dmi.h>
#include <linux/init.h>
#include <linux/mod_devicetable.h>
#include <linux/slab.h>
#include <linux/string.h>

#include "ec.h"
#include "features.h"

/* ========================================================================== */

struct oem_string_walker_data {
	char *value;
	int index;
};

/* ========================================================================== */

static const struct dmi_system_id qc71_dmi_table[] __initconst = {
	{
		.matches = {
			DMI_MATCH(DMI_BOARD_NAME, "LAPQC71"),
			{ }
		}
	},
	{
		/* https://avell.com.br/avell-a60-muv-295765 */
		.matches = {
			DMI_EXACT_MATCH(DMI_CHASSIS_VENDOR, "Avell High Performance"),
			DMI_EXACT_MATCH(DMI_PRODUCT_NAME, "A60 MUV"),
			{ }
		}
	},
	{
		.matches = {
			DMI_EXACT_MATCH(DMI_BOARD_NAME, "LAPAC71G"),
			{ }
		}
	},
	{
		.matches = {
			DMI_EXACT_MATCH(DMI_BOARD_NAME, "LAPAC71H"),
			{ }
		}
	},
	{ }
};

/* ========================================================================== */

struct qc71_features_struct qc71_features;

/* ========================================================================== */

static void __init oem_string_walker(const struct dmi_header *dm, void *ptr)
{
	int i, count;
	const uint8_t *s;
	struct oem_string_walker_data *data = ptr;

	if (dm->type != 11 || dm->length < 5 || !IS_ERR_OR_NULL(data->value))
		return;

	count = *(uint8_t *)(dm + 1);

	if (data->index >= count)
		return;

	i = 0;
	s = ((uint8_t *)dm) + dm->length;

	while (i++ < data->index && *s)
		s += strlen(s) + 1;

	data->value = kstrdup(s, GFP_KERNEL);

	if (!data->value)
		data->value = ERR_PTR(-ENOMEM);
}

static char * __init read_oem_string(int index)
{
	struct oem_string_walker_data d = {.value = ERR_PTR(-ENOENT),
					   .index = index};
	int err = dmi_walk(oem_string_walker, &d);

	if (err) {
		if (!IS_ERR_OR_NULL(d.value))
			kfree(d.value);
		return ERR_PTR(err);
	}

	return d.value;
}

/* QCCFL357.0062.2020.0313.1530 -> 62 */
static int __pure __init parse_bios_version(const char *str)
{
	const char *p = strchr(str, '.'), *p2;
	int bios_version;

	if (!p)
		return -EINVAL;

	p2 = strchr(p + 1, '.');

	if (!p2)
		return -EINVAL;

	p += 1;
	/* Intel BIOS revisions have four digits. Reject empty/overflowing fields. */
	if (p == p2 || p2 - p > 4)
		return -EINVAL;

	bios_version = 0;

	while (p != p2) {
		if (!isdigit(*p))
			return -EINVAL;

		bios_version = 10 * bios_version + *p - '0';
		p += 1;
	}

	return bios_version;
}

static int __init check_features_ec(void)
{
	int err = ec_read_byte(SUPPORT_1_ADDR);
	int support_2;

	if (err >= 0) {
		qc71_features.super_key_lock = !!(err & SUPPORT_1_SUPER_KEY_LOCK);
		qc71_features.lightbar       = !!(err & SUPPORT_1_LIGHTBAR);
		qc71_features.fan_boost      = !!(err & SUPPORT_1_FAN_BOOST);
	} else {
		pr_warn("failed to query support_1 byte: %d\n", err);
	}

	support_2 = ec_read_byte(SUPPORT_2_ADDR);
	if (support_2 >= 0) {
		pr_info("support_2: %#04x\n", support_2);
		/* The RGB register layout is currently supported on the X15 only. */
		qc71_features.keyboard_backlight =
			qc71_is_lapac71() &&
			(support_2 & SUPPORT_2_SINGLE_ZONE_KBD);
	} else {
		pr_warn("failed to query support_2 byte: %d\n", support_2);
	}

	return err;
}

static int __init check_features_bios(void)
{
	const char *bios_version_str;
	int bios_version;
	bool x15 = qc71_is_lapac71();

	if (!dmi_check_system(qc71_dmi_table)) {
		pr_warn("no DMI match\n");
		return -ENODEV;
	}

	bios_version_str = dmi_get_system_info(DMI_BIOS_VERSION);

	if (!bios_version_str) {
		pr_warn("failed to get BIOS version DMI string\n");
		return -ENOENT;
	}

	pr_info("BIOS version string: '%s'\n", bios_version_str);

	/* ACADL and QCCFL firmware revisions are independent version series. */
	if (x15 && !str_has_prefix(bios_version_str, "ACADL357.")) {
		pr_warn("unrecognized X15 BIOS family; skipping BIOS-specific controls\n");
		return -EOPNOTSUPP;
	}

	bios_version = parse_bios_version(bios_version_str);

	if (bios_version < 0) {
		pr_warn("cannot parse BIOS version\n");
		return -EINVAL;
	}

	pr_info("BIOS version: %04d\n", bios_version);

	if (bios_version >= (x15 ? 60 : 114)) {
		const char *s = read_oem_string(18);
		size_t s_len;

		if (IS_ERR(s)) {
			pr_warn("cannot read OEM feature string: %ld\n", PTR_ERR(s));
			return PTR_ERR(s);
		}

		s_len = strlen(s);

		pr_info("OEM_STRING(18) = '%s'\n", s);

		/* if it is entirely spaces */
		if (s_len && strspn(s, " ") == s_len) {
			qc71_features.fn_lock           = true;
			qc71_features.batt_charge_limit = true;
			qc71_features.fan_extras        = true;
		} else {
			/* TODO */
			pr_warn("cannot extract supported features from OEM string\n");
		}

		kfree(s);
	}

	return 0;
}

int __init qc71_check_features(void)
{
	(void) check_features_ec();
	(void) check_features_bios();

	return 0;
}
