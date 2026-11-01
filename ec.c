// SPDX-License-Identifier: GPL-2.0
#include "pr.h"

#include <linux/acpi.h>
#include <linux/compiler_types.h>
#include <linux/error-injection.h>
#include <linux/mutex.h>
#include <linux/printk.h>
#include <linux/wmi.h>

#include "ec.h"
#include "wmi.h"

/* ========================================================================== */

/* Even reads use the same EC mailbox; do not issue concurrent WMI calls. */
static DEFINE_MUTEX(ec_lock);

/* ========================================================================== */

static int qc71_ec_transaction_locked(uint16_t addr, uint16_t data,
				      union qc71_ec_result *result, bool read)
{
	uint8_t buf[] = {
		addr & 0xFF,
		addr >> 8,
		data & 0xFF,
		data >> 8,
		0,
		read ? 1 : 0,
		0,
		0,
	};
	static_assert(ARRAY_SIZE(buf) == 8);

	/* the returned ACPI_TYPE_BUFFER is 40 bytes long for some reason ... */
	__aligned(__alignof__(union acpi_object)) uint8_t output_buf[sizeof(union acpi_object) + 40] = {0};

	struct acpi_buffer input = { sizeof(buf), buf },
			   output = { sizeof(output_buf), output_buf };
	union acpi_object *obj = NULL;
	acpi_status status = AE_OK;
	int err = 0;

	status = wmi_evaluate_method(QC71_WMI_WMBC_GUID, 0,
				     QC71_WMBC_GETSETULONG_ID, &input, &output);

	if (ACPI_FAILURE(status)) {
		err = -EIO;
		goto out;
	}

	obj = output.pointer;

	if (!obj || obj->type != ACPI_TYPE_BUFFER || !obj->buffer.pointer ||
	    obj->buffer.length < sizeof(union qc71_ec_result)) {
		err = -ENODATA;
		goto out;
	}

	/* The firmware uses this value to report a failed EC transaction. */
	if (!memcmp(obj->buffer.pointer, "\xfe\xfe\xfe\xfe", 4)) {
		err = -EIO;
		goto out;
	}

	if (result)
		memcpy(result, obj->buffer.pointer, sizeof(*result));

out:
	pr_debug(
		"%s(addr=%#06x, data=%#06x, result=%c, read=%c)"
		": (%d) [%#010lx] %s"
		": [%*ph]\n",

		__func__, (unsigned int) addr, (unsigned int) data,
		result ? 'y' : 'n', read ? 'y' : 'n',
		err, (unsigned long) status, acpi_format_exception(status),
		(obj && obj->type == ACPI_TYPE_BUFFER) ?
			(int) min(sizeof(*result), (size_t) obj->buffer.length) : 0,
		(obj && obj->type == ACPI_TYPE_BUFFER) ?
			obj->buffer.pointer : NULL
	);

	return err;
}

int __must_check qc71_ec_transaction(uint16_t addr, uint16_t data,
				     union qc71_ec_result *result, bool read)
{
	int err = mutex_lock_killable(&ec_lock);

	if (err)
		return err;

	err = qc71_ec_transaction_locked(addr, data, result, read);
	mutex_unlock(&ec_lock);
	return err;
}
ALLOW_ERROR_INJECTION(qc71_ec_transaction, ERRNO);

int __must_check ec_update_bits(uint16_t addr, uint8_t mask, uint8_t value)
{
	union qc71_ec_result result;
	int err = mutex_lock_killable(&ec_lock);

	if (err)
		return err;

	err = qc71_ec_transaction_locked(addr, 0, &result, true);
	if (!err)
		err = qc71_ec_transaction_locked(addr,
			(result.bytes.b1 & ~mask) | (value & mask), NULL, false);

	mutex_unlock(&ec_lock);
	return err;
}
