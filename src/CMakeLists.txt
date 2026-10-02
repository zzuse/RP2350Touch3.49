
add_executable(${NAME}
        main.cpp
        Widgets.cpp
        UsageScreen.cpp
        SerialLink.cpp
        AudioPlayer.cpp
        AutoRotate.cpp
        Gestures.cpp
        LevelControls.cpp
        Pager.cpp
        UiKit.cpp
        StatsPage.cpp

        )

# Pull in our pico_stdlib which pulls in commonly used features
target_link_libraries(${NAME} 
	 pico_stdlib
	 touch349
     lvgl
     sdcard
     pico_multicore
	)

   
# create map/bin/hex file etc.
pico_add_extra_outputs(${NAME})

# enable usb output, disable uart output
pico_enable_stdio_usb(${NAME} 1)
pico_enable_stdio_uart(${NAME} 0)

# Streamed audio arrives at 48 KB/s; the default 64-byte USB receive buffer
# can't keep up between polls
target_compile_definitions(${NAME} PRIVATE
    CFG_TUD_CDC_RX_BUFSIZE=4096
    CFG_TUD_CDC_TX_BUFSIZE=1024
    )
