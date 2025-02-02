#!/usr/bin/env python3
"""
Copyright (c) 2019-2021 ARM Limited. All rights reserved.

SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import os
import argparse
import glob
import sys
import signal
import shutil
import logging
from psa_builder import *
from tools.toolchains import TOOLCHAIN_PATHS
from tools.targets import TARGET_MAP

logging.basicConfig(
    level=logging.INFO,
    format="[Build-TF-M] %(asctime)s: %(message)s.",
    datefmt="%H:%M:%S",
)

MBED_TF_M_PATH = os.path.join(mbed_path, TF_M_RELATIVE_PATH)


def _detect_and_write_tfm_version(tfm_dir, commit):
    """
    Identify the version of TF-M and write it to VERSION.txt
    :param tfm_dir: The filesystem path where TF-M repo is cloned
    :param commit: If True then commmit the VERSION.txt
    """
    cmd = [
        "git",
        "-C",
        tfm_dir,
        "describe",
        "--tags",
        "--abbrev=12",
        "--dirty",
        "--always",
    ]
    tfm_version = run_cmd_and_return(cmd, True)
    logging.info("TF-M version: %s", tfm_version.strip("\n"))
    if not os.path.isdir(MBED_TF_M_PATH):
        os.makedirs(MBED_TF_M_PATH)
    # Write the version to Mbed OS
    with open(os.path.join(MBED_TF_M_PATH, "VERSION.txt"), "w") as f:
        f.write(tfm_version)

    if commit:
        _commit_changes(MBED_TF_M_PATH)


def _clone_tfm_repo(target, commit):
    """
    Clone TF-M git repos and it's dependencies
    :param target: Target name
    :param commit: If True then commit VERSION.txt
    """
    if target == "NU_M2354":
        check_and_clone_repo(
            "trusted-firmware-m", "nuvoton-tfm", TF_M_BUILD_DIR
        )
    else:
        check_and_clone_repo(
            "trusted-firmware-m", "released-tfm", TF_M_BUILD_DIR
        )

    _detect_and_write_tfm_version(
        os.path.join(TF_M_BUILD_DIR, "trusted-firmware-m"), commit
    )


def _get_target_info(target, toolchain=None):
    """
    Creates a TF-M target tuple (target name, TF-M target name, toolchain,
    delivery directory)

    :param target: Target name.
    :param toolchain: Toolchain
    :return: tuple (target name, TF-M target name, toolchain, delivery directory)
    """
    if toolchain:
        if not TARGET_MAP[target].tfm_supported_toolchains:
            msg = "Supported Toolchains is not configured for target %s" % (
                TARGET_MAP[target].name
            )
            raise Exception(msg)
        elif toolchain not in TARGET_MAP[target].tfm_supported_toolchains:
            msg = "Toolchain %s is not supported by %s" % (
                toolchain,
                TARGET_MAP[target].name,
            )
            raise Exception(msg)
        tc = toolchain
    else:
        tc = TARGET_MAP[target].tfm_default_toolchain

    delivery_dir = os.path.join(
        mbed_path, "targets", TARGET_MAP[target].tfm_delivery_dir
    )

    if not os.path.exists(delivery_dir):
        msg = "Delivery directory (delivery_dir) missing for %s" % target
        raise FileNotFoundError(msg)

    return tuple(
        [
            TARGET_MAP[target].name,
            TARGET_MAP[target].tfm_target_name,
            tc,
            delivery_dir,
        ]
    )


def _get_mbed_supported_tfm_targets():
    """
    Returns a generator with every element containing a TF-M target tuple
    (target name, TF-M target name, toolchain, delivery directory)
    """
    tfm_secure_targets = get_tfm_secure_targets()
    logging.info(
        "Found the following TF-M targets in targets.json: {}".format(
            ", ".join(tfm_secure_targets)
        )
    )

    return (_get_target_info(t) for t in tfm_secure_targets)


def _commit_changes(directory, target_toolchain=None):
    """
    Check for changes in `directory` and if any then commit them
    :param directory: path to be checked for changes
    :param target_toolchain: List of Tuple (target name, toolchain)
    """
    # Use --intent-to-add option of git status to identify un-tracked files
    cmd = ["git", "-C", mbed_path, "status", "N", directory]
    run_cmd_and_return(cmd)

    cmd = ["git", "-C", mbed_path, "diff", "--exit-code", "--quiet", directory]
    changes_made = run_cmd_and_return(cmd)

    if target_toolchain is None:
        if changes_made:
            logging.info("Committing changes in directory %s" % directory)
            cmd = [
                "git",
                "-C",
                mbed_path,
                "add",
                os.path.relpath(directory, mbed_path),
            ]
            run_cmd_and_return(cmd)
            msg = '--message="Update directory %s"' % os.path.relpath(
                directory, mbed_path
            )
            cmd = ["git", "-C", mbed_path, "commit", msg]
            run_cmd_and_return(cmd)
        else:
            logging.info(
                "No changes detected in %s, skipping commit"
                % os.path.relpath(directory, mbed_path)
            )
        return

    if changes_made:
        logging.info("Committing image for %s" % target_toolchain)
        cmd = [
            "git",
            "-C",
            mbed_path,
            "add",
            os.path.relpath(directory, mbed_path),
        ]
        run_cmd_and_return(cmd)
        msg = '--message="Update secure binaries for %s"' % target_toolchain
        cmd = ["git", "-C", mbed_path, "commit", msg]
        run_cmd_and_return(cmd)
    else:
        logging.info(
            "No changes detected for %s, skipping commit" % target_toolchain
        )


def _run_cmake_build(cmake_build_dir, args, tgt, tfm_config):
    """
    Run the Cmake build

    :param cmake_build_dir: Base directory for Cmake build
    :param args: Command-line arguments
    :param tgt[]:
    0: Target name
    1: TF-M target name
    2: Toolchain
    3: Delivery directory
    :return Error code returned by Cmake build
    """
    if args.debug:
        msg = (
            "Building TF-M for target %s using toolchain %s in DEBUG mode"
            % (
                tgt[0],
                tgt[2],
            )
        )
    else:
        msg = "Building TF-M for target %s using toolchain %s" % (
            tgt[0],
            tgt[2],
        )
    logging.info(msg)

    cmake_cmd = ["cmake", "../", "-GNinja", "-DTFM_PSA_API=ON"]
    cmake_cmd.append("-DTFM_PLATFORM=" + tgt[1])
    cmake_cmd.append("-DTFM_TOOLCHAIN_FILE=../toolchain_" + tgt[2] + ".cmake")

    if args.config == SUPPORTED_TFM_CONFIGS[1]:
        cmake_cmd.extend(
            [
                "-DTEST_NS=ON",
                "-DTEST_S=ON",
                "-DTFM_PERIPH_ACCESS_TEST=ON",
            ]
        )

    if args.debug:
        cmake_cmd.append("-DCMAKE_BUILD_TYPE=Debug")
    else:
        cmake_cmd.append("-DCMAKE_BUILD_TYPE=Release")

    if not TARGET_MAP[tgt[0]].tfm_bootloader_supported:
        cmake_cmd.append("-DBL2=FALSE")
    else:
        cmake_cmd.append("-DBL2=True")

    if args.config in SUPPORTED_TFM_PSA_CONFIGS:
        if args.suite in PSA_SUITE_CHOICES:
            cmake_cmd.append("-DTEST_PSA_API=" + args.suite)

    logging.info(cmake_cmd)

    retcode = run_cmd_output_realtime(cmake_cmd, cmake_build_dir)
    if retcode:
        msg = "Cmake configure failed for target %s using toolchain %s" % (
            tgt[0],
            tgt[2],
        )
        logging.critical(msg)
        sys.exit(1)

    # install option exports NS APIs to a dedicated folder under
    # cmake build folder
    cmake_cmd = ["cmake", "--build", ".", "--", "install"]

    retcode = run_cmd_output_realtime(cmake_cmd, cmake_build_dir)
    if retcode:
        msg = "Cmake build failed for target %s using toolchain %s" % (
            tgt[0],
            tgt[2],
        )
        logging.critical(msg)
        sys.exit(1)


def _copy_binaries(source, destination, toolchain, target):
    """
    Copy TF-M binaries from source to destination

    :param source: directory where TF-M binaries are available
    :param destination: directory to which TF-M binaries are copied to
    :param toolchain: build toolchain
    :param target: target name
    """
    if destination.endswith("/"):
        output_dir = destination
    else:
        output_dir = destination + "/"

    tfm_secure_axf = os.path.join(source, "tfm_s.axf")
    logging.info(
        "Copying %s to %s"
        % (
            os.path.relpath(tfm_secure_axf, mbed_path),
            os.path.relpath(output_dir, mbed_path),
        )
    )
    shutil.copy2(tfm_secure_axf, output_dir)

    try:
        out_ext = TARGET_MAP[target].TFM_OUTPUT_EXT
    except AttributeError:
        tfm_secure_bin = os.path.join(source, "tfm_s.bin")
        logging.info(
            "Copying %s to %s"
            % (
                os.path.relpath(tfm_secure_bin, mbed_path),
                os.path.relpath(output_dir, mbed_path),
            )
        )
        shutil.copy2(tfm_secure_bin, output_dir)
    else:
        if out_ext == "hex":
            tfm_secure_bin = os.path.join(source, "tfm_s.hex")
            global TC_DICT
            if toolchain == "ARMCLANG":
                elf2bin = os.path.join(
                    TOOLCHAIN_PATHS[TC_DICT.get(toolchain)], "fromelf"
                )
                cmd = [
                    elf2bin,
                    "--i32",
                    "--output=" + tfm_secure_bin,
                    tfm_secure_axf,
                ]
            elif toolchain == "GNUARM":
                elf2bin = os.path.join(
                    TOOLCHAIN_PATHS[TC_DICT.get(toolchain)],
                    "arm-none-eabi-objcopy",
                )
                cmd = [elf2bin, "-O", "ihex", tfm_secure_axf, tfm_secure_bin]

            run_cmd_and_return(cmd)

            logging.info(
                "Copying %s to %s"
                % (
                    os.path.relpath(tfm_secure_bin, mbed_path),
                    os.path.relpath(output_dir, mbed_path),
                )
            )
            shutil.copy2(tfm_secure_bin, output_dir)

    if TARGET_MAP[target].tfm_bootloader_supported:
        mcu_bin = os.path.join(source, "bl2.bin")
        shutil.copy2(mcu_bin, output_dir)

    if "TFM_V8M" in TARGET_MAP[target].extra_labels:
        install_dir = os.path.abspath(
            os.path.join(source, os.pardir, os.pardir)
        )

        # Support multi-level TF-M target name.
        head_tail = os.path.split(TARGET_MAP[target].tfm_target_name)
        while head_tail[0]:
            install_dir = os.path.join(install_dir, os.pardir)
            head_tail = os.path.split(head_tail[0])

        tfm_veneer = os.path.join(
            install_dir, "interface", "lib", "s_veneers.o"
        )
        shutil.copy2(tfm_veneer, output_dir)


def _copy_tfm_ns_files(source, target):
    """
    Copy TF-M NS API files into Mbed OS
    :param source: Source directory containing TF-M NS API files
    """

    mbed_os_excluded_files = []

    def _is_excluded(filename):
        for f in mbed_os_excluded_files:
            if filename in f:
                return True
        return False

    def _copy_file(fname, path):
        src_file = os.path.join(source, fname["src"])
        dst_file = os.path.join(path, fname["dst"])
        logging.info("Copying file: " + src_file + " - to - " + dst_file)
        if not os.path.isdir(os.path.dirname(dst_file)):
            os.makedirs(os.path.dirname(dst_file))
        try:
            if not _is_excluded(src_file):
                shutil.copy2(src_file, dst_file)
        except FileNotFoundError:
            # Workaround: TF-M build process exports all NS API files to
            # cmake build folder. The yaml file `tfm_ns_import.yaml` contains
            # list of files and folder relative to cmake build folder.
            # However, both mbed-os and regression tests needs some
            # files/folders which are not exported (the path names in
            # `tfm_ns_import.yaml` which don't begin with `install`). These
            # are handled as exceptions.
            src_file = os.path.join(source, os.pardir, fname["src"])
            shutil.copy2(src_file, dst_file)

    def _copy_folder(folder, path):
        src_folder = os.path.join(source, folder["src"])
        dst_folder = os.path.join(path, folder["dst"])
        logging.info("Copying folder: " + src_folder + " - to - " + dst_folder)
        if not os.path.isdir(dst_folder):
            os.makedirs(dst_folder)
        for f in os.listdir(src_folder):
            if os.path.isfile(os.path.join(src_folder, f)):
                if not _is_excluded(f):
                    shutil.copy2(
                        os.path.join(src_folder, f),
                        os.path.join(dst_folder, f),
                    )

    def _check_and_copy(list_of_items, path):
        for item in list_of_items:
            if os.path.isdir(os.path.join(source, item["src"])):
                _copy_folder(item, path)
            else:
                _copy_file(item, path)

    with open(
        os.path.join(os.path.dirname(__file__), "tfm_ns_import.yaml")
    ) as ns_import:
        yaml_data = yaml.safe_load(ns_import)
        logging.info("Copying files/folders from TF-M to Mbed OS")
        mbed_os_data = yaml_data["mbed-os"]
        mbed_os_excluded_files = mbed_os_data["excluded_files"]
        if target in mbed_os_data:
            _check_and_copy(mbed_os_data[target], mbed_path)
        if "common" in mbed_os_data:
            _check_and_copy(mbed_os_data["common"], mbed_path)
        if "TFM_V8M" in TARGET_MAP[target].extra_labels:
            if "v8-m" in mbed_os_data:
                _check_and_copy(mbed_os_data["v8-m"], mbed_path)
        if "TFM_DUALCPU" in TARGET_MAP[target].extra_labels:
            if "dualcpu" in mbed_os_data:
                _check_and_copy(mbed_os_data["dualcpu"], mbed_path)

        logging.info("Copying files/folders from TF-M to regression test")
        tf_regression_data = yaml_data["tf-m-regression"]
        if target in tf_regression_data:
            _check_and_copy(tf_regression_data[target], ROOT)
        if "common" in tf_regression_data:
            _check_and_copy(tf_regression_data["common"], ROOT)
        if "TFM_V8M" in TARGET_MAP[target].extra_labels:
            if "v8-m" in tf_regression_data:
                _check_and_copy(tf_regression_data["v8-m"], ROOT)
        if "TFM_DUALCPU" in TARGET_MAP[target].extra_labels:
            if "dualcpu" in tf_regression_data:
                _check_and_copy(tf_regression_data["dualcpu"], ROOT)


def _copy_psa_libs(source, destination, args):
    """
    Copy PSA Compliance libraries from source to destination

    :param source: directory where libraries are available
    :param destination: directory to which libraries are copied to
    :param args: Command-line arguments
    """

    output_dir = os.path.join(
        destination, "test", "lib", "TOOLCHAIN_" + TC_DICT[args.toolchain]
    )
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    source = os.path.join(source, "app", "psa_api_tests")
    output_lib_suffix = ".ar" if args.toolchain == "ARMCLANG" else ".a"

    val_nspe = os.path.join(source, "val", "val_nspe.a")
    val_nspe_output = os.path.join(
        output_dir, "libval_nspe" + output_lib_suffix
    )
    logging.info("Copying file: %s - to - %s" % (val_nspe, val_nspe_output))
    shutil.copy2(val_nspe, val_nspe_output)

    pal_nspe = os.path.join(source, "platform", "pal_nspe.a")
    pal_nspe_output = os.path.join(
        output_dir, "libpal_nspe" + output_lib_suffix
    )
    logging.info("Copying file: %s - to - %s" % (pal_nspe, pal_nspe_output))
    shutil.copy2(pal_nspe, pal_nspe_output)

    if (
        args.suite == "INITIAL_ATTESTATION"
        or args.suite == "CRYPTO"
        or args.suite == "IPC"
    ):
        suite_folder = str(args.suite).lower()
    else:
        # Applicable for INTERNAL_TRUSTED_STORAGE, PROTECTED_STORAGE
        # and STORAGE suites.
        suite_folder = "storage"

    if args.suite == "IPC":
        test_combine = os.path.join(
            source, "ff", suite_folder, "test_combine.a"
        )
    else:
        test_combine = os.path.join(
            source, "dev_apis", suite_folder, "test_combine.a"
        )

    test_combine_output = os.path.join(
        output_dir, "libtest_combine" + output_lib_suffix
    )
    logging.info(
        "Copying file: %s - to - %s" % (test_combine, test_combine_output)
    )
    shutil.copy2(test_combine, test_combine_output)


def _copy_library(source, toolchain):

    with open(
        os.path.join(os.path.dirname(__file__), "tfm_ns_import.yaml")
    ) as ns_import:
        logging.info(
            "Copying regression test libraries from TF-M to regression test"
        )
        yaml_data = yaml.safe_load(ns_import)
        tf_regression_data = yaml_data["tf-m-regression"]

        if "regression_libs" in tf_regression_data:
            for item in tf_regression_data["regression_libs"]:
                src_file = os.path.join(source, item["src"])
                dst_base = os.path.basename(src_file)

                if toolchain == "ARMCLANG":
                    dst_base = os.path.splitext(dst_base)[0] + ".ar"

                dst_file = os.path.join(
                    ROOT,
                    item["dst"],
                    "TOOLCHAIN_" + TC_DICT[toolchain],
                    dst_base,
                )
                logging.info(
                    "Copying file: " + src_file + " - to - " + dst_file
                )
                if not os.path.isdir(os.path.dirname(dst_file)):
                    os.makedirs(os.path.dirname(dst_file))

                # TODO:
                # https://github.com/ARMmbed/mbed-os-tf-m-regression-tests/issues/103
                # libtfm_test_suite_fwu_ns.a exists for Musca B1 only.
                # This is to avoid failure on Musca S1.
                if os.path.exists(src_file):
                    shutil.copy2(src_file, dst_file)
                else:
                    logging.info("Skipping " + src_file)

                if dst_base == "libplatform_ns.ar":
                    # TF-M redirects output to serial by declaring its own `FILE __stdout`
                    # and disables the toolchain's default version of this symbol using
                    # the flag `-nostdlib`. But stdlib is enabled and required by Mbed OS,
                    # so we need to disable the one from TF-M's libplatform_ns to avoid
                    # symbol duplication.
                    cmd = [
                        "fromelf",
                        "--elf",
                        "--localize",
                        "__stdout",
                        dst_file,
                        "-o",
                        dst_file,
                    ]
                    ret = run_cmd_and_return(cmd)
                    if ret:
                        msg = "Unable to strip __stdout from %s" % (dst_base,)
                        raise Exception(msg)


def _build_target(tgt, cmake_build_dir, args):
    """
    :param tgt: is a tuple:
    0: Target name
    1: TF-M target name
    2: Toolchain
    3: Delivery directory
    :param cmake_build_dir: Cmake build directory
    :param args: Command-line arguments
    """
    tgt_list = []
    logging.info("Building target - %s using %s toolchain" % (tgt[0], tgt[2]))

    _run_cmake_build(cmake_build_dir, args, tgt, args.config)

    if not args.skip_copy:
        source = os.path.join(
            cmake_build_dir, "install", "outputs", tgt[1].upper()
        )
        _copy_binaries(source, tgt[3], tgt[2], tgt[0])
        tgt_list.append((tgt[0], tgt[2]))

    if args.commit:
        _commit_changes(tgt[3], tgt_list)

    if not args.skip_copy:
        if args.config == SUPPORTED_TFM_CONFIGS[1]:
            _copy_library(cmake_build_dir, tgt[2])
        elif args.config in SUPPORTED_TFM_PSA_CONFIGS:
            _copy_psa_libs(cmake_build_dir, ROOT, args)

        _copy_tfm_ns_files(cmake_build_dir, tgt[0])

    if args.commit:
        _commit_changes(MBED_TF_M_PATH)


def _build_tfm(args):
    """
    Build TF-M
    :param args: Command-line arguments
    """

    if not args.skip_clone:
        _clone_tfm_repo(args.mcu, args.commit)

    cmake_build_dir = os.path.join(
        TF_M_BUILD_DIR, "trusted-firmware-m", "cmake_build"
    )
    if os.path.isdir(cmake_build_dir):
        shutil.rmtree(cmake_build_dir, onerror=handle_read_permission_error)

    os.mkdir(cmake_build_dir)

    if args.mcu:
        if args.toolchain:
            """
            _get_target_info() returns a tuple:
            0: Target name
            1: TF-M target name
            2: Toolchain
            3: Delivery directory
            """
            tgt = _get_target_info(args.mcu, args.toolchain)
        else:
            tgt = _get_target_info(args.mcu)

        _build_target(tgt, cmake_build_dir, args)

    else:
        for tgt in _get_mbed_supported_tfm_targets():
            """
            _get_mbed_supported_tfm_targets() returns a generator and each
            element contains a tuple:
            0: Target name
            1: TF-M target name
            2: Toolchain
            3: Delivery directory
            """
            # Build only for supported TF-M targets
            if tgt[0] in get_tfm_regression_targets():
                if args.toolchain:
                    tgt = _get_target_info(tgt[0], args.toolchain)

                _build_target(tgt, cmake_build_dir, args)


def _get_parser():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-c",
        "--config",
        help="Use the specified TF-M configuration",
        default=SUPPORTED_TFM_CONFIGS[0],
        choices=SUPPORTED_TFM_CONFIGS,
    )

    parser.add_argument(
        "-m",
        "--mcu",
        help="Build for the given MCU",
        default=None,
        choices=get_tfm_regression_targets(),
    )

    hmsg = "Build for the given toolchain (default is tfm_default_toolchain)"
    parser.add_argument(
        "-t",
        "--toolchain",
        help=hmsg,
        default=None,
        choices=["ARMCLANG", "GNUARM"],
    )

    parser.add_argument(
        "-d",
        "--debug",
        help="Set build profile to debug",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "-l",
        "--list",
        help="Print supported TF-M secure targets",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--commit",
        help="""
            Commit secure binaries (TF-M) and
            features/FEATURE_PSA/TARGET_TFM/VERSION.txt
            """,
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "-s",
        "--suite",
        help="Suite name for PSA API Tests",
        choices=PSA_SUITE_CHOICES,
        default=None,
    )

    parser.add_argument(
        "--clean",
        help="Clean the cloned dependencies",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--skip-clone",
        help="Skip cloning/checkout of TF-M dependencies",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--skip-copy",
        help="Skip copying TF-M dependencies to Mbed OS",
        action="store_true",
        default=False,
    )

    return parser


def _main():
    """
    Build TrustedFirmware-M (TF-M) image for supported targets
    """
    global TF_M_BUILD_DIR
    signal.signal(signal.SIGINT, exit_gracefully)
    parser = _get_parser()
    args = parser.parse_args()

    if args.list:
        logging.info(
            "Supported TF-M regression targets are: {}".format(
                ", ".join([t for t in get_tfm_regression_targets()])
            )
        )
        return

    if args.config not in SUPPORTED_TFM_CONFIGS:
        logging.info(
            "Supported TF-M configs are: {}".format(
                ", ".join([t for t in SUPPORTED_TFM_CONFIGS])
            )
        )
        return

    if args.config in SUPPORTED_TFM_PSA_CONFIGS:
        if not args.suite:
            logging.info(
                "Test suite required for supplied config: {}".format(
                    ", ".join([t for t in PSA_SUITE_CHOICES])
                )
            )
            return

    if args.clean:
        if args.skip_clone:
            args.skip_clone = False
            logging.info(
                "Cannot force to skip cloning/checkout when clean option is specified"
            )

        if os.path.isdir(TF_M_BUILD_DIR):
            logging.info("Removing folder %s" % TF_M_BUILD_DIR)
            shutil.rmtree(TF_M_BUILD_DIR, onerror=handle_read_permission_error)

    if not os.path.isdir(TF_M_BUILD_DIR):
        os.mkdir(TF_M_BUILD_DIR)

    logging.info("Using folder %s" % TF_M_BUILD_DIR)
    _build_tfm(args)


if __name__ == "__main__":
    if are_dependencies_installed() != 0:
        sys.exit(1)
    else:
        _main()
