#ifndef APOLLO_DPT_FRAME_H
#define APOLLO_DPT_FRAME_H

#include <stddef.h>
#include <stdint.h>

#include "spi_link_config.h"

_Static_assert(SPI_DPT_FORMAT == 3U && SPI_TEST_PAYLOAD_SIZE == 14900U,
               "This sender targets Power Deck DPT format 3");
_Static_assert(SPI_DPT_HEADER_SIZE == 14U && SPI_DPT_CRC_SIZE == 4U,
               "DPT header and CRC lengths are fixed");
_Static_assert(SPI_TEST_FRAME_SIZE <= UINT16_MAX,
               "The blocking HAL SPI length must fit uint16_t");

static inline void dpt_put_u32_le(uint8_t *dest, uint32_t value)
{
    for (unsigned i = 0U; i < 4U; ++i)
    {
        dest[i] = (uint8_t)(value >> (i * 8U));
    }
}

/* CRC-32/ISO-HDLC, compatible with Python zlib.crc32(). */
static inline uint32_t dpt_crc32(const uint8_t *data, size_t size)
{
    static const uint32_t nibble[16] = {
        0x00000000U, 0x1db71064U, 0x3b6e20c8U, 0x26d930acU,
        0x76dc4190U, 0x6b6b51f4U, 0x4db26158U, 0x5005713cU,
        0xedb88320U, 0xf00f9344U, 0xd6d6a3e8U, 0xcb61b38cU,
        0x9b64c2b0U, 0x86d3d2d4U, 0xa00ae278U, 0xbdbdf21cU
    };
    uint32_t crc = 0xffffffffU;

    for (size_t i = 0U; i < size; ++i)
    {
        crc ^= data[i];
        crc = (crc >> 4U) ^ nibble[crc & 15U];
        crc = (crc >> 4U) ^ nibble[crc & 15U];
    }
    return crc ^ 0xffffffffU;
}

/* Fill the payload before calling this; frame needs SPI_TEST_FRAME_SIZE bytes.
 * Write fields bytewise because uint32 fields at offsets 2/6/10 are unaligned.
 */
static inline uint32_t dpt_frame_finalize(uint8_t *frame, uint32_t sequence,
                                           uint32_t camera_ms)
{
    frame[0] = 0x01U;
    frame[1] = SPI_DPT_FORMAT;
    dpt_put_u32_le(frame + 2U, sequence);
    dpt_put_u32_le(frame + 6U, camera_ms);
    dpt_put_u32_le(frame + 10U, SPI_TEST_PAYLOAD_SIZE);

    const size_t crc_offset = SPI_DPT_HEADER_SIZE + SPI_TEST_PAYLOAD_SIZE;
    const uint32_t crc = dpt_crc32(frame, crc_offset);
    dpt_put_u32_le(frame + crc_offset, crc);
    for (size_t i = SPI_DPT_FRAME_SIZE; i < SPI_TEST_FRAME_SIZE; ++i)
    {
        frame[i] = 0U;
    }
    return crc;
}

#endif /* APOLLO_DPT_FRAME_H */
