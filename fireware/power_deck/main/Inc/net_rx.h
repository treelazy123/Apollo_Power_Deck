#ifndef MAIN_NET_RX_H_
#define MAIN_NET_RX_H_

#include <stdbool.h>
#include <stdint.h>

/* A copied snapshot: no socket or mutable peer state is shared with TX. */
typedef struct {
    bool have_peer;
    uint32_t peer_ipv4_be;
    uint16_t peer_port;
    uint32_t peer_expired;
    uint32_t peer_wifi_lost;
    uint32_t messages_received;
    uint32_t ack_errors;
} net_rx_status_t;

/* Task entry; created by stream_tasks_start(). Owns UDP 5006 and discovery. */
void net_rx_task(void *arg);
void net_rx_get_status(net_rx_status_t *status);

#endif
