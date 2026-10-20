#ifndef SPI_LINK_CONFIG_H
#define SPI_LINK_CONFIG_H

/* Parameters most users will change. Keep SPI_TEST_FRAME_SIZE equal to
 * SPI_FRAME_SIZE_BYTES in the Power Deck project.
 */
#define SPI_TEST_FRAME_SIZE          14900U
#define SPI_TEST_PERIOD_MS           30U
#define SPI_STARTUP_DELAY_MS         1000U
#define SPI_TEST_BAUDRATE_PRESCALER  SPI_BAUDRATEPRESCALER_16

#endif /* SPI_LINK_CONFIG_H */
