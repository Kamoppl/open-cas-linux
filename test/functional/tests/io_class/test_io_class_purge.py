#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from collections import namedtuple

from api.cas import ioclass_config, casadm
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.dd import Dd
from test_tools.fs_tools import Filesystem, create_directory
from test_tools.os_tools import drop_caches, DropCachesMode, sync
from test_tools.udev import Udev
from type_def.size import Unit, Size
from tests.io_class.io_class_common import prepare, mountpoint, ioclass_config_path


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
def test_ioclass_usage_sum():
    """
    title: Test for ioclass stats after purge
    description: |
      Create io classes for 3 different directories. Run IO against each
      directory, check usage stats correctness before and after purge.
    pass_criteria:
      - Usage stats are consistent on each test step
      - Usage stats don't exceed cache size
    """
    with TestRun.step("Prepare disks"):
        cache, core = prepare()
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}"):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        default_ioclass_id = 0
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio dir_path io_size")
        io_classes = [
            IoclassConfig(1, 3, f"{mountpoint}/A", cache_size * 0.25),
            IoclassConfig(2, 4, f"{mountpoint}/B", cache_size * 0.35),
            IoclassConfig(3, 5, f"{mountpoint}/C", cache_size * 0.1),
        ]

        for io_class in io_classes:
            create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Add io classes for all dirs"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(True)
        for io_class in io_classes:
            add_io_class(
                io_class.id,
                io_class.eviction_prio,
                f"directory:{io_class.dir_path}&done",
            )

        casadm.load_io_classes(cache_id=cache.cache_id, file=ioclass_config_path)

        # Since default ioclass is already present in cache and no directory should be
        # created, it is added to io classes list after setup is done
        io_classes.append(IoclassConfig(default_ioclass_id, 22, f"{mountpoint}", cache_size * 0.2))

    with TestRun.step("Verify stats of newly started cache device"):
        sync()
        drop_caches(DropCachesMode.ALL)
        verify_ioclass_usage_stats(cache, [i.id for i in io_classes])

    with TestRun.step("Trigger IO to each partition and verify stats"):
        for io_class in io_classes:
            run_io_dir(io_class.dir_path, int(io_class.io_size / Unit.Blocks4096.get_value()))

        verify_ioclass_usage_stats(cache, [i.id for i in io_classes])

    with TestRun.step("Purge cache and verify stats"):
        cache.purge_cache()

        verify_ioclass_usage_stats(cache, [i.id for i in io_classes])

    with TestRun.step("Trigger IO to each partition for the second time and verify stats"):
        for io_class in io_classes:
            run_io_dir(io_class.dir_path, int(io_class.io_size / Unit.Blocks4096.get_value()))

        verify_ioclass_usage_stats(cache, [i.id for i in io_classes])


def get_io_class_usage(cache, io_class_id):
    return cache.get_io_class_statistics(io_class_id=io_class_id).usage_stats


def verify_ioclass_usage_stats(cache, ioclasses_ids):
    cache_size = cache.get_statistics().config_stats.cache_size

    usage_stats_occupancy_sum = Size.zero()
    usage_stats_clean_sum = Size.zero()
    usage_stats_dirty_sum = Size.zero()

    all_io_class_usage_stats = []
    for i in ioclasses_ids:
        io_class_usage_stats = get_io_class_usage(cache, i)
        usage_stats_occupancy_sum += io_class_usage_stats.occupancy
        usage_stats_clean_sum += io_class_usage_stats.clean
        usage_stats_dirty_sum += io_class_usage_stats.dirty
        all_io_class_usage_stats.append(io_class_usage_stats)

    cache_usage_stats = cache.get_statistics().usage_stats

    if (
            cache_usage_stats.occupancy != usage_stats_occupancy_sum
            or cache_usage_stats.clean != usage_stats_clean_sum
            or cache_usage_stats.dirty != usage_stats_dirty_sum
    ):
        TestRun.LOGGER.error(
            "Sum of io classes usage stats doesn't match cache usage stats!\n"
            f"Cache usage stats: {cache_usage_stats}\n"
            f"Usage stats occupancy sum: {usage_stats_occupancy_sum}\n"
            f"Usage stats clean sum: {usage_stats_clean_sum}\n"
            f"Usage stats dirty sum: {usage_stats_dirty_sum}\n"
            f"{all_io_class_usage_stats}"
        )

    if cache_usage_stats.occupancy + cache_usage_stats.free > cache_size:
        TestRun.LOGGER.error(
            "Sum of occupancy and free cache lines exceeds cache size!"
            f" Occupancy: {cache_usage_stats.occupancy}, free: {cache_usage_stats.free}"
            f" cache size: {cache_size}"
        )


def add_io_class(class_id, eviction_prio, rule):
    ioclass_config.add_ioclass(
        ioclass_id=class_id,
        eviction_priority=eviction_prio,
        allocation="1.00",
        rule=rule,
        ioclass_config_path=ioclass_config_path,
    )


def run_io_dir(path, num_ios):
    (
        Dd()
        .input("/dev/zero")
        .output(f"{path}/tmp_file")
        .count(num_ios)
        .block_size(Size(1, Unit.Blocks4096))
        .run()
    )
    sync()
    drop_caches(DropCachesMode.ALL)
