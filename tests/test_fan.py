#!/usr/bin/env python3
"""Run the real fan/PWM C code against an in-memory EC, without kernel privileges.

Requires Python 3 and a C compiler (CC, default: cc). Kernel headers are not needed.
The tiny kernel stubs only model these callbacks' dependencies; this verifies
software state and error handling, not EC address compatibility or physical RPM.
"""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile

STUBS = {'mutex.h': '#define DEFINE_MUTEX(x) int x\n'
            'static int mutex_lock_interruptible(int *m) { assert(*m == 0); *m=1; return 0; }\n'
            'static void mutex_lock(int *m) { assert(*m == 0); *m=1; }\n'
            'static void mutex_unlock(int *m) { assert(*m == 1); *m=0; }\n',
 'lockdep.h': '#define lockdep_assert_held(x) assert(*(x) == 1)\n',
 'printk.h': '#define pr_err(...) do { mock_errors++; } while(0)\n',
 'types.h': '#include <stdbool.h>\n#include <stdint.h>\n#include <stddef.h>\n',
 'compiler_types.h': '#define __must_check\n',
 'version.h': '#define LINUX_VERSION_CODE 0\n'
              '#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))\n',
 'device.h': '#pragma once\nstruct device { int unused; };\n',
 'init.h': '#define __init\n',
 'hwmon-sysfs.h': '',
 'sysfs.h': '',
 'platform_device.h': '#include <linux/device.h>\nstruct platform_device { struct device dev; };\n',
 'hwmon.h': '#pragma once\n'
            '#include <linux/device.h>\n'
            'typedef unsigned int u32;\n'
            'typedef unsigned short umode_t;\n'
            'enum hwmon_sensor_types { hwmon_pwm, hwmon_fan };\n'
            'enum { hwmon_pwm_input, hwmon_pwm_enable };\n'
            '#define HWMON_PWM_INPUT 1\n'
            '#define HWMON_PWM_ENABLE 2\n'
            'struct hwmon_channel_info { enum hwmon_sensor_types type; const u32 *config; };\n'
            'struct hwmon_ops {\n'
            ' umode_t (*is_visible)(const void *, enum hwmon_sensor_types, u32, int);\n'
            ' int (*read)(struct device *, enum hwmon_sensor_types, u32, int, long *);\n'
            ' int (*write)(struct device *, enum hwmon_sensor_types, u32, int, long);\n'
            '};\n'
            'struct hwmon_chip_info { const struct hwmon_ops *ops; const struct hwmon_channel_info '
            '**info; };\n'
            '#define HWMON_CHANNEL_INFO(stype, ...) (&(const struct hwmon_channel_info){ .type = '
            'hwmon_##stype, .config = (const u32[]){ __VA_ARGS__, 0 } })\n'
            'static struct device mock_hwmon_device;\n'
            'static inline struct device *hwmon_device_register_with_info(struct device *dev, '
            'const char *name, void *data, const struct hwmon_chip_info *chip, void *extra) { '
            'return &mock_hwmon_device; }\n'
            'static inline void hwmon_device_unregister(struct device *dev) {}\n'
            '#define IS_ERR(ptr) ((uintptr_t)(ptr) > (uintptr_t)-4096)\n'
            '#define IS_ERR_OR_NULL(ptr) (!(ptr) || IS_ERR(ptr))\n'
            '#define PTR_ERR(ptr) ((intptr_t)(ptr))\n',
 'dmi.h': 'enum { DMI_BOARD_NAME };\n'
          'static const char *mock_board = "LAPAC71G";\n'
          'static inline bool dmi_match(int field, const char *value) { return '
          'strcmp(mock_board,value)==0; }\n',
 'moduleparam.h': '#define module_param(...)\n#define MODULE_PARM_DESC(...)\n'}

SOURCE = r'''

#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)<<(l)) & ((~0U)>>(31-(h))))
#define U8_MAX 255
#define min(a,b) ((a)<(b)?(a):(b))
#define CONFIG_HWMON 1
#define IS_ENABLED(x) (x)
static int mock_errors;
#define KBUILD_MODNAME "qc71_laptop"
#define KBUILD_BASENAME "fan_test"
#include "fan.c"
#include "hwmon_pwm.c"
struct qc71_features_struct qc71_features;
static struct platform_device mock_platform;
struct platform_device *qc71_platform_dev = &mock_platform;
static uint8_t regs[65536];
static int writes, reads, fail_write_addr=-1, fail_read_addr=-1, fail_after_addr=-1;
static bool fail_rollback_read;
int qc71_ec_transaction(uint16_t addr, uint16_t data, union qc71_ec_result *r, bool read) {
 if (read) {
  reads++;
  if (addr==fail_read_addr) {fail_read_addr=-1; return -EIO;}
  r->dword=0; r->bytes.b1=regs[addr]; r->bytes.b2=regs[(uint16_t)(addr+1)];
 } else {
  writes++;
  if (addr==fail_write_addr) {fail_write_addr=-1; return -EIO;}
  regs[addr]=data;
  if (addr==fail_after_addr) {
   fail_after_addr=-1;
   if (fail_rollback_read) { fail_read_addr=FAN_CTRL_ADDR; fail_rollback_read=false; }
   return -EIO;
  }
 }
 return 0;
}
int ec_update_bits(uint16_t addr,uint8_t mask,uint8_t value) {
 int r=ec_read_byte(addr); if(r<0) return r;
 uint8_t n=(r&~mask)|(value&mask);
 return r==n ? 0 : ec_write_byte(addr,n);
}
static void reset(void) {
 assert(fan_lock==0);
 memset(regs,0,sizeof(regs)); reads=writes=mock_errors=0;
 fail_read_addr=fail_write_addr=fail_after_addr=-1; fail_rollback_read=false;
 fan_control_owned=fan_full_speed=fan_suspended=false;
 fan_control=false; qc71_features.fan_boost=false; mock_board="LAPAC71G";
 regs[CTRL_1_ADDR]=0x09;
 regs[FAN_CTRL_ADDR]=0x91;
 regs[FAN_PWM_1_ADDR]=51; regs[FAN_PWM_2_ADDR]=77;
}
int main(void) {
 reset();
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_input,0,-1)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_input,0,256)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_input,0,LONG_MAX)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_enable,0,-1)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_enable,0,3)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_enable,0,256)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_enable,0,LONG_MAX)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_input,256,170)==-EINVAL);
 assert(qc71_hwmon_pwm_write(NULL,hwmon_pwm,hwmon_pwm_input,-256,170)==-EINVAL);
 assert(qc71_hwmon_pwm_is_visible(NULL,hwmon_pwm,hwmon_pwm_input,1)==0644);
 assert(qc71_hwmon_pwm_is_visible(NULL,hwmon_pwm,hwmon_pwm_enable,1)==0);
 assert(qc71_hwmon_pwm_is_visible(NULL,hwmon_fan,hwmon_pwm_enable,0)==0);
 assert(qc71_fan_set_mode(256)==-EINVAL);
 assert(qc71_fan_set_mode(UINT_MAX)==-EINVAL);
 assert(qc71_fan_set_pwm(0,256)==-EINVAL);
 assert(qc71_fan_set_pwm(2,170)==-EINVAL);
 assert(writes==0 && reads==0);
 regs[CTRL_1_ADDR]=8;
 assert(qc71_fan_get_mode()==2);
 assert(qc71_fan_set_mode(1)==-EBUSY);
 assert(qc71_fan_set_pwm(0,170)==-EBUSY);
 assert(writes==0);
 reset();
 assert(qc71_fan_set_mode(1)==0);
 assert(regs[FAN_CTRL_ADDR]==0xd1 && regs[CTRL_1_ADDR]==0x09);
 assert(regs[FAN_PWM_1_ADDR]==51 && regs[FAN_PWM_2_ADDR]==77);
 assert(qc71_fan_get_mode()==1);
 assert(qc71_fan_set_pwm(0,128)==0 && regs[FAN_PWM_1_ADDR]==100);
 assert(qc71_fan_set_pwm(0,255)==0 && regs[FAN_PWM_1_ADDR]==200);
 assert(qc71_fan_set_pwm(1,255)==0 && regs[FAN_PWM_2_ADDR]==200);
 assert(qc71_fan_get_mode()==1);
 assert(qc71_fan_set_mode(0)==0);
 assert(regs[FAN_PWM_1_ADDR]==200 && regs[FAN_PWM_2_ADDR]==200);
 assert(qc71_fan_get_mode()==0);
 assert(qc71_fan_set_pwm(0,170)==-EBUSY);
 assert(qc71_fan_set_mode(1)==0 && qc71_fan_get_mode()==1);
 assert(qc71_fan_set_pwm(0,170)==0 && regs[FAN_PWM_1_ADDR]==133);
 assert(qc71_fan_set_mode(2)==0 && qc71_fan_get_mode()==2);
 assert(regs[FAN_CTRL_ADDR]==0x91 && regs[CTRL_1_ADDR]==0x09);
 assert(qc71_fan_set_mode(1)==0);
 assert(qc71_fan_release_control()==0);
 assert(regs[FAN_CTRL_ADDR]==0x91 && regs[CTRL_1_ADDR]==0x08);
 reset(); fail_write_addr=FAN_PWM_2_ADDR;
 assert(qc71_fan_set_mode(1)==-EIO);
 assert(regs[FAN_CTRL_ADDR]==0x91 && !fan_control_owned);
 reset(); assert(qc71_fan_set_mode(1)==0);
 fail_write_addr=FAN_PWM_1_ADDR;
 assert(qc71_fan_set_pwm(0,200)==-EIO);
 assert(regs[FAN_CTRL_ADDR]==0x91 && !fan_control_owned);
 reset(); qc71_fan_cleanup(); assert(writes==0);
 assert(qc71_fan_set_mode(1)==0); qc71_fan_cleanup();
 assert(regs[FAN_CTRL_ADDR]==0x91 && regs[CTRL_1_ADDR]==0x09);
 reset(); regs[FAN_PWM_1_ADDR]=255; assert(qc71_fan_get_pwm(0)==255);
 regs[FAN_RPM_1_ADDR]=0x12; regs[FAN_RPM_1_ADDR+1]=0x34;
 assert(qc71_fan_get_rpm(0)==0x1234);
 reset(); assert(qc71_fan_set_mode(1)==0);
 fail_write_addr=FAN_CTRL_ADDR;
 assert(qc71_fan_release_control()==-EIO && regs[CTRL_1_ADDR]==0x09);
 reset(); fail_read_addr=FAN_PWM_2_ADDR;
 assert(qc71_fan_set_mode(1)==-EIO && writes==0);
 reset(); fail_after_addr=FAN_CTRL_ADDR;
 assert(qc71_fan_set_mode(1)==-EIO);
 assert(regs[FAN_CTRL_ADDR]==0x91 && !fan_control_owned);
 reset(); fail_after_addr=FAN_CTRL_ADDR; fail_rollback_read=true;
 assert(qc71_fan_set_mode(1)==-EIO);
 assert(regs[FAN_CTRL_ADDR]==0xd1 && fan_control_owned && mock_errors==1);
 qc71_fan_cleanup(); assert(regs[FAN_CTRL_ADDR]==0x91 && !fan_control_owned);
 reset(); fail_after_addr=FAN_PWM_2_ADDR;
 assert(qc71_fan_set_mode(0)==-EIO);
 assert(regs[FAN_PWM_1_ADDR]==200 && regs[FAN_PWM_2_ADDR]==200);
 assert(regs[FAN_CTRL_ADDR]==0x91 && !fan_control_owned);
 reset(); regs[FAN_CTRL_ADDR]=0xd1;
 fail_after_addr=FAN_PWM_1_ADDR; fail_rollback_read=true;
 assert(qc71_fan_set_pwm(0,255)==-EIO);
 assert(regs[FAN_PWM_1_ADDR]==200 && fan_control_owned && mock_errors==1);
 qc71_fan_cleanup(); assert(regs[FAN_CTRL_ADDR]==0x91 && !fan_control_owned);
 reset(); assert(qc71_fan_set_mode(1)==0);
 assert(qc71_fan_suspend()==0 && fan_suspended);
 assert(qc71_fan_get_mode()==2 && regs[CTRL_1_ADDR]==0x09);
 int sleep_reads=reads, sleep_writes=writes;
 assert(qc71_fan_set_mode(0)==-EBUSY && qc71_fan_set_mode(1)==-EBUSY);
 assert(qc71_fan_set_pwm(0,230)==-EBUSY);
 assert(reads==sleep_reads && writes==sleep_writes);
 assert(qc71_fan_set_mode(2)==0);
 sleep_writes=writes;
 qc71_fan_resume();
 assert(!fan_suspended && writes==sleep_writes && qc71_fan_get_mode()==2);
 assert(qc71_fan_set_mode(1)==0);
 fail_write_addr=FAN_CTRL_ADDR;
 assert(qc71_fan_suspend()==-EIO && !fan_suspended && fan_control_owned);
 assert(mock_errors==1);
 qc71_fan_cleanup(); assert(qc71_fan_get_mode()==2);
 reset();
 assert(qc71_hwmon_pwm_setup()==-ENODEV);
 fan_control=true;
 mock_board="LAPAC71G";
 assert(qc71_hwmon_pwm_setup()==0 && reads==0 && writes==0);
 qc71_hwmon_pwm_cleanup();
 mock_board="LAPAC71G-other";
 assert(qc71_hwmon_pwm_setup()==-ENODEV);
 mock_board="LAPQC71A";
 assert(qc71_hwmon_pwm_setup()==-ENODEV);
 fan_control=false; qc71_features.fan_boost=true;
 assert(qc71_hwmon_pwm_setup()==0 && reads==0 && writes==0);
 qc71_hwmon_pwm_cleanup();
 puts("PASS: PM blocks manual control without replay on resume, capability/board opt-in gates, hwmon long boundaries and visibility, fan state, both channels, 100% scaling, range validation, explicit firmware restore, ownership cleanup and EC failure rollback (including errors after writes)");
}
'''


def main():
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="qc71-fan-tests-") as directory:
        temporary = Path(directory)
        include = temporary / "include" / "linux"
        include.mkdir(parents=True)
        for name, contents in STUBS.items():
            (include / name).write_text("#pragma once\n" + contents)
        source = temporary / "fan_test.c"
        source.write_text(SOURCE)
        executable = temporary / "fan_test"
        compiler = shlex.split(os.environ.get("CC", "cc"))
        subprocess.run(compiler + [
            "-std=gnu11", "-Wall", "-Wextra", "-Werror",
            "-Wno-unused-parameter", "-I", str(include.parent),
            "-iquote", str(project), str(source), "-o", str(executable),
        ], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
