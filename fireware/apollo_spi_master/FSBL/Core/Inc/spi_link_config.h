#ifndef SPI_LINK_CONFIG_H
#define SPI_LINK_CONFIG_H

/* Match DEPTH_TEST_FORMAT=3 in the Wi-Fi Power Deck receiver. */
#define SPI_DPT_FORMAT               3U
#define SPI_TEST_PAYLOAD_SIZE        14900U
#define SPI_DPT_HEADER_SIZE          14U
#define SPI_DPT_CRC_SIZE             4U
#define SPI_DPT_FRAME_SIZE           (SPI_DPT_HEADER_SIZE + SPI_TEST_PAYLOAD_SIZE + SPI_DPT_CRC_SIZE)
#define SPI_TEST_FRAME_SIZE          ((SPI_DPT_FRAME_SIZE + 3U) & ~3U)

#define SPI_TEST_PERIOD_MS           30U
#define SPI_STARTUP_DELAY_MS         1000U
#define SPI_TEST_BAUDRATE_PRESCALER  SPI_BAUDRATEPRESCALER_16

#endif /* SPI_LINK_CONFIG_H */
