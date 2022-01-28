#!/bin/bash -
#******************************************************************************
#  * @attention
#  *
#  * <h2><center>&copy; Copyright (c) 2021 STMicroelectronics.
#  * All rights reserved.</center></h2>
#  *
#  * This software component is licensed by ST under BSD 3-Clause license,
#  * the "License"; You may not use this file except in compliance with the
#  * License. You may obtain a copy of the License at:
#  *                        opensource.org/licenses/BSD-3-Clause
#  *
#  ******************************************************************************

echo "TFM UPDATE for STM32 started"

tfm/repos/trusted-firmware-m/cmake_build/postbuild.sh
cp -v tfm/repos/trusted-firmware-m/cmake_build/regression.sh mbed-os/targets/TARGET_STM/TARGET_STM32L5/TARGET_STM32L552xE/TARGET_NUCLEO_L552ZE_Q/TFM_S_FW/
cp -v tfm/repos/trusted-firmware-m/cmake_build/TFM_UPDATE.sh mbed-os/targets/TARGET_STM/TARGET_STM32L5/TARGET_STM32L552xE/TARGET_NUCLEO_L552ZE_Q/TFM_S_FW/

cd mbed-os/targets/TARGET_STM/TARGET_STM32L5/TARGET_STM32L552xE/TARGET_NUCLEO_L552ZE_Q/TFM_S_FW/

sed -i 's/FLASH_LAYOUT_FOR_TEST/MBED_CONF_APP_REGRESSION_TEST/' partition/flash_layout.h
sed -i '/STM32CubeProgrammer/d' regression.sh
sed -i 's/tfm_ns_signed/tfm_mbed-os-tf-m-regression-tests_signed/' TFM_UPDATE.sh
sed -i '/STM32CubeProgrammer/d' TFM_UPDATE.sh
sed -i 's/-el $external_loader//g' TFM_UPDATE.sh

which STM32_Programmer_CLI &> /dev/null
if [ $? -ne 0 ]; then
    echo STM32_Programmer_CLI is not part of environment path
    echo 'PATH="/C/Program Files/STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/":$PATH'
    echo 'PATH="~/STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/":$PATH'
    exit 1
fi