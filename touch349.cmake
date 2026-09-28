if (DEFINED TOUCH349_PATH)
	message("Using Given TOUCH349_PATH '${TOUCH349_PATH}')")
else ()
	set(TOUCH349_PATH "${CMAKE_CURRENT_LIST_DIR}/lib/touch349/")
    message("Using local TOUCH349_PATH '${TOUCH349_PATH}')")
endif ()

add_library(touch349 STATIC)
target_sources(touch349 PUBLIC
    ${TOUCH349_PATH}/Config/DEV_Config.c
    ${TOUCH349_PATH}/LCD/LCD_3in49.c
    ${TOUCH349_PATH}/PCF85063A/PCF85063A.c
    ${TOUCH349_PATH}/PSRAM/psram_tool.c
    ${TOUCH349_PATH}/PSRAM/rp_pico_alloc.c
    ${TOUCH349_PATH}/QMI8658/QMI8658.c
    ${TOUCH349_PATH}/QSPI_PIO/qspi_pio.c
    ${TOUCH349_PATH}/Touch/Touch.c
    ${TOUCH349_PATH}/ES8311/es8311.c
    ${TOUCH349_PATH}/Audio_PIO/audio_pio.c
    ${TOUCH349_PATH}/Audio_Data/audio_data.c
)

pico_generate_pio_header(touch349 ${TOUCH349_PATH}/QSPI_PIO/qspi.pio)
pico_generate_pio_header(touch349 ${TOUCH349_PATH}/Audio_PIO/audio_pio.pio)

# Add include directory
target_include_directories(touch349 PUBLIC
    ${TOUCH349_PATH}/Config
    ${TOUCH349_PATH}/LCD
    ${TOUCH349_PATH}/PCF85063A
    ${TOUCH349_PATH}/PSRAM
    ${TOUCH349_PATH}/QMI8658
    ${TOUCH349_PATH}/QSPI_PIO
    ${TOUCH349_PATH}/Touch
    ${TOUCH349_PATH}/ES8311
    ${TOUCH349_PATH}/Audio_PIO
    ${TOUCH349_PATH}/Audio_Data
)


target_link_libraries(touch349 PUBLIC 
    pico_stdlib 
    hardware_spi 
    hardware_i2c 
    hardware_pwm 
    hardware_adc 
    hardware_dma
    hardware_pio
    hardware_irq
    hardware_flash
    )