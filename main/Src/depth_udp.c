#include <errno.h>
#include <string.h>
#include <fcntl.h>

#include "esp_log.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"

#include "Inc/depth_udp.h"

#define UDP_CHUNK_BYTES 1200U
#define PDK1_HEADER_BYTES 40U
static const char *TAG = "depth_udp";
static int s_socket = -1;

static void put16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

static void put32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (i * 8));
}

bool depth_udp_init(void)
{
    if (s_socket >= 0) return true;
    int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (fd < 0) {
        ESP_LOGE(TAG, "Unable to create UDP TX socket: errno %d", errno);
        return false;
    }
    if (fcntl(fd, F_SETFL, O_NONBLOCK) < 0) {
        int saved_errno = errno;
        close(fd);
        errno = saved_errno;
        return false;
    }
    s_socket = fd;
    ESP_LOGI(TAG, "Depth UDP transmitter ready");
    return true;
}

static bool send_packet(const void *data, size_t length,
                        uint32_t peer_ipv4_be, uint16_t peer_port,
                        int *send_errno)
{
    if (send_errno) *send_errno = 0;
    if (s_socket < 0 || !peer_ipv4_be || !peer_port) {
        if (send_errno) *send_errno = ENOTCONN;
        return false;
    }
    struct sockaddr_in destination = {
        .sin_family = AF_INET,
        .sin_port = htons(peer_port),
        .sin_addr.s_addr = peer_ipv4_be,
    };
    int sent = sendto(s_socket, data, length, 0,
                      (const struct sockaddr *)&destination, sizeof(destination));
    if (sent != (int)length) {
        if (send_errno) *send_errno = (sent < 0) ? errno : EIO;
        return false;
    }
    return true;
}

bool depth_udp_send_depth_chunk(const uint8_t *frame, uint32_t frame_bytes,
                                uint32_t session, uint32_t seq,
                                uint32_t rx_ms, uint32_t age_ms,
                                uint32_t offset, uint32_t peer_ipv4_be,
                                uint16_t peer_port, uint32_t *sent_bytes,
                                int *send_errno)
{
    if (!frame || offset >= frame_bytes || !sent_bytes) {
        if (send_errno) *send_errno = EINVAL;
        return false;
    }
    uint32_t bytes = frame_bytes - offset;
    if (bytes > UDP_CHUNK_BYTES) bytes = UDP_CHUNK_BYTES;

    uint8_t packet[PDK1_HEADER_BYTES + UDP_CHUNK_BYTES] = {0};
    memcpy(packet, "PDK1", 4);
    packet[4] = 1;
    packet[5] = 2;
    put16(packet + 6, PDK1_HEADER_BYTES);
    put32(packet + 8, session);
    put32(packet + 12, seq);
    put32(packet + 16, frame_bytes);
    put32(packet + 20, offset);
    put16(packet + 24, (uint16_t)bytes);
    put16(packet + 26, (uint16_t)(offset / UDP_CHUNK_BYTES));
    put16(packet + 28, (uint16_t)((frame_bytes + UDP_CHUNK_BYTES - 1) / UDP_CHUNK_BYTES));
    put32(packet + 32, rx_ms);
    put32(packet + 36, age_ms);
    memcpy(packet + PDK1_HEADER_BYTES, frame + offset, bytes);

    if (!send_packet(packet, PDK1_HEADER_BYTES + bytes,
                     peer_ipv4_be, peer_port, send_errno)) return false;
    *sent_bytes = bytes;
    return true;
}

void depth_udp_deinit(void)
{
    if (s_socket >= 0) {
        shutdown(s_socket, 0);
        close(s_socket);
        s_socket = -1;
    }
}
