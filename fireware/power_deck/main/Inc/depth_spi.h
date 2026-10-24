#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "esp_err.h"

#include "deck_config.h"
#define DEPTH_HEADER_BYTES 14U
#define DEPTH_MAGIC_DPT 0x01U
/* Opaque payload sizes; no pixel dimensions or units are implied. */
#if DEPTH_TEST_FORMAT == 1U
#define DEPTH_PAYLOAD_BYTES 6912U
#elif DEPTH_TEST_FORMAT == 2U
#define DEPTH_PAYLOAD_BYTES 9216U
#elif DEPTH_TEST_FORMAT == 3U
#define DEPTH_PAYLOAD_BYTES 14900U
#else
#error Unsupported DEPTH_TEST_FORMAT
#endif
#define DEPTH_FRAME_BYTES (DEPTH_HEADER_BYTES + DEPTH_PAYLOAD_BYTES + 4U)
/* UDP/bin contain FRAME_BYTES; SPI appends zero padding after CRC. */
#define DEPTH_SPI_BYTES ((DEPTH_FRAME_BYTES + 3U) & ~3U)
esp_err_t depth_spi_init(void);
/* DMA capacity includes a guard word; UDP still sends DEPTH_FRAME_BYTES. */
#define DEPTH_RX_BUFFER_BYTES (DEPTH_SPI_BYTES + 4U)
/* Only depth_rx_task calls these; buffers/descriptors remain owned by SPI
 * between a successful queue and receive. received_bits is the actual length. */
esp_err_t depth_spi_queue(uint8_t id, uint8_t *frame);
esp_err_t depth_spi_receive(uint8_t *id, size_t *received_bits);
typedef enum {
    DEPTH_CHECK_OK = 0,
    DEPTH_CHECK_HEADER,
    DEPTH_CHECK_CRC
} depth_check_t;
depth_check_t depth_frame_check(const uint8_t *frame);
uint32_t depth_u32(const uint8_t *p);
uint32_t depth_frame_sequence(const uint8_t *frame);