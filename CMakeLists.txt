cmake_minimum_required(VERSION 3.13)

set(NAME LVGL) 
set(PICO_BOARD_HEADER_DIRS ${CMAKE_CURRENT_LIST_DIR}/boards) 
#set(PICO_BOARD pico2)
set(PICO_BOARD waveshare_rp2350_touch_lcd_3.49 CACHE STRING "Board type")
set(PICO_PLATFORM rp2350)

include("$ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake")
project(${NAME} C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(PICO_CXX_ENABLE_EXCEPTIONS 1)

# Initialize the SDK
pico_sdk_init()


include(touch349.cmake)

include(lvgl.cmake)

add_subdirectory(src)


#Set up files for the release packages
install(CODE "execute_process(COMMAND picotool load -v ${CMAKE_CURRENT_BINARY_DIR}/src/${NAME}.elf)")

# Set up files for the release packages
install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/src/${NAME}.uf2
    DESTINATION ${CMAKE_CURRENT_BINARY_DIR}
)

set(CPACK_INCLUDE_TOPLEVEL_DIRECTORY OFF)
set(CPACK_GENERATOR "ZIP" "TGZ")
include(CPack)
