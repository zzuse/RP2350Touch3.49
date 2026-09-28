
if (NOT DEFINED FATFS_SD_DIR)
    set(FATFS_SD_DIR "${CMAKE_CURRENT_LIST_DIR}/lib/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico")
endif()
if (NOT DEFINED FATFS_PORT_DIR)
    set(FATFS_PORT_DIR "${CMAKE_CURRENT_LIST_DIR}/port/fatfs")
endif()

# Defines the no-OS-FatFS-SD-SDIO-SPI-RPi-Pico interface library
add_subdirectory(${FATFS_SD_DIR}/src ${CMAKE_CURRENT_BINARY_DIR}/fatfs)

# FatFs + SD card driver, plus this board's card/pin configuration
add_library(sdcard INTERFACE)

target_sources(sdcard INTERFACE
	${FATFS_PORT_DIR}/hw_config.c
	)

target_link_libraries(sdcard INTERFACE
	no-OS-FatFS-SD-SDIO-SPI-RPi-Pico
	)
