#ifndef MAIN_DEPTH_UDP_H_
#define MAIN_DEPTH_UDP_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


/* Depth TX socket and PDK1 serialization only. Peer discovery lives in net_rx. */
bool depth_udp_init(void);
bool depth_udp_send_depth_chunk(const uint8_t *frame, uint32_t frame_bytes,
                                uint32_t session, uint32_t seq,
                                uint32_t rx_ms, uint32_t age_ms,
                                uint32_t offset, uint32_t peer_ipv4_be,
                                uint16_t peer_port, uint32_t *sent_bytes,
                                int *send_errno);
void depth_udp_deinit(void);

#endif
