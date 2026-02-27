"""
router.py - Roteador Mini-NET.
Encaminha pacotes com base no VIP de destino.
"""

import socket

from mini_net import (
    ROUTER_ADDR,
    CLIENT_ADDR,
    CLIENT_B_ADDR,
    SERVER_ADDR,
    CLIENT_VIP,
    CLIENT_B_VIP,
    SERVER_VIP,
    CLIENT_MAC,
    CLIENT_B_MAC,
    SERVER_MAC,
    ROUTER_MAC,
    build_frame_bytes,
    parse_frame_bytes,
    send_frame,
    colorize,
    ANSI_RED,
    ANSI_YELLOW,
    ANSI_CYAN,
)


ROUTING_TABLE = {
    CLIENT_VIP: {"next_hop": CLIENT_ADDR, "dst_mac": CLIENT_MAC},
    CLIENT_B_VIP: {"next_hop": CLIENT_B_ADDR, "dst_mac": CLIENT_B_MAC},
    SERVER_VIP: {"next_hop": SERVER_ADDR, "dst_mac": SERVER_MAC},
}


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(ROUTER_ADDR)

    print("Mini-NET Roteador iniciado.")

    while True:
        data, _ = sock.recvfrom(65535)

        frame_dict, packet_dict, segment_dict, ok = parse_frame_bytes(data)
        if not ok:
            print(colorize("[ENLACE] Quadro inválido. Descartando.", ANSI_RED))
            continue

        if frame_dict.get("dst_mac") != ROUTER_MAC:
            continue

        dst_vip = packet_dict.get("dst_vip")
        ttl = packet_dict.get("ttl", 0)

        if ttl <= 0:
            print(colorize("[REDE] TTL expirado. Descartando pacote.", ANSI_YELLOW))
            continue

        route = ROUTING_TABLE.get(dst_vip)
        if not route:
            print(colorize(f"[REDE] Sem rota para {dst_vip}. Descartando.", ANSI_RED))
            continue

        new_ttl = ttl - 1

        new_frame = build_frame_bytes(
            payload=segment_dict.get("payload"),
            seq_num=segment_dict.get("seq_num"),
            is_ack=segment_dict.get("is_ack"),
            src_vip=packet_dict.get("src_vip"),
            dst_vip=dst_vip,
            ttl=new_ttl,
            src_mac=ROUTER_MAC,
            dst_mac=route["dst_mac"],
        )

        print(colorize(f"[REDE] Encaminhando para {dst_vip} TTL={new_ttl}", ANSI_CYAN))
        send_frame(sock, new_frame, route["next_hop"])


if __name__ == "__main__":
    main()
