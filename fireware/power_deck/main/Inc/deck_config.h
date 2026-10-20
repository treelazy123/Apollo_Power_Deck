#ifndef MAIN_DECK_CONFIG_H_
#define MAIN_DECK_CONFIG_H_

/* Change these values to match the hotspot created by the computer. */
#define POWER_WIFI_SSID              "myssid"
#define POWER_WIFI_PASSWORD          "mypassword"

/* PC sends PDHELLO1/text to this port; stream data and text ACKs return to its source port. */
#define STREAM_DISCOVERY_PORT       5006
#define STREAM_PEER_LEASE_MS        5000
#define POWER_SAMPLE_PERIOD_MS     100
#define POWER_QUEUE_LENGTH         32
#define DEPTH_FRAME_COUNT          3
/* Match SPI_TEST_FORMAT in ../n6/FSBL/Core/Inc/spi_link_config.h. */
#define DEPTH_TEST_FORMAT          3U
/* STM32N6 is SPI master and controls the clock and frame rate.
 * Match Apollo wiring: SCK=6, MOSI=7, active-low CS=4; MISO is unused.
 * No READY wire: the master is paced and the slave prequeues frame buffers. */
#define DEPTH_GPIO_SCK             6
#define DEPTH_GPIO_MOSI            7
#define DEPTH_GPIO_CS              4
#endif
