#
# Copyright(c) 2019-2022 Intel Corporation
# SPDX-License-Identifier: BSD-3-Clause
#

import time

import pytest

from api.cas import ioclass_config, casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.os_tools import sync
from test_tools.udev import Udev
from type_def.size import Size, Unit
from tests.io_class.io_class_common import prepare, ioclass_config_path


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_process_name():
    """
    title: Test IO classification by process name.
    description: Check if data generated by process with particular name is cached.
    pass_criteria:
      - No kernel bug.
      - IO is classified properly based on process generating IO name.
    """
    ioclass_id = 1
    dd_size = Size(4, Unit.KibiByte)
    dd_count = 1
    iterations = 100

    with TestRun.step("Prepare cache and core."):
        cache, core = prepare()

    with TestRun.step("Create and load IO class config file."):
        ioclass_config.add_ioclass(
            ioclass_id=ioclass_id,
            eviction_priority=1,
            allocation="1.00",
            rule=f"process_name:dd&done",
            ioclass_config_path=ioclass_config_path,
        )
        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

    with TestRun.step("Flush cache and disable udev."):
        cache.flush_cache()
        Udev.disable()

    with TestRun.step("Check if all data generated by dd process is cached."):
        for i in range(iterations):
            (
                Dd()
                .input("/dev/zero")
                .output(core.path)
                .count(dd_count)
                .block_size(dd_size)
                .seek(i)
                .run()
            )
            sync()
            time.sleep(0.1)
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != (i + 1) * dd_count:
                TestRun.LOGGER.error(f"Wrong amount of dirty data ({dirty}).")


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_pid():
    """
    title: Test IO classification by process id.
    description: Check if data generated by process with particular id is cached.
    pass_criteria:
      - No kernel bug.
      - IO is classified properly based on process generating IO id.
    """
    ioclass_id = 1
    iterations = 20
    dd_count = 100
    dd_size = Size(4, Unit.KibiByte)

    with TestRun.step("Prepare cache, core and disable udev."):
        cache, core = prepare()
        Udev.disable()

    with TestRun.step("Prepare dd command."):
        # Since 'dd' has to be executed right after writing pid to 'ns_last_pid',
        # 'dd' command is created and is appended to 'echo' command instead of running it
        dd_command = str(
            Dd().input("/dev/zero").output(core.path).count(dd_count).block_size(dd_size)
        )

    for _ in TestRun.iteration(range(iterations)):
        with TestRun.step("Flush cache."):
            cache.flush_cache()

        with TestRun.step("Prepare and load IO class config."):
            output = TestRun.executor.run("cat /proc/sys/kernel/ns_last_pid")
            if output.exit_code != 0:
                raise Exception(
                    f"Failed to retrieve pid. stdout: {output.stdout} \n stderr :{output.stderr}"
                )

            # Few pids might be used by system during test preparation
            pid = int(output.stdout) + 50

            ioclass_config.add_ioclass(
                ioclass_id=ioclass_id,
                eviction_priority=1,
                allocation="1.00",
                rule=f"pid:eq:{pid}&done",
                ioclass_config_path=ioclass_config_path,
            )
            casadm.load_io_classes(cache.cache_id, ioclass_config_path)

        with TestRun.step(f"Run dd with pid {pid}."):
            # pid saved in 'ns_last_pid' has to be smaller by one than target dd pid
            dd_and_pid_command = (
                f"echo {pid - 1} > /proc/sys/kernel/ns_last_pid && {dd_command} "
                f"&& cat /proc/sys/kernel/ns_last_pid"
            )
            output = TestRun.executor.run(dd_and_pid_command)
            if output.exit_code != 0:
                raise Exception(
                    f"Failed to run dd with target pid. "
                    f"stdout: {output.stdout} \n stderr :{output.stderr}"
                )
            sync()
        with TestRun.step("Check if data was cached properly."):
            dirty = cache.get_io_class_statistics(io_class_id=ioclass_id).usage_stats.dirty
            if dirty.get_value(Unit.Blocks4096) != dd_count:
                TestRun.LOGGER.error(f"Wrong amount of dirty data ({dirty}).")
            ioclass_config.remove_ioclass(ioclass_id, ioclass_config_path)
