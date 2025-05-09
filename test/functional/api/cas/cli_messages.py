#
# Copyright(c) 2019-2022 Intel Corporation
# Copyright(c) 2024-2025 Huawei Technologies
# SPDX-License-Identifier: BSD-3-Clause
#

import re

from connection.utils.output import Output
from core.test_run import TestRun


attach_not_enough_memory = [
    r"Not enough free RAM\.\nYou need at least \d+.\d+GB to attach a device to cache "
    r"with cache line size equal \d+kB.\n"
    r"Try with greater cache line size\."
]

attach_with_existing_metadata = [
    r"Error inserting cache \d+",
    r"Old metadata found on device",
    r"Please attach another device or use --force to discard on-disk metadata",
    r" and attach this device to cache instance\."
]

load_inactive_core_missing = [
    r"WARNING: Can not resolve path to core \d+ from cache \d+\. By-id path will be shown for that "
    r"core\.",
    r"WARNING: Cache is in incomplete state - at least one core is inactive",
]

start_cache_with_existing_metadata = [
    r"Error inserting cache \d+",
    r"Old metadata found on device",
    r"Please load cache metadata using --load option or use --force to",
    r" discard on-disk metadata and start fresh cache instance\.",
]

attach_cache_with_existing_metadata = [
    r"Error inserting cache \d+",
    r"Old metadata found on device",
    r"Please attach another device or use --force to discard on-disk metadata",
    r" and attach this device to cache instance\.",
]

start_cache_on_already_used_dev = [
    r"Error inserting cache \d+",
    r"Cache device \'\/dev\/\S+\' is already used as cache\.",
]

start_cache_with_existing_id = [
    r"Error inserting cache \d+",
    r"Cache ID already exists",
]

standby_init_with_existing_filesystem = [
    r"A filesystem exists on \S+. Specify the --force option if you wish to add the cache anyway.",
    r"Note: this may result in loss of data",
]

error_inserting_cache = [r"Error inserting cache \d+"]

reinitialize_with_force_or_recovery = [
    r"Old metadata found on device\.",
    r"Please load cache metadata using --load option or use --force to",
    r" discard on-disk metadata and start fresh cache instance\.",
]

remove_inactive_core_with_remove_command = [
    r"Core is inactive\. To manage the inactive core use '--remove-inactive' command\."
]

remove_inactive_dirty_core = [
    r"The cache contains dirty data assigned to the core\. If you want to ",
    r"continue, please use --force option\.\nWarning: the data will be lost",
]

stop_cache_incomplete = [
    r"Error while stopping cache \d+",
    r"Cache is in incomplete state - at least one core is inactive",
]

stop_cache_errors = [
    r"Stopped cache \d+ with errors",
    r"Error while writing to cache device",
]

get_stats_ioclass_id_not_configured = [r"IO class \d+ is not configured\."]

get_stats_ioclass_id_out_of_range = [r"Invalid IO class id, must be in the range 0-32\."]

remove_multilevel_core = [
    r"Error while removing core device \d+ from cache instance \d+",
    r"Device opens or mount are pending to this cache",
]

add_cached_core = [
    r"Error while adding core device to cache instance \d+",
    r"Core device \'/dev/\S+\' is already cached\.",
]

already_cached_core = [
    r"Error while adding core device to cache instance \d+",
    r"Device already added as a core",
]

remove_mounted_core = [
    r"Can\'t remove core \d+ from cache \d+ due to mounted devices:"
]

remove_mounted_core_kernel = [
    r"Error while removing core device \d+ from cache instance \d+",
    r"Device opens or mount are pending to this cache",
]

stop_cache_mounted_core = [
    r"Can\'t stop cache instance \d+ due to mounted devices:"
]

stop_cache_mounted_core_kernel = [
    r"Error while stopping cache \d+",
    r"Device opens or mount are pending to this cache",
]

load_and_force = [
    r"Use of \'load\' with \'force\', \'cache-id\', \'cache-mode\' or \'cache-line-size\'",
    r" simultaneously is forbidden.",
]

try_add_core_sector_size_mismatch = [
    r"Error while adding core device to cache instance \d+",
    r"Cache device logical sector size is greater than core device logical sector size\.",
    r"Consider changing logical sector size on current cache device",
    r"or try other device with the same logical sector size as core device\.",
]

no_caches_running = [r"No caches running"]

unavailable_device = [
    r"Error while opening \'\S+\'exclusively\. This can be due to\n"
    r"cache instance running on this device\. In such case please stop the cache and try again\."
]

error_handling = [r"Error during options handling"]

no_cas_metadata = [r"Device \'\S+\' does not contain OpenCAS's metadata\."]

cache_dirty_data = [
    r"Cache instance contains dirty data\. Clearing metadata will result in loss of dirty data\.\n"
    r"Please load cache instance and flush dirty data in order to preserve them on the core "
    r"device\.\n"
    r"Alternatively, if you wish to clear metadata anyway, please use \'--force\' option\."
]

cache_dirty_shutdown = [
    r"Cache instance did not shut down cleanly\. It might contain dirty data\. \n"
    r"Clearing metadata might result in loss of dirty data\. Please recover cache instance\n"
    r"by loading it and flush dirty data in order to preserve them on the core device\.\n"
    r"Alternatively, if you wish to clear metadata anyway, please use \'--force\' option\."
]

missing_param = [r"Option \'.+\' is missing"]

disallowed_param = [r"Unrecognized option \S+"]

operation_forbidden_in_standby = [
    r"The operation is not permitted while the cache is in the standby mode"
]

set_param_detached_cache = [r"Setting runtime parameter failed!"]

operation_forbidden_detached_cache = [
    r"The operation is not permitted while the cache is detached"
]

set_cache_mode_detached_cache = [
    r"Error while setting cache state for cache \d+\n"
    r"The operation is not permitted while the cache is detached"
]

remove_core_detached_cache = [
    r"Failed to remove core\. See dmesg for more information"
]

mutually_exclusive_params_init = [
    r"Can\'t use \'load\' and \'init\' options simultaneously\nError during options handling"
]

mutually_exclusive_params_load = [
    r"Use of \'load\' with \'force\', \'cache-id\' or \'cache-line-size\' simultaneously is "
    r"forbidden."
]

activate_with_different_cache_id = [
    r"Cache id specified by user and loaded from metadata are different"
]

cache_activated_successfully = [r"Successfully activated cache instance \d+"]

invalid_core_volume_size = [r"Core volume size does not match the size stored in cache metadata"]

error_activating_cache = [r"Error activating cache \d+"]

activate_without_detach = [
    r"Cannot open the device exclusively. Make sure to detach cache before activation."
]

cache_line_size_mismatch = [r"Cache line size mismatch"]

headerless_io_class_config = [
    r'Cannot parse configuration file - unknown column "1"\.\n'
    r"Failed to parse I/O classes configuration file header\. It is either malformed or missing\.\n"
    r"Please consult Admin Guide to check how columns in configuration file should be named\."
]

illegal_io_class_config_L2C1 = [
    r"Cannot parse configuration file - error in line 2 in column 1 \(IO class id\)\."
]

illegal_io_class_config_L2C2 = [
    r"Empty or too long IO class name\n"
    r"Cannot parse configuration file - error in line 2 in column 2 \(IO class name\)\."
]

illegal_io_class_config_L2C4 = [
    r"Cannot parse configuration file - error in line 2 in column 4 \(Allocation\)\."
]

illegal_io_class_config_L2 = [r"Cannot parse configuration file - error in line 2\."]

double_io_class_config = [
    r"Double configuration for IO class id \d+\n"
    r"Cannot parse configuration file - error in line \d+ in column \d+ \(IO class id\)\."
]

illegal_io_class_invalid_id = [
    r"Invalid id, must be a correct unsigned decimal integer\.\n"
    r"Cannot parse configuration file - error in line 2 in column 1 \(IO class id\)\."
]

illegal_io_class_invalid_id_number = [
    r"Invalid id, must be in the range 0-32\.\n"
    r"Cannot parse configuration file - error in line 2 in column 1 \(IO class id\)\."
]

illegal_io_class_invalid_priority = [
    r"Invalid prio, must be a correct unsigned decimal integer\.\n"
    r"Cannot parse configuration file - error in line 2 in column 3 \(Eviction priority\)"
]

illegal_io_class_invalid_priority_number = [
    r"Invalid prio, must be in the range 0-255\.\n"
    r"Cannot parse configuration file - error in line 2 in column 3 \(Eviction priority\)"
]

illegal_io_class_invalid_allocation = [
    r"Cannot parse configuration file - error in line 2 in column 4 \(Allocation\)\."
]

illegal_io_class_invalid_allocation_number = [
    r"Cannot parse configuration file - error in line 2 in column 4 \(Allocation\)\."
]

malformed_io_class_header = [
    r"Cannot parse configuration file - unknown column \"value_template\"\.\n"
    r"Failed to parse I/O classes configuration file header\. It is either malformed or missing\.\n"
    r"Please consult Admin Guide to check how columns in configuration file should be named\."
]

unexpected_cls_option = [r"Option '--cache-line-size \(-x\)' is not allowed"]

attach_not_enough_memory = [
    r"Not enough free RAM\.\nYou need at least \d+.\d+GB to attach a device to cache "
    r"with cache line size equal \d+kB.\n"
    r"Try with greater cache line size\."
]


def check_stderr_msg(output: Output, expected_messages, negate=False):
    return __check_string_msg(output.stderr, expected_messages, negate)


def check_stdout_msg(output: Output, expected_messages, negate=False):
    return __check_string_msg(output.stdout, expected_messages, negate)


def __check_string_msg(text: str, expected_messages, negate=False):
    msg_ok = True
    for msg in expected_messages:
        matches = re.search(msg, text)
        if not matches and not negate:
            TestRun.LOGGER.error(f"Message is incorrect, expected: {msg}\n actual: {text}.")
            msg_ok = False
        elif matches and negate:
            TestRun.LOGGER.error(
                f"Message is incorrect, expected to not find: {msg}\n actual: {text}."
            )
            msg_ok = False
    return msg_ok
