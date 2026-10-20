#include <string.h>
#include "Inc/depth_spi.h"
#include "driver/spi_slave.h"
#include "driver/gpio.h"

uint32_t depth_u32(const uint8_t *p)
{ return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
uint32_t depth_frame_sequence(const uint8_t *frame) { return depth_u32(frame + 2); }
depth_check_t depth_frame_check(const uint8_t *p)
{
    if(p[0]!=DEPTH_MAGIC_DPT ||
       p[1]!=DEPTH_TEST_FORMAT ||
       depth_u32(p+10)!=DEPTH_PAYLOAD_BYTES) return DEPTH_CHECK_HEADER;
    /* Tail padding is transport-only and must be zero. */
    for(unsigned i=DEPTH_FRAME_BYTES;i<DEPTH_SPI_BYTES;i++)
        if(p[i]!=0U) return DEPTH_CHECK_HEADER;
    static const uint32_t nibble[16]={
        0x00000000U,0x1db71064U,0x3b6e20c8U,0x26d930acU,
        0x76dc4190U,0x6b6b51f4U,0x4db26158U,0x5005713cU,
        0xedb88320U,0xf00f9344U,0xd6d6a3e8U,0xcb61b38cU,
        0x9b64c2b0U,0x86d3d2d4U,0xa00ae278U,0xbdbdf21cU
    };
    uint32_t crc=0xffffffffU;
    for(unsigned i=0;i<DEPTH_FRAME_BYTES-4U;i++) {
        crc^=p[i];
        crc=(crc>>4)^nibble[crc&15U];
        crc=(crc>>4)^nibble[crc&15U];
    }
    if((crc^0xffffffffU)!=depth_u32(p+DEPTH_FRAME_BYTES-4U)) return DEPTH_CHECK_CRC;
    /* Payload is opaque in every profile; CRC verifies byte integrity. */
    return DEPTH_CHECK_OK;
}

/* Only depth_rx_task owns the descriptors. UDP may retain the frame buffers,
 * so a slot is requeued only after its frame index returns to free_q. */
static spi_slave_transaction_t transactions[DEPTH_FRAME_COUNT];
static bool in_flight[DEPTH_FRAME_COUNT];
static bool initialized;

_Static_assert(DEPTH_FRAME_COUNT > 0 && DEPTH_FRAME_COUNT <= UINT8_MAX,
               "frame indexes must fit in uint8_t");
_Static_assert((DEPTH_SPI_BYTES % 4U) == 0U, "SPI DMA wire length must be word aligned");

esp_err_t depth_spi_init(void)
{
    if (initialized) return ESP_ERR_INVALID_STATE;
    const spi_bus_config_t bus = {
        .mosi_io_num = DEPTH_GPIO_MOSI,
        .miso_io_num = -1, /* RX only; Apollo uses a separate CS input on GPIO4. */
        .sclk_io_num = DEPTH_GPIO_SCK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = DEPTH_RX_BUFFER_BYTES,
        .flags = SPICOMMON_BUSFLAG_GPIO_PINS,
    };
    const spi_slave_interface_config_t slave = {
        .spics_io_num = DEPTH_GPIO_CS,
        .queue_size = DEPTH_FRAME_COUNT,
        .mode = 0,
    };
    esp_err_t err = spi_slave_initialize(SPI2_HOST, &bus, &slave, SPI_DMA_CH_AUTO);
    if (err != ESP_OK) return err;

    /* All three C6 signal pins are inputs. CS must be idle high at startup. */
    err = gpio_set_pull_mode(DEPTH_GPIO_CS, GPIO_PULLUP_ONLY);
    if (err == ESP_OK) err = gpio_set_pull_mode(DEPTH_GPIO_SCK, GPIO_PULLDOWN_ONLY);
    if (err == ESP_OK) err = gpio_set_pull_mode(DEPTH_GPIO_MOSI, GPIO_PULLDOWN_ONLY);
    if (err != ESP_OK) {
        spi_slave_free(SPI2_HOST);
        return err;
    }
    initialized = true;
    return ESP_OK;
}

esp_err_t depth_spi_queue(uint8_t id, uint8_t *frame)
{
    if (!initialized) return ESP_ERR_INVALID_STATE;
    if (id >= DEPTH_FRAME_COUNT || !frame || ((uintptr_t)frame & 3U))
        return ESP_ERR_INVALID_ARG;
    if (in_flight[id]) return ESP_ERR_INVALID_STATE;

    spi_slave_transaction_t *trans = &transactions[id];
    memset(trans, 0, sizeof(*trans));
    /* One guard word lets us reject overlong CS transactions as well as short
     * frames. trans_len is capped at length, so capacity must exceed wire size. */
    trans->length = DEPTH_RX_BUFFER_BYTES * 8U;
    trans->rx_buffer = frame;
    trans->user = (void *)(uintptr_t)id;
    esp_err_t err = spi_slave_queue_trans(SPI2_HOST, trans, 0);
    if (err == ESP_OK) in_flight[id] = true;
    return err;
}

esp_err_t depth_spi_receive(uint8_t *id, size_t *received_bits)
{
    if (!initialized) return ESP_ERR_INVALID_STATE;
    if (!id || !received_bits) return ESP_ERR_INVALID_ARG;
    spi_slave_transaction_t *done = NULL;
    esp_err_t err = spi_slave_get_trans_result(SPI2_HOST, &done, portMAX_DELAY);
    if (err != ESP_OK) return err;
    uint8_t slot = (uint8_t)(uintptr_t)done->user;
    configASSERT(slot < DEPTH_FRAME_COUNT && done == &transactions[slot] && in_flight[slot]);
    in_flight[slot] = false;
    *id = slot;
    *received_bits = done->trans_len;
    return ESP_OK;
}
