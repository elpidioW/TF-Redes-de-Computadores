"""
server.py - Servidor do chat Mini-NET.
Recebe mensagens, mostra no terminal e envia ACKs.
"""

import queue
import socket
import threading
import time

from mini_net import (
    SERVER_ADDR,
    ROUTER_ADDR,
    CLIENT_VIP,
    CLIENT_B_VIP,
    SERVER_VIP,
    SERVER_MAC,
    ROUTER_MAC,
    DEFAULT_TTL,
    build_frame_bytes,
    parse_frame_bytes,
    send_frame,
    TIMEOUT_SECONDS,
    colorize,
    ANSI_RED,
    ANSI_YELLOW,
    ANSI_GREEN,
    MAX_TIMEOUT_SECONDS,
    BACKOFF_FACTOR,
)


def send_with_retry(sock, dst_vip, payload, seq_state, ack_events, lock):
    """Envia dados ao cliente com Stop-and-Wait e espera ACK."""
    seq = seq_state[dst_vip]

    frame = build_frame_bytes(
        payload=payload,
        seq_num=seq,
        is_ack=False,
        src_vip=SERVER_VIP,
        dst_vip=dst_vip,
        ttl=DEFAULT_TTL,
        src_mac=SERVER_MAC,
        dst_mac=ROUTER_MAC,
    )

    event = threading.Event()
    with lock:
        ack_events[(dst_vip, seq)] = event

    try:
        timeout = TIMEOUT_SECONDS
        while True:
            print(colorize(f"[TRANSPORTE] Enviando para {dst_vip} seq={seq}", ANSI_YELLOW))
            send_frame(sock, frame, ROUTER_ADDR)

            if event.wait(timeout):
                print(colorize(f"[TRANSPORTE] ACK recebido de {dst_vip} seq={seq}", ANSI_GREEN))
                seq_state[dst_vip] = 1 - seq
                break

            print(colorize(f"[TRANSPORTE] Timeout para {dst_vip}. Retransmitindo...", ANSI_YELLOW))
            timeout = min(MAX_TIMEOUT_SECONDS, timeout * BACKOFF_FACTOR)
    finally:
        with lock:
            ack_events.pop((dst_vip, seq), None)


def sender_worker(sock, dst_vip, send_queue, seq_state, ack_events, ack_lock):
    while True:
        payload = send_queue.get()
        if payload is None:
            break
        send_with_retry(sock, dst_vip, payload, seq_state, ack_events, ack_lock)


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(SERVER_ADDR)

    expected_seq = {CLIENT_VIP: 0, CLIENT_B_VIP: 0}
    tx_seq = {CLIENT_VIP: 0, CLIENT_B_VIP: 0}
    ack_events = {}
    ack_lock = threading.Lock()
    clients = {CLIENT_VIP, CLIENT_B_VIP}
    send_queues = {vip: queue.Queue() for vip in clients}

    for vip in clients:
        threading.Thread(
            target=sender_worker,
            args=(sock, vip, send_queues[vip], tx_seq, ack_events, ack_lock),
            daemon=True,
        ).start()

    print("Mini-NET Servidor iniciado.")

    while True:
        data, _ = sock.recvfrom(65535)

        frame_dict, packet_dict, segment_dict, ok = parse_frame_bytes(data)
        if not ok:
            print(colorize("[ENLACE] Quadro corrompido. Descartando silenciosamente.", ANSI_RED))
            continue

        if packet_dict.get("dst_vip") != SERVER_VIP:
            continue

        if segment_dict.get("is_ack", False):
            src_vip = packet_dict.get("src_vip")
            seq_num = segment_dict.get("seq_num")
            with ack_lock:
                event = ack_events.get((src_vip, seq_num))
                if event:
                    event.set()
            continue

        seq_num = segment_dict.get("seq_num")
        payload = segment_dict.get("payload") or {}
        src_vip = packet_dict.get("src_vip")

        is_new = seq_num == expected_seq.get(src_vip, 0)

        if is_new:
            msg = payload.get("message", "")
            sender = payload.get("sender", src_vip or "desconhecido")
            ts = payload.get("timestamp", time.time())
            print(colorize(f"[APLICAÇÃO] {sender} @ {ts:.3f}: {msg}", ANSI_GREEN))
            expected_seq[src_vip] = 1 - expected_seq.get(src_vip, 0)
        else:
            print(colorize(f"[TRANSPORTE] Duplicata recebida de {src_vip} seq={seq_num}.", ANSI_YELLOW))

        ack_payload = {"type": "ack"}
        ack_frame = build_frame_bytes(
            payload=ack_payload,
            seq_num=seq_num,
            is_ack=True,
            src_vip=SERVER_VIP,
            dst_vip=src_vip,
            ttl=DEFAULT_TTL,
            src_mac=SERVER_MAC,
            dst_mac=ROUTER_MAC,
        )

        print(colorize(f"[TRANSPORTE] Enviando ACK para {src_vip} seq={seq_num}", ANSI_YELLOW))
        send_frame(sock, ack_frame, ROUTER_ADDR)

        if not is_new:
            continue

        target = payload.get("to")
        if target:
            destinations = [target]
        else:
            destinations = [vip for vip in clients if vip != src_vip]

        forward_payload = {
            "type": "msg",
            "sender": sender,
            "message": msg,
            "timestamp": ts,
        }

        for dst_vip in destinations:
            if dst_vip not in clients:
                print(colorize(f"[REDE] Destino inválido: {dst_vip}", ANSI_RED))
                continue
            send_queues[dst_vip].put(forward_payload)


if __name__ == "__main__":
    main()
