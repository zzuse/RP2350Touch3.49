/* hw_config.c
Copyright 2021 Carl John Kugler III

Licensed under the Apache License, Version 2.0 (the License); you may not use
this file except in compliance with the License. You may obtain a copy of the
License at

   http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an AS IS BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
*/
/*
SD card hardware configuration for the Waveshare RP2350 Touch LCD 3.49.

Pin assignments and SPI settings are taken from Waveshare's 03-FatFs demo, which
runs the card in SPI mode (its hw_config.h defines SPI_SD0). Waveshare's version
also declared three extra card slots on the same pins; they are dropped here
because the board has only one card socket.

See
  https://github.com/carlk3/no-OS-FatFS-SD-SDIO-SPI-RPi-Pico/tree/main#customizing-for-the-hardware-configuration
*/

#include "hw_config.h"

// Hardware Configuration of SPI "objects"
static spi_t spis[] = {
    {   // spis[0]
        .hw_inst = spi1,
        .sck_gpio = 26,
        .mosi_gpio = 27,
        .miso_gpio = 28,
        .set_drive_strength = true,
        .mosi_gpio_drive_strength = GPIO_DRIVE_STRENGTH_2MA,
        .sck_gpio_drive_strength = GPIO_DRIVE_STRENGTH_12MA,
        .no_miso_gpio_pull_up = true,
        .baud_rate = 125 * 1000 * 1000 / 6  // 20833333 Hz
    }
};

/* SPI Interfaces */
static sd_spi_if_t spi_ifs[] = {
    {   // spi_ifs[0]
        .spi = &spis[0],
        .ss_gpio = 31,
        .set_drive_strength = true,
        .ss_gpio_drive_strength = GPIO_DRIVE_STRENGTH_2MA
    }
};

/* Hardware Configuration of the SD Card "objects"
    These correspond to SD card sockets
*/
static sd_card_t sd_cards[] = {
    {   // sd_cards[0]: Socket sd0, mounted as "0:"
        .type = SD_IF_SPI,
        .spi_if_p = &spi_ifs[0],
        .use_card_detect = false
    }
};

/* ********************************************************************** */

size_t sd_get_num() { return count_of(sd_cards); }

sd_card_t *sd_get_by_num(size_t num) {
    if (num < sd_get_num()) {
        return &sd_cards[num];
    } else {
        return NULL;
    }
}

/* [] END OF FILE */
