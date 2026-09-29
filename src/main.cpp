#include <stdio.h>
#include "pico/stdlib.h"
#include "pico/multicore.h"


extern "C"{
#include "lv_port.h"

#include "qspi_pio.h"
#include "QMI8658.h"
#include "Touch.h"
#include "PCF85063A.h"
#include "LCD_3in49.h"
}

#include "UsageScreen.h"
#include "AudioPlayer.h"

// Shared by both cores: core 0 fills it from USB, core 1 plays it
static AudioPlayer audio;

void core1_entry() {
    static int press_time = 0;
    while(1)
    {
        // Plays (or outputs silence for) 5 ms, paced by the codec's clock
        audio.pump5ms();
        if(DEV_Digital_Read(SYS_OUT) == 0)
        {
            press_time++;
            if(press_time > 300)//shutdown
            {
                press_time = 0;
                DEV_Digital_Write(SYS_EN, 0);
            }
        }
        else
        {
            press_time = 0;
        }
    }
}

int main()
{
    stdio_init_all();
    sleep_ms(2000);

    if (DEV_Module_Init() != 0){
         printf("Dev Module Init Failed\n");
         for (;;)
        	 sleep_ms(2000);
    }

    /*PWR*/
	multicore_launch_core1(core1_entry);

	printf("LCD_3IN49_LCGL_test Demo\r\n");
	/*QSPI PIO Init*/
	QSPI_GPIO_Init(qspi);
	QSPI_PIO_Init(qspi);
	QSPI_4Wrie_Mode(&qspi);
	/*Init LCD*/
	LCD_3IN49_Init();
	DEV_SET_PWM(60);
	LCD_3IN49_Clear(BLACK);
	/*Init RTC*/
	PCF85063A_Init();
	/*Init IMU*/
	QMI8658_init();
	/*Init audio: ES8311 codec, MCLK and I2S output*/
	audio.init();
	/*Init LVGL*/
	LVGL_Init();

    // Usage snapshots and streamed audio arrive over USB serial from
    // tools/claude_usage_host.py
    static UsageScreen usage(&audio);
    usage.init();
    for(;;){
        lv_timer_handler();
        //printf("Loop\n");
        sleep_ms(1);
    }
}
