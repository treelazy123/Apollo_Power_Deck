#include <errno.h>
#include <fcntl.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"

#include "Inc/deck_config.h"
#include "Inc/net_rx.h"
#include "Inc/wifi_sta.h"

/* Text transport only; no device command semantics are defined here. */
#define MESSAGE_HEADER_BYTES 10U
#define MESSAGE_MAX_BYTES 512U

static const char *TAG = "net_rx";
static int s_socket = -1;
static net_rx_status_t s_status;
static portMUX_TYPE s_status_lock = portMUX_INITIALIZER_UNLOCKED;
/* The following lease fields are accessed only by net_rx_task. */
static bool s_was_wifi_connected;
static uint32_t s_peer_seen_ms;

void net_rx_get_status(net_rx_status_t *status)
{
    if (!status) return;
    portENTER_CRITICAL(&s_status_lock);
    *status = s_status;
    portEXIT_CRITICAL(&s_status_lock);
}

static bool open_rx_socket(void)
{
    if (s_socket >= 0) return true;
    int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (fd < 0) {
        ESP_LOGE(TAG, "Unable to create UDP RX socket: errno %d", errno);
        return false;
    }
    struct sockaddr_in local = {
        .sin_family = AF_INET,
        .sin_port = htons(STREAM_DISCOVERY_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(fd, (struct sockaddr *)&local, sizeof(local)) < 0 ||
        fcntl(fd, F_SETFL, O_NONBLOCK) < 0) {
        int saved_errno = errno;
        close(fd);
        ESP_LOGE(TAG, "Unable to bind UDP RX port %u: errno %d",
                 STREAM_DISCOVERY_PORT, saved_errno);
        return false;
    }
    s_socket = fd;
    ESP_LOGI(TAG, "Listening for PDHELLO1 and PC text on UDP %u",
             STREAM_DISCOVERY_PORT);
    return true;
}

static void update_peer_lease(bool wifi_connected, uint32_t now_ms)
{
    portENTER_CRITICAL(&s_status_lock);
    if (!wifi_connected) {
        if (s_was_wifi_connected) ++s_status.peer_wifi_lost;
        s_was_wifi_connected = false;
        s_status.have_peer = false;
    } else {
        s_was_wifi_connected = true;
        if (s_status.have_peer &&
            (uint32_t)(now_ms - s_peer_seen_ms) > STREAM_PEER_LEASE_MS) {
            s_status.have_peer = false;
            ++s_status.peer_expired;
        }
    }
    portEXIT_CRITICAL(&s_status_lock);
}

static void receive_hello(const struct sockaddr_in *from, uint32_t now_ms)
{
    bool new_peer = false;
    portENTER_CRITICAL(&s_status_lock);
    if (!s_status.have_peer ||
        (from->sin_addr.s_addr == s_status.peer_ipv4_be &&
         ntohs(from->sin_port) == s_status.peer_port)) {
        new_peer = !s_status.have_peer;
        s_status.peer_ipv4_be = from->sin_addr.s_addr;
        s_status.peer_port = ntohs(from->sin_port);
        s_peer_seen_ms = now_ms;
        s_status.have_peer = true;
    }
    portEXIT_CRITICAL(&s_status_lock);
    if (new_peer) {
        ESP_LOGI(TAG, "PC receiver %s:%u", inet_ntoa(from->sin_addr),
                 ntohs(from->sin_port));
    }
}

static void receive_pc_message(const uint8_t *packet, size_t length,
                               const struct sockaddr_in *from)
{
    if (length <= MESSAGE_HEADER_BYTES ||
        length > MESSAGE_HEADER_BYTES + MESSAGE_MAX_BYTES ||
        memcmp(packet, "PDMSG1", 6) != 0) return;

    net_rx_status_t peer;
    net_rx_get_status(&peer);
    if (!peer.have_peer || from->sin_addr.s_addr != peer.peer_ipv4_be ||
        ntohs(from->sin_port) != peer.peer_port) return;

    const char *text = (const char *)packet + MESSAGE_HEADER_BYTES;
    size_t text_length = length - MESSAGE_HEADER_BYTES;
    if (memchr(text, '\0', text_length)) return;
    uint32_t id = (uint32_t)packet[6] | ((uint32_t)packet[7] << 8) |
                  ((uint32_t)packet[8] << 16) | ((uint32_t)packet[9] << 24);
    /* Future device command handling belongs here, outside net_tx_task. */
    ESP_LOGI(TAG, "PC message id=%lu from=%s:%u bytes=%u text=%.*s",
             (unsigned long)id, inet_ntoa(from->sin_addr), ntohs(from->sin_port),
             (unsigned)text_length, (int)text_length, text);
    portENTER_CRITICAL(&s_status_lock);
    ++s_status.messages_received;
    portEXIT_CRITICAL(&s_status_lock);

    uint8_t ack[MESSAGE_HEADER_BYTES];
    memcpy(ack, "PDACK1", 6);
    memcpy(ack + 6, packet + 6, 4);
    int sent = sendto(s_socket, ack, sizeof(ack), 0,
                      (const struct sockaddr *)from, sizeof(*from));
    if (sent != (int)sizeof(ack)) {
        int saved_errno = sent < 0 ? errno : EIO;
        portENTER_CRITICAL(&s_status_lock);
        ++s_status.ack_errors;
        portEXIT_CRITICAL(&s_status_lock);
        ESP_LOGW(TAG, "PC message ACK failed id=%lu errno=%d",
                 (unsigned long)id, saved_errno);
    }
}

static void poll_datagrams(void)
{
    for (unsigned i = 0; i < 4; ++i) {
        /* One extra byte makes oversized/truncated messages rejectable. */
        uint8_t packet[MESSAGE_HEADER_BYTES + MESSAGE_MAX_BYTES + 1];
        struct sockaddr_in from;
        socklen_t from_len = sizeof(from);
        int length = recvfrom(s_socket, packet, sizeof(packet), 0,
                               (struct sockaddr *)&from, &from_len);
        if (length < 0) {
            int saved_errno = errno;
            if (saved_errno != EAGAIN && saved_errno != EWOULDBLOCK &&
                saved_errno != EINTR) {
                ESP_LOGE(TAG, "UDP receive failed: errno %d", saved_errno);
                close(s_socket);
                s_socket = -1;
                portENTER_CRITICAL(&s_status_lock);
                s_status.have_peer = false;
                portEXIT_CRITICAL(&s_status_lock);
            }
            break;
        }
        if (length == 8 && memcmp(packet, "PDHELLO1", 8) == 0) {
            receive_hello(&from, (uint32_t)(esp_timer_get_time() / 1000));
        } else {
            receive_pc_message(packet, (size_t)length, &from);
        }
    }
}

void net_rx_task(void *arg)
{
    (void)arg;
    for (;;) {
        bool wifi_connected = wifi_sta_connected();
        update_peer_lease(wifi_connected, (uint32_t)(esp_timer_get_time() / 1000));
        if (!open_rx_socket()) {
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        if (wifi_connected) poll_datagrams();
        vTaskDelay(1);
    }
}
