#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest
import math
from api.cas import casadm
from api.cas.cache_config import (
    CacheMode,
    CacheLineSize,
    SeqCutOffPolicy,
    CleaningPolicy,
    CacheStatus,
    CacheModeTrait,
)

from core.test_run import TestRun
from storage_devices.disk import DiskTypeSet, DiskType, DiskTypeLowerThan
from test_tools.device_mapper import DmTable
from storage_devices.error_device import ErrorDevice
from test_tools.fio.fio import Fio
from test_tools.fio.fio_param import ReadWrite, IoEngine, ErrorFilter, VerifyMethod
from test_tools.udev import Udev
from type_def.size import Size, Unit

start_size = Size(512, Unit.Byte)
stop_size = Size(128, Unit.KibiByte)


@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex(
    "block_size", [start_size, Size(1024, Unit.Byte), Size(4, Unit.KibiByte), stop_size]
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cache_insert_error(cache_mode, block_size):
    """
    title: Cache insert test with error device
    description: |
      Validate CAS ability to handle write errors while it tries to insert
      cache lines. For lazy writes cache modes (WO, WB) issue only reads.
    pass_criteria:
      - No I/O errors returned to the user
      - Cache write error statistics are counted properly
      - No cache line gets inserted into cache
    """
    cache_line_size = CacheLineSize.DEFAULT
    with TestRun.step("Prepare core and cache"):
        cache, core, core_device = prepare_configuration(cache_mode, cache_line_size)

    fio_cmd = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .size(core.size)
        .block_size(block_size)
        .target(core)
        .direct()
    )
    if cache_mode in CacheMode.with_traits(CacheModeTrait.LazyWrites):
        fio_cmd = fio_cmd.read_write(ReadWrite.randread)
    else:
        fio_cmd = fio_cmd.read_write(ReadWrite.randrw)

    with TestRun.step("Run fio and verify no errors present"):
        fio_errors = fio_cmd.run()[0].total_errors()

        if fio_errors != 0:
            TestRun.fail(f"Some I/O ended with errors {fio_errors}")

    with TestRun.step("Check error statistics on cache"):
        stats = cache.get_statistics()

        occupancy = cache.get_occupancy().get_value()
        if occupancy != 0:
            TestRun.fail(f"Occupancy is not zero, but {occupancy}")

        # Convert cache writes from bytes to I/O count.
        # Cache errors are accounted with request granularity.
        # Blocks are expressed with 4k granularity.
        correction = int(math.ceil(Size(1, Unit.Blocks4096) / block_size))
        cache_writes_upper = int(stats.block_stats.cache.writes / block_size)
        cache_writes_lower = cache_writes_upper - correction + 1
        cache_errors = stats.error_stats.cache.total

        if not cache_writes_lower <= cache_errors <= cache_writes_upper:
            TestRun.fail(
                f"Cache errors ({cache_errors}) should equal to number of"
                f" requests to cache (range {cache_writes_lower}-{cache_writes_upper})"
            )

    if cache_mode not in CacheMode.with_traits(CacheModeTrait.LazyWrites):
        with TestRun.step("Verify core device contents for non-lazy-writes cache modes"):
            cache.stop()

            fio_cmd.target(core_device).verify_only().run()


@pytest.mark.parametrizex("cache_mode", CacheMode.without_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex("block_size", [start_size, Size(4, Unit.KibiByte), stop_size])
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_error_cache_verify_core(cache_mode, block_size):
    """
    title: Write data to broken cache in non-lazy cache mode
    description: |
      Verify contents of primary storage after writes to cache with underlaying error
      device in non-lazy cache mode and check taht all IO requests succeeded
    pass_criteria:
      - No I/O errors returned to the user
      - The primary storage contents match the actual written data
    """
    cache_line_size = CacheLineSize.DEFAULT
    with TestRun.step("Prepare core and cache"):
        cache, core, core_device = prepare_configuration(cache_mode, cache_line_size)

    fio_cmd = (
        Fio()
        .create_command()
        .io_engine(IoEngine.libaio)
        .size(core.size)
        .block_size(block_size)
        .target(core)
        .direct()
        .read_write(ReadWrite.randrw)
        .verify_pattern()
        .verify(VerifyMethod.pattern)
    )

    with TestRun.step("Run fio and verify no errors present"):
        fio_errors = fio_cmd.run()[0].total_errors()
        if fio_errors != 0:
            TestRun.fail(f"Some I/O ended with errors {fio_errors}")

    with TestRun.step("Verify core device contents"):
        cache.stop()
        fio_cmd.target(core_device).verify_only().run()


@pytest.mark.parametrizex("cache_mode", CacheMode.with_traits(CacheModeTrait.LazyWrites))
@pytest.mark.parametrizex(
    "block_size", [start_size, Size(1024, Unit.Byte), Size(4, Unit.KibiByte), stop_size]
)
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_cache_write_lazy_insert_error(cache_mode, block_size):
    """
    title: Cache insert test with error device for writes on lazy writes cache mode
    description: |
      Validate CAS ability to handle write errors while it tries to insert
      cache lines. This test is exclusively for lazy writes cache modes.
    pass_criteria:
      - I/O errors returned to user
      - Cache automatically stops after encountering errors
      - No cache line gets inserted into cache
    """
    cache_line_size = CacheLineSize.DEFAULT
    with TestRun.step("Prepare core and cache"):
        cache, core, _ = prepare_configuration(cache_mode, cache_line_size)

    with TestRun.step("Run fio and verify errors are present"):
        fio_errors = (
            Fio()
            .create_command()
            .io_engine(IoEngine.libaio)
            .size(core.size)
            .block_size(block_size)
            .read_write(ReadWrite.randwrite)
            .target(core)
            .continue_on_error(ErrorFilter.io)
            .direct()
            .run()[0]
            .total_errors()
        )
        if fio_errors == 0:
            TestRun.fail("No I/O ended with error")

    with TestRun.step("Check error statistics and state on cache"):
        stats = cache.get_statistics()

        occupancy = cache.get_occupancy().get_value()
        if occupancy != 0:
            TestRun.fail(f"Occupancy is not zero, but {occupancy}")

        # Convert cache writes from bytes to I/O count.
        # Cache errors are accounted with request granularity.
        # Blocks are expressed with 4k granularity.
        correction = int(math.ceil(Size(1, Unit.Blocks4096) / block_size))
        cache_writes_upper = int(stats.block_stats.cache.writes / block_size)
        cache_writes_lower = cache_writes_upper - correction + 1
        cache_errors = stats.error_stats.cache.total

        if not cache_writes_lower <= cache_errors <= cache_writes_upper:
            TestRun.fail(
                f"Cache errors ({cache_errors}) should equal to number of"
                f" requests to cache (range {cache_writes_lower}-{cache_writes_upper})"
            )

        state = cache.get_status()
        if state != CacheStatus.not_running:
            TestRun.fail(f"Cache should be in 'Not running' state, and it's {state}")


def prepare_configuration(cache_mode, cache_line_size):
    cache_device = TestRun.disks["cache"]
    core_device = TestRun.disks["core"]

    with TestRun.step("Creating cache partition"):
        cache_device.create_partitions([Size(50, Unit.MebiByte)])

    with TestRun.step("Creating cache error device"):
        error_device = ErrorDevice("error", cache_device.partitions[0])

    with TestRun.step("Starting cache to check metadata offset"):
        cache = casadm.start_cache(error_device, cache_line_size=cache_line_size, force=True)
        cache_size = cache.size
        cache.stop()

    with TestRun.step("Setting errors on non-metadata area"):
        error_device.change_table(
            DmTable.error_table(
                offset=(cache_device.partitions[0].size - cache_size).get_value(Unit.Blocks512),
                size=cache_size,
            ).fill_gaps(cache_device.partitions[0])
        )

    with TestRun.step("Create core partition with size of usable cache space"):
        core_device.create_partitions([cache_size])

    with TestRun.step("Starting and configuring cache"):
        cache = casadm.start_cache(
            error_device, cache_mode=cache_mode, cache_line_size=cache_line_size, force=True
        )
        result = cache.set_seq_cutoff_policy(SeqCutOffPolicy.never)
        if result.exit_code:
            TestRun.LOGGER.exception("Couldn't set seq cutoff policy")
        result = cache.set_cleaning_policy(CleaningPolicy.nop)
        if result.exit_code:
            TestRun.LOGGER.exception("Couldn't set cleaning policy")

    with TestRun.step("Stopping udev"):
        Udev.disable()

    with TestRun.step("Adding core device"):
        core = cache.add_core(core_dev=core_device.partitions[0])

    with TestRun.step("Purge cache and reset statistics"):
        cache.purge_cache()
        cache.reset_counters()

    return cache, core, core_device.partitions[0]
