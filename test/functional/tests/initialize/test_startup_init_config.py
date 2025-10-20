#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: BSD-3-Clause
#

import pytest

from datetime import timedelta
from time import sleep
from api.cas import casctl, casadm, casadm_parser
from api.cas.cache_config import CacheMode, CacheStatus
from api.cas.cas_service import set_cas_service_timeout, clear_cas_service_timeout
from api.cas.cli_messages import check_stdout_msg, no_caches_running
from api.cas.core import CoreStatus
from api.cas.init_config import InitConfig
from core.test_run import TestRun
from storage_devices.disk import DiskType, DiskTypeSet, DiskTypeLowerThan
from test_tools import fstab
from test_tools.dd import Dd
from test_tools.fs_tools import Filesystem, readlink
from test_tools.os_tools import sync
from test_tools.udev import Udev
from test_utils.emergency_escape import EmergencyEscape
from test_utils.filesystem.file import File
from type_def.size import Size, Unit

mountpoint = "/mnt"
filepath = f"{mountpoint}/file"
cores_number = 4


@pytest.mark.os_dependent
@pytest.mark.remote_only
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("filesystem", Filesystem)
def test_cas_startup(cache_mode, filesystem):
    """
    title: Test for starting CAS on system startup.
    description: |
        Check if OpenCAS loads correctly after system reboot.
    pass_criteria:
      - System does not crash.
      - CAS modules are loaded before partitions are mounted.
      - Cache is loaded before partitions are mounted.
      - Exported object is mounted after startup is complete.
    """
    with TestRun.step("Prepare partitions for cache (200MiB) and for core (400MiB)"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step("Start cache and add core"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        core = cache.add_core(core_part)

    with TestRun.step("Create and mount filesystem"):
        core.create_filesystem(filesystem)
        core.mount(mountpoint)

    with TestRun.step("Create test file and calculate md5 checksum"):
        (
            Dd()
            .input("/dev/urandom")
            .output(filepath)
            .count(16)
            .block_size(Size(1, Unit.MebiByte))
            .run()
        )
        test_file = File(filepath)
        md5_before = test_file.md5sum()

    with TestRun.step("Add mountpoint fstab and create intelcas.conf"):
        fstab.add_mountpoint(device=core, mount_point=mountpoint, fs_type=filesystem)
        InitConfig.create_init_config_from_running_configuration()

    with TestRun.step("Reboot"):
        TestRun.executor.reboot()

    with TestRun.step("Check if cache is started"):
        caches = casadm_parser.get_caches()
        if len(caches) != 1:
            TestRun.fail(f"Expected one cache, got {len(caches)}!")
        if caches[0].cache_id != cache.cache_id:
            TestRun.fail("Invalid cache id!")

    with TestRun.step("Check if core is added"):
        cores = casadm_parser.get_cores(cache.cache_id)
        if len(cores) != 1:
            TestRun.fail(f"Expected one core, got {len(cores)}!")
        if cores[0].core_id != core.core_id:
            TestRun.fail("Invalid core id!")

    with TestRun.step("Check if filesystem is mounted"):
        if not core.is_mounted():
            TestRun.fail("Core is not mounted!")

    with TestRun.step("Check if md5 checksum matches"):
        md5_after = test_file.md5sum()
        if md5_before != md5_after:
            TestRun.fail("md5 checksum mismatch!")

    with TestRun.step("Test cleanup"):
        fstab.remove_mountpoint(device=core)
        core.unmount()
        InitConfig.create_default_init_config()
        casadm.stop_all_caches()


@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex(
    "cache_mode_pair",
    [
        (CacheMode.WT, CacheMode.WB),
        (CacheMode.WB, CacheMode.WA),
        (CacheMode.WA, CacheMode.PT),
        (CacheMode.PT, CacheMode.WO),
        (CacheMode.WO, CacheMode.WT),
    ],
)
def test_cas_init_with_changed_mode(cache_mode_pair):
    """
    title: Check starting cache in other cache mode by initializing OpenCAS service from config.
    description: |
        Start cache, create config based on running configuration but with another cache mode,
        reinitialize OpenCAS service with '--force' option and check if cache defined
        in config file starts properly.
        Check all cache modes.
    pass_criteria:
      - Cache starts with attached core
      - Cache starts in mode saved in configuration file.
    """
    with TestRun.step("Prepare partitions for cache and core."):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(400, Unit.MebiByte)])
        core_part = core_dev.partitions[0]

    with TestRun.step(f"Start cache in the {cache_mode_pair[0]} mode and add core."):
        cache = casadm.start_cache(cache_part, cache_mode_pair[0], force=True)
        core = cache.add_core(core_part)

    with TestRun.step(
        f"Create the configuration file with a different cache mode ({cache_mode_pair[1]})"
    ):
        init_conf = InitConfig()
        init_conf.add_cache(cache.cache_id, cache.cache_device, cache_mode_pair[1])
        init_conf.add_core(cache.cache_id, core.core_id, core.core_device)
        init_conf.save_config_file()

    with TestRun.step("Reinitialize OpenCAS service with '--force' option."):
        casadm.stop_all_caches()
        casctl.init(True)

    with TestRun.step("Check if cache started in correct mode with core attached."):
        validate_cache(cache_mode_pair[1])


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
@pytest.mark.require_plugin("power_control")
def test_cas_startup_lazy():
    """
    title: Test successful boot with CAS configuration including lazy_startup
    description: |
        Check that DUT boots successfully with failing lazy-startup marked devices
    pass_criteria:
      - DUT boots successfully
      - caches are configured as expected
    """
    with TestRun.step("Prepare partitions"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache_disk.create_partitions([Size(200, Unit.MebiByte)] * 2)
        core_disk.create_partitions([Size(200, Unit.MebiByte)] * 4)

    with TestRun.step(
        "Add a cache configuration with cache device with `lazy_startup` flag"
    ):
        init_conf = InitConfig()
        init_conf.add_cache(
            1, cache_disk.partitions[0], extra_flags="lazy_startup=True"
        )
        init_conf.add_core(1, 1, core_disk.partitions[0])
        init_conf.add_core(1, 2, core_disk.partitions[1])

        expected_core_pool_paths = set(c.path for c in core_disk.partitions[:2])

    with TestRun.step(
        "Add a cache configuration with core device with `lazy_startup` flag"
    ):
        init_conf.add_cache(2, cache_disk.partitions[1])
        init_conf.add_core(2, 1, core_disk.partitions[2])
        init_conf.add_core(
            2, 2, core_disk.partitions[3], extra_flags="lazy_startup=True"
        )
        init_conf.save_config_file()
        sync()

        expected_caches_paths = set([cache_disk.partitions[1].path])
        expected_cores_paths = set(c.path for c in core_disk.partitions[2:])
        active_core_path = core_disk.partitions[2].path
        inactive_core_path = core_disk.partitions[3].path

    with TestRun.step(
        "Start and stop all the configurations using the casctl utility"
    ):
        output = casctl.init(True)
        if output.exit_code != 0:
            TestRun.fail(
                f"Failed to initialize caches from config file. Error: {output.stdout}"
            )
        casadm.stop_all_caches()

    with TestRun.step(
        "Disable udev to allow manipulating partitions without CAS being automatically loaded"
    ):
        Udev.disable()

    with TestRun.step("Remove one cache partition and one core partition"):
        cache_disk.remove_partition(cache_disk.partitions[0])
        core_disk.remove_partition(core_disk.partitions[3])

    with TestRun.step("Reboot DUT"):
        power_control = TestRun.plugin_manager.get_plugin("power_control")
        power_control.power_cycle(wait_for_connection=True)

    with TestRun.step("Verify if all the devices are initialized properly"):
        core_pool_list = casadm_parser.get_cas_devices_dict()["core_pool"]
        caches_list = casadm_parser.get_cas_devices_dict()["caches"].values()
        cores_list = casadm_parser.get_cas_devices_dict()["cores"].values()

        core_pool_paths = {c["device_path"] for c in core_pool_list}
        if core_pool_paths != expected_core_pool_paths:
            TestRun.LOGGER.error(
                f"Expected the following devices in core pool "
                f"{expected_core_pool_paths}. Got {core_pool_paths}"
            )
        else:
            TestRun.LOGGER.info("Core pool is ok")

        caches_paths = {c["device_path"] for c in caches_list}
        if caches_paths != expected_caches_paths:
            TestRun.LOGGER.error(
                f"Expected the following devices as caches "
                f"{expected_caches_paths}. Got {caches_paths}"
            )
        else:
            TestRun.LOGGER.info("Caches are ok")

        cores_paths = {c["device_path"] for c in cores_list}
        if cores_paths != expected_cores_paths:
            TestRun.LOGGER.error(
                f"Expected the following devices as cores "
                f"{expected_caches_paths}. Got {cores_paths}"
            )
        else:
            TestRun.LOGGER.info("Core devices are ok")

        cores_states = {c["device_path"]: c["status"] for c in cores_list}
        if cores_states[active_core_path] != CoreStatus.active:
            TestRun.LOGGER.error(
                f"Core {active_core_path} should be Active "
                f"but is {cores_states[active_core_path]} instead!"
            )

        if cores_states[inactive_core_path] != CoreStatus.inactive:
            TestRun.LOGGER.error(
                f"Core {inactive_core_path} should be Inactive "
                f"but is {cores_states[inactive_core_path]} instead!"
            )


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
def test_cas_startup_negative_missing_core():
    """
    title: Test unsuccessful boot with CAS configuration
    description: |
        Check that DUT doesn't boot sucesfully when using invalid CAS configuration
    pass_criteria:
      - DUT enters emergency mode
    """
    with TestRun.step("Create 2 cache partitions and 4 core partitons"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache_disk.create_partitions([Size(200, Unit.MebiByte)] * 2)
        core_disk.create_partitions([Size(200, Unit.MebiByte)] * 4)

    with TestRun.step(
        "Add a cache configuration with cache device with `lazy_startup` flag"
    ):
        init_conf = InitConfig()
        init_conf.add_cache(
            1, cache_disk.partitions[0], extra_flags="lazy_startup=True"
        )
        init_conf.add_core(1, 1, core_disk.partitions[0])
        init_conf.add_core(1, 2, core_disk.partitions[1])

    with TestRun.step(
        "Add a cache configuration with core device with `lazy_startup` flag"
    ):
        init_conf.add_cache(2, cache_disk.partitions[1])
        init_conf.add_core(2, 1, core_disk.partitions[2])
        init_conf.add_core(
            2, 2, core_disk.partitions[3], extra_flags="lazy_startup=True"
        )
        init_conf.save_config_file()
        sync()

    with TestRun.step(
        "Start and stop all the configurations using the casctl utility"
    ):
        output = casctl.init(True)
        if output.exit_code != 0:
            TestRun.fail(
                f"Failed to initialize caches from config file. Error: {output.stdout}"
            )
        casadm.stop_all_caches()

    with TestRun.step(
        "Disable udev to allow manipulating partitions without CAS being automatically loaded"
    ):
        Udev.disable()

    with TestRun.step("Remove core partition"):
        core_disk.remove_partition(core_disk.partitions[0])

    escape = EmergencyEscape()
    escape.add_escape_method_command("/usr/bin/rm /etc/opencas/opencas.conf")
    set_cas_service_timeout(timedelta(minutes=1))

    with TestRun.step("Reboot DUT with emergency escape armed"):
        with escape:
            TestRun.executor.reboot()

    with TestRun.step("Verify the DUT entered emergency mode"):
        dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout.split("\n")
        if not escape.verify_trigger_in_log(dmesg_out):
            TestRun.LOGGER.error("DUT didn't enter emergency mode after reboot")

    clear_cas_service_timeout()
    InitConfig().create_default_init_config()

    # required to fix services after test
    with TestRun.step("Reboot platform"):
        TestRun.executor.reboot()


@pytest.mark.os_dependent
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
def test_cas_startup_negative_missing_cache():
    """
    title: Test unsuccessful boot with CAS configuration
    description: |
        Check that DUT doesn't boot sucesfully when using invalid CAS configuration
    pass_criteria:
      - DUT enters emergency mode
    """
    with TestRun.step("Create 2 cache partitions and 4 core partitons"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache_disk.create_partitions([Size(200, Unit.MebiByte)] * 2)
        core_disk.create_partitions([Size(200, Unit.MebiByte)] * 4)

    with TestRun.step(
        "Add a cache configuration with cache device with `lazy_startup` flag"
    ):
        init_conf = InitConfig()
        init_conf.add_cache(
            1, cache_disk.partitions[0], extra_flags="lazy_startup=True"
        )
        init_conf.add_core(1, 1, core_disk.partitions[0])
        init_conf.add_core(1, 2, core_disk.partitions[1])

    with TestRun.step(
        "Add a cache configuration with core devices with `lazy_startup` flag"
    ):
        init_conf.add_cache(2, cache_disk.partitions[1])
        init_conf.add_core(
            2, 1, core_disk.partitions[2], extra_flags="lazy_startup=True"
        )
        init_conf.add_core(
            2, 2, core_disk.partitions[3], extra_flags="lazy_startup=True"
        )
        init_conf.save_config_file()
        sync()

    with TestRun.step(
        "Start and stop all the configurations using the casctl utility"
    ):
        output = casctl.init(True)
        if output.exit_code != 0:
            TestRun.fail(
                f"Failed to initialize caches from config file. Error: {output.stdout}"
            )
        casadm.stop_all_caches()

    with TestRun.step(
        "Disable udev to allow manipulating partitions without CAS being automatically loaded"
    ):
        Udev.disable()

    with TestRun.step("Remove second cache partition"):
        cache_disk.remove_partition(cache_disk.partitions[1])

    escape = EmergencyEscape()
    escape.add_escape_method_command("/usr/bin/rm /etc/opencas/opencas.conf")
    set_cas_service_timeout(timedelta(minutes=1))

    with TestRun.step("Reboot DUT with emergency escape armed"):
        with escape:
            TestRun.executor.reboot()

    with TestRun.step("Verify the DUT entered emergency mode"):
        dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout.split("\n")
        if not escape.verify_trigger_in_log(dmesg_out):
            TestRun.LOGGER.error("DUT didn't enter emergency mode after reboot")

    clear_cas_service_timeout()
    InitConfig().create_default_init_config()

    # required to fix services after test
    with TestRun.step("Reboot platform"):
        TestRun.executor.reboot()


@pytest.mark.os_dependent
@pytest.mark.skip(reason="Standby mode is not supported")
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeSet([DiskType.hdd]))
@pytest.mark.require_plugin("power_control")
def test_failover_config_startup():
    """
    title: Test successful boot with failover-specific configuration options
    description: |
        Check that DUT boots sucesfully and CAS is properly configured when using failover-specific
        configuration options (target_failover_state)
    pass_criteria:
      - DUT boots sucesfully
      - caches are configured as expected
    """
    with TestRun.step("Prepare partitions"):
        cache_disk = TestRun.disks["cache"]
        core_disk = TestRun.disks["core"]
        cache_disk.create_partitions([Size(200, Unit.MebiByte)] * 2)
        core_disk.create_partitions([Size(200, Unit.MebiByte)])

    with TestRun.step(
        "Add a cache configuration with cache device with "
        "`target_failover_state=active` flag and a core"
    ):
        init_conf = InitConfig()
        init_conf.add_cache(
            1, cache_disk.partitions[0], extra_flags="target_failover_state=active"
        )
        init_conf.add_core(1, 1, core_disk.partitions[0])
        active_cache_device_path = cache_disk.partitions[0].path
        active_core_device_path = core_disk.partitions[0].path

    with TestRun.step(
        "Add a cache configuration with cache device with "
        "`target_failover_state=failover` flag"
    ):
        init_conf.add_cache(
            2,
            cache_disk.partitions[1],
            extra_flags="target_failover_state=standby,cache_line_size=4",
        )
        standby_cache_path = cache_disk.partitions[1].path
        init_conf.save_config_file()
        sync()

    with TestRun.step(
        "Start and stop all the configurations using the casctl utility"
    ):
        output = casctl.init(True)
        if output.exit_code != 0:
            TestRun.fail(
                f"Failed to initialize caches from config file. Error: {output.stdout}"
            )
        casadm.stop_all_caches()

    with TestRun.step("Reboot DUT"):
        power_control = TestRun.plugin_manager.get_plugin("power_control")
        power_control.power_cycle()

    with TestRun.step("Verify if all the devices are initialized properly"):
        core_pool_list = casadm_parser.get_cas_devices_dict()["core_pool"]
        caches_list = casadm_parser.get_cas_devices_dict()["caches"].values()
        cores_list = casadm_parser.get_cas_devices_dict()["cores"].values()

        if len(core_pool_list) != 0:
            TestRun.LOGGER.error(
                f"No cores expected in core pool. Got {core_pool_list}"
            )
        else:
            TestRun.LOGGER.info("Core pool is ok")

        expected_caches_paths = {active_cache_device_path, standby_cache_path}
        caches_paths = {c["device"] for c in caches_list}
        if caches_paths != expected_caches_paths:
            TestRun.LOGGER.error(
                f"Expected the following devices as caches "
                f"{expected_caches_paths}. Got {caches_paths}"
            )
        else:
            TestRun.LOGGER.info("Caches are ok")

        expected_core_paths = {active_core_device_path}
        cores_paths = {c["device"] for c in cores_list}
        if cores_paths != expected_core_paths:
            TestRun.LOGGER.error(
                f"Expected the following devices as cores "
                f"{expected_core_paths}. Got {cores_paths}"
            )
        else:
            TestRun.LOGGER.info("Core devices are ok")

        cores_states = {c["device"]: c["status"] for c in cores_list}
        if cores_states[active_core_device_path] != CoreStatus.active:
            TestRun.LOGGER.error(
                f"Core {active_core_device_path} should be Active "
                f"but is {cores_states[active_core_device_path]} instead!"
            )

        caches_states = {c["device"]: c["status"] for c in caches_list}
        if caches_states[active_cache_device_path] != CacheStatus.running:
            TestRun.LOGGER.error(
                f"Cache {active_cache_device_path} should be Running "
                f"but is {caches_states[active_cache_device_path]} instead!"
            )
        if caches_states[standby_cache_path] != CacheStatus.standby:
            TestRun.LOGGER.error(
                f"Cache {standby_cache_path} should be Standby "
                f"but is {caches_states[standby_cache_path]} instead!"
            )


@pytest.mark.os_dependent
@pytest.mark.skip(reason="Standby mode is not supported")
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
def test_failover_config_startup_negative():
    """
    title: Test unsuccessful boot with failover-specific configuration options
    description: |
        Check that DUT doesn't boot successfully with misconfigured cache using failover-specific
        configuration options (target_failover_state). After boot it should be verified that
        emergency mode was in fact triggered.
    pass_criteria:
      - DUT enters emergency mode
    """

    with TestRun.step("Create cache partition"):
        cache_disk = TestRun.disks["cache"]
        cache_disk.create_partitions([Size(200, Unit.MebiByte)])

    with TestRun.step("Add a cache configuration with standby cache"):
        init_conf = InitConfig()
        init_conf.add_cache(
            1,
            cache_disk.partitions[0],
            extra_flags="target_failover_state=standby,cache_line_size=4",
        )
        init_conf.save_config_file()
        sync()

    with TestRun.step(
        "Start and stop all the configurations using the casctl utility"
    ):
        output = casctl.init(True)
        if output.exit_code != 0:
            TestRun.fail(
                f"Failed to initialize caches from config file. Error: {output.stdout}"
            )
        casadm.stop_all_caches()

    with TestRun.step(
        "Disable udev to allow manipulating partitions without CAS being automatically loaded"
    ):
        Udev.disable()

    with TestRun.step("Remove second cache partition"):
        cache_disk.remove_partition(cache_disk.partitions[0])

    escape = EmergencyEscape()
    escape.add_escape_method_command("/usr/bin/rm /etc/opencas/opencas.conf")
    set_cas_service_timeout(timedelta(seconds=32))

    with TestRun.step("Reboot DUT with emergency escape armed"):
        with escape:
            TestRun.executor.reboot()
            TestRun.executor.wait_for_connection()

    with TestRun.step("Verify the DUT entered emergency mode"):
        dmesg_out = TestRun.executor.run_expect_success("dmesg").stdout.split("\n")
        if not escape.verify_trigger_in_log(dmesg_out):
            TestRun.LOGGER.error("DUT didn't enter emergency mode after reboot")

    clear_cas_service_timeout()
    InitConfig().create_default_init_config()


def validate_cache(cache_mode):
    caches = casadm_parser.get_caches()
    caches_count = len(caches)
    if caches_count != 1:
        TestRun.LOGGER.error(
            f"Cache did not start successfully - wrong number of caches: {caches_count}."
        )

    cores = casadm_parser.get_cores(caches[0].cache_id)
    cores_count = len(cores)
    if cores_count != 1:
        TestRun.LOGGER.error(
            f"Cache started with wrong number of cores: {cores_count}."
        )

    current_mode = caches[0].get_cache_mode()
    if current_mode != cache_mode:
        TestRun.LOGGER.error(
            f"Cache started in wrong mode!\n"
            f"Should start in {cache_mode}, but started in {current_mode} mode."
        )


@pytest.mark.os_dependent
@pytest.mark.remote_only
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("reboot_type", ["soft", "hard"])
@pytest.mark.require_plugin("power_control")
def test_lazy_startup_core_path_by_id(cache_mode, reboot_type):
    """
    title: Lazy startup when cores are set in config with by-id path.
    description: |
        Test if core devices are recognized during lazy initialization when their paths
        are configured as existing by-id paths.
    pass_criteria:
      - System does not crash
      - Cache is not running after startup
      - Cores are detached after startup
    """

    with TestRun.step("Prepare partitions for cache and for cores"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        for partition in core_dev.partitions:
            cache.add_core(partition)

    with TestRun.step("Create init config file"):
        InitConfig.create_init_config_from_running_configuration(
            cache_extra_flags="lazy_startup=true", core_extra_flags="lazy_startup=true"
        )

    with TestRun.step("Stop cache and clear metadata before reboot"):
        cache.stop()
        casadm.zero_metadata(cache_part)

    with TestRun.step("Reset platform"):
        if reboot_type == "soft":
            TestRun.executor.reboot()
        else:  # wait few seconds to simulate power failure during normal system run
            sleep(5)  # not when configuring Open CAS
            power_control = TestRun.plugin_manager.get_plugin("power_control")
            power_control.power_cycle(wait_for_connection=True)

    with TestRun.step("Check if cache is not running"):
        if len(casadm_parser.get_caches()) > 0:
            TestRun.fail("Cache is running after system startup but it shouldn't.")

    with TestRun.step("Check if all cores are detached"):
        listed_cores = casadm_parser.get_cas_devices_dict().get("core_pool")
        listed_cores_number = len(listed_cores)
        if listed_cores_number != cores_number:
            TestRun.fail(f"Expected {cores_number} cores, got {listed_cores_number}!")

        for core in listed_cores.values():
            if core.get("status") != CoreStatus.detached:
                TestRun.fail(f"Core {core.get('device')} isn't detached as expected.")


@pytest.mark.os_dependent
@pytest.mark.remote_only
@pytest.mark.require_disk("cache", DiskTypeSet([DiskType.optane, DiskType.nand]))
@pytest.mark.require_disk("core", DiskTypeLowerThan("cache"))
@pytest.mark.parametrizex("cache_mode", CacheMode)
@pytest.mark.parametrizex("reboot_type", ["soft", "hard"])
@pytest.mark.require_plugin("power_control")
def test_lazy_startup_core_path_not_by_id(cache_mode, reboot_type):
    """
    title: Lazy startup when cores are set in config with short path.
    description: |
        Test if core devices are recognized during lazy initialization when their paths
        are configured as existing short paths (/dev/sdx).
    pass_criteria:
      - System does not crash
      - Cache is not running after startup
      - No cores after startup
    """

    with TestRun.step("Prepare partitions for cache and for cores"):
        cache_dev = TestRun.disks["cache"]
        cache_dev.create_partitions([Size(200, Unit.MebiByte)])
        cache_part = cache_dev.partitions[0]
        core_dev = TestRun.disks["core"]
        core_dev.create_partitions([Size(400, Unit.MebiByte)] * cores_number)

    with TestRun.step("Start cache and add cores"):
        cache = casadm.start_cache(cache_part, cache_mode, force=True)
        cores = [cache.add_core(partition) for partition in core_dev.partitions]

    with TestRun.step("Create init config file"):
        create_init_config(
            cache, cores, [readlink(part.path) for part in core_dev.partitions]
        )

    with TestRun.step("Stop cache and clear metadata before reboot"):
        cache.stop()
        casadm.zero_metadata(cache_part)

    with TestRun.step("Reset platform"):
        if reboot_type == "soft":
            TestRun.executor.reboot()
        else:  # wait few seconds to simulate power failure during normal system run
            sleep(5)  # not when configuring Open CAS
            power_control = TestRun.plugin_manager.get_plugin("power_control")
            power_control.power_cycle(wait_for_connection=True)

    with TestRun.step("Check if cache is not running"):
        check_stdout_msg(casadm.list_caches(), no_caches_running)


def create_init_config(cache, cores, paths):
    init_conf = InitConfig()

    init_conf.add_cache(
        cache.cache_id, cache.cache_device, cache.get_cache_mode(), "lazy_startup=true"
    )
    for core, path in zip(cores, paths):
        params = [str(cache.cache_id), str(core.core_id), path, "lazy_startup=true"]
        init_conf.core_config_lines.append("\t".join(params))
    init_conf.save_config_file()
    return init_conf
