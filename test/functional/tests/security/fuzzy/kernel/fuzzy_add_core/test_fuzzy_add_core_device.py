#
# Copyright(c) 2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    UnalignedIo,
    KernelParameters,
    UseIoScheduler,
    CleaningPolicy,
    CacheModeTrait,
)
from api.cas.cli import add_core_cmd
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.peach_fuzzer.peach_fuzzer import PeachFuzzer
from test_tools.udev import Udev
from tests.security.fuzzy.kernel.common.common import (
    run_cmd_and_validate,
    get_device_fuzz_config,
)


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("cache_line_size", CacheLineSize)
@pytest.mark.parametrizex("cleaning_policy", CleaningPolicy)
@pytest.mark.parametrizex("unaligned_io", UnalignedIo)
@pytest.mark.parametrizex("use_io_scheduler", UseIoScheduler)
def test_fuzzy_add_core_device(
    cache_mode, cache_line_size, cleaning_policy, unaligned_io, use_io_scheduler
):
    """
    title: Fuzzy test for casadm 'add core' command – device
    description: |
        Using Peach Fuzzer check Open CAS ability of handling wrong core device in
        'add core' command.
    pass_criteria:
      - System did not crash
      - Open CAS still works.
    """

    core_id = 1

    with TestRun.step("Start cache and set appropriate cleaning policy."):
        cache_disk = TestRun.disks["cache"]
        cache = casadm.start_cache(
            cache_dev=cache_disk,
            cache_mode=cache_mode,
            cache_line_size=cache_line_size,
            cache_id=1,
            force=True,
            kernel_params=KernelParameters(unaligned_io, use_io_scheduler),
        )

        cache.set_cleaning_policy(
            cleaning_policy=(
                cleaning_policy
                if CacheModeTrait.LazyWrites in CacheMode.get_traits(cache_mode)
                else CleaningPolicy.DEFAULT
            )
        )

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step("Prepare PeachFuzzer"):
        valid_values = [
            disk.path
            for disk in TestRun.dut.disks
            if disk.path != cache_disk.path
            and disk.block_size.get_value() >= cache_disk.block_size.get_value()
        ]
        fuzz_config = get_device_fuzz_config(valid_values)
        valid_values = [path.encode("ascii") for path in valid_values]
        PeachFuzzer.generate_config(fuzz_config)
        base_cmd = add_core_cmd(
            cache_id=str(cache.cache_id), core_dev="{param}", core_id=str(core_id)
        )
        commands = PeachFuzzer.get_fuzzed_command(
            command_template=base_cmd, count=TestRun.usr.fuzzy_iter_count
        )

    for index, cmd in TestRun.iteration(
        enumerate(commands), f"Run command {TestRun.usr.fuzzy_iter_count} times"
    ):
        with TestRun.step(f"Iteration {index + 1}"):
            output = run_cmd_and_validate(
                cmd=cmd,
                value_name="Device path",
                is_valid=cmd.param in valid_values,
            )
            if output.exit_code == 0:
                with TestRun.step("Remove core"):
                    cache.remove_core(core_id=core_id)
