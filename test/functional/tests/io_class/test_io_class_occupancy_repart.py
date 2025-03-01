#
# Copyright(c) 2020-2022 Intel Corporation
# Copyright(c) 2024 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from collections import namedtuple
from math import isclose

from api.cas import ioclass_config, casadm
from api.cas.cache_config import CacheMode, CacheLineSize
from api.cas.ioclass_config import IoClass, default_config_file_path
from core.test_run_utils import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools.fs_tools import Filesystem, create_directory, move
from test_tools.os_tools import sync
from test_tools.udev import Udev
from type_def.size import Unit
from tests.io_class.io_class_common import (
    prepare,
    mountpoint,
    ioclass_config_path,
    get_io_class_occupancy,
    run_io_dir,
    run_io_dir_read,
)


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrize("io_class_size_multiplication", [0.5, 1])
def test_ioclass_repart(io_class_size_multiplication):
    """
    title: Check whether occupancy limit is respected during repart
    description: |
      Create ioclass for 3 different directories, each with different max
      occupancy threshold. Create 3 files classified on default ioclass.
      Move files to directories created earlier and force repart by reading
      theirs contents.
    pass_criteria:
      - Partitions are evicted in specified order
    """
    cache_mode = CacheMode.WB
    cache_line_size = CacheLineSize.LINE_64KiB

    with TestRun.step("Prepare CAS device"):
        cache, core = prepare(cache_mode=cache_mode, cache_line_size=cache_line_size)
        cache_size = cache.get_statistics().config_stats.cache_size

    with TestRun.step("Disable udev"):
        Udev.disable()

    with TestRun.step(f"Prepare filesystem and mount {core.path} at {mountpoint}"):
        filesystem = Filesystem.xfs
        core.create_filesystem(filesystem)
        core.mount(mountpoint)
        sync()

    with TestRun.step("Prepare test dirs"):
        IoclassConfig = namedtuple("IoclassConfig", "id eviction_prio max_occupancy dir_path")
        io_classes = [
            IoclassConfig(1, 3, 0.40, f"{mountpoint}/A"),
            IoclassConfig(2, 4, 0.30, f"{mountpoint}/B"),
            IoclassConfig(3, 5, 0.30, f"{mountpoint}/C"),
        ]

        for io_class in io_classes:
            create_directory(io_class.dir_path, parents=True)

    with TestRun.step("Remove old io class config"):
        ioclass_config.remove_ioclass_config()
        ioclass_config.create_ioclass_config(False)

    with TestRun.step("Add default io classes"):
        ioclass_config.add_ioclass(*str(IoClass.default(allocation="1.00")).split(","))
        ioclass_config.add_ioclass(
            ioclass_id=5,
            rule="metadata",
            eviction_priority=1,
            allocation="1.00",
            ioclass_config_path=ioclass_config_path,
        )

    with TestRun.step("Add io classes for all dirs"):
        for io_class in io_classes:
            ioclass_config.add_ioclass(
                io_class.id,
                f"directory:{io_class.dir_path}&done",
                io_class.eviction_prio,
                f"{io_class.max_occupancy * io_class_size_multiplication:0.2f}",
            )

        casadm.load_io_classes(cache_id=cache.cache_id, file=default_config_file_path)

    with TestRun.step("Reset cache stats"):
        cache.purge_cache()
        cache.reset_counters()

    with TestRun.step(f"Create 3 files classified in default ioclass"):
        for i, io_class in enumerate(io_classes[0:3]):
            run_io_dir(
                f"{mountpoint}/{i}",
                int((io_class.max_occupancy * cache_size) / Unit.Blocks4096.get_value()),
            )

        if not isclose(
            get_io_class_occupancy(cache, ioclass_config.DEFAULT_IO_CLASS_ID).value,
            cache_size.value,
            rel_tol=0.1,
        ):
            TestRun.fail(f"Failed to populte default ioclass")

    with TestRun.step("Check initial occupancy"):
        for io_class in io_classes:
            occupancy = get_io_class_occupancy(cache, io_class.id)
            if occupancy.get_value() != 0:
                TestRun.LOGGER.error(
                    f"Incorrect initial occupancy for ioclass id: {io_class.id}."
                    f" Expected 0, got: {occupancy}"
                )

    with TestRun.step("Force repart - move files to created directories and read theirs contents"):
        for i, io_class in enumerate(io_classes):
            move(source=f"{mountpoint}/{i}", destination=io_class.dir_path)
            run_io_dir_read(f"{io_class.dir_path}/{i}")

    with TestRun.step("Check if each ioclass reached it's occupancy limit"):
        for io_class in io_classes[0:3]:
            actual_occupancy = get_io_class_occupancy(cache, io_class.id)

            occupancy_limit = (
                (io_class.max_occupancy * cache_size)
                .align_down(Unit.Blocks4096.get_value())
                .set_unit(Unit.Blocks4096)
            )

            if not isclose(actual_occupancy.value, occupancy_limit.value, rel_tol=0.1):
                TestRun.LOGGER.error(
                    f"Occupancy for ioclass {io_class.id} does not match. "
                    f"Limit: {occupancy_limit}, actual: {actual_occupancy}"
                )
