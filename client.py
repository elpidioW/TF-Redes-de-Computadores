"""
client.py - Cliente do chat Mini-NET.
Camadas: Aplicação -> Transporte (Stop-and-Wait) -> Rede -> Enlace -> Física.
"""

import argparse
import socket
import threading
import time

from mini_net import (
    ROUTER_ADDR,
    SERVER_VIP,
    ROUTER_MAC,
    DEFAULT_TTL,
    TIMEOUT_SECONDS,
    build_frame_bytes,
    parse_frame_bytes,
    send_frame,
    CLIENTS,
    colorize,
    ANSI_YELLOW,
    ANSI_GREEN,
    ANSI_RED,
    MAX_TIMEOUT_SECONDS,
    BACKOFF_FACTOR,
)


def receiver_loop(sock, self_vip, self_mac, ack_events, ack_lock, expected_in):
    """Processa recebimentos: dados do servidor e ACKs."""
    while True:
        try:
            data, _ = sock.recvfrom(65535)
        except OSError:
            break

        frame_dict, packet_dict, segment_dict, ok = parse_frame_bytes(data)
        if not ok:
            print(colorize("[ENLACE] Quadro inválido ou corrompido. Ignorando.", ANSI_RED))
            continue

        if packet_dict.get("dst_vip") != self_vip:
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

        if seq_num == expected_in["seq"]:
            sender = payload.get("sender", "desconhecido")
            msg = payload.get("message", "")
            ts = payload.get("timestamp", time.time())
            print(colorize(f"\n[APLICAÇÃO] {sender} @ {ts:.3f}: {msg}\n> ", ANSI_GREEN), end="")
            expected_in["seq"] = 1 - expected_in["seq"]
        else:
            print(colorize(f"[TRANSPORTE] Duplicata recebida seq={seq_num}. Reenviando ACK.", ANSI_YELLOW))

        ack_frame = build_frame_bytes(
            payload={"type": "ack"},
            seq_num=seq_num,
            is_ack=True,
            src_vip=self_vip,
            dst_vip=SERVER_VIP,
            ttl=DEFAULT_TTL,
            src_mac=self_mac,
            dst_mac=ROUTER_MAC,
        )
        send_frame(sock, ack_frame, ROUTER_ADDR)


def send_with_retry(sock, frame_bytes, dst_vip, seq_num, ack_events, ack_lock):
    event = threading.Event()
    with ack_lock:
        ack_events[(dst_vip, seq_num)] = event

    try:
        timeout = TIMEOUT_SECONDS
        while True:
            print(colorize(f"[TRANSPORTE] Enviando seq={seq_num}", ANSI_YELLOW))
            send_frame(sock, frame_bytes, ROUTER_ADDR)

            if event.wait(timeout):
                print(colorize(f"[TRANSPORTE] ACK recebido para seq={seq_num}", ANSI_GREEN))
                return True

            print(colorize("[TRANSPORTE] Timeout/ACK inválido. Retransmitindo...", ANSI_YELLOW))
            timeout = min(MAX_TIMEOUT_SECONDS, timeout * BACKOFF_FACTOR)
    finally:
        with ack_lock:
            ack_events.pop((dst_vip, seq_num), None)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", choices=["A", "B"], default="A")
    parser.add_argument("--name", default=None)
    parser.add_argument("--to", dest="target", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    profile = CLIENTS[args.id]
    self_addr = profile["addr"]
    self_vip = profile["vip"]
    self_mac = profile["mac"]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(self_addr)

    ack_events = {}
    ack_lock = threading.Lock()
    expected_in = {"seq": 0}
    seq = 0

    threading.Thread(
        target=receiver_loop,
        args=(sock, self_vip, self_mac, ack_events, ack_lock, expected_in),
        daemon=True,
    ).start()

    name = args.name or self_vip
    default_target = args.target

    print("Mini-NET Cliente iniciado. Digite mensagens (ou 'sair' para encerrar).")
    print("Use /to VIP mensagem para escolher o destino.")

    try:
        while True:
            msg = input("> ").strip()
            if msg.lower() in {"sair", "exit", "quit"}:
                break

            target = default_target
            if msg.startswith("/to "):
                parts = msg.split(" ", 2)
                if len(parts) < 3:
                    print("Uso: /to VIP mensagem")
                    continue
                target = parts[1]
                msg = parts[2]

            payload = {
                "type": "msg",
                "sender": name,
                "message": msg,
                "timestamp": time.time(),
            }
            if target:
                payload["to"] = target

            frame_bytes = build_frame_bytes(
                payload=payload,
                seq_num=seq,
                is_ack=False,
                src_vip=self_vip,
                dst_vip=SERVER_VIP,
                ttl=DEFAULT_TTL,
                src_mac=self_mac,
                dst_mac=ROUTER_MAC,
            )

            if send_with_retry(sock, frame_bytes, SERVER_VIP, seq, ack_events, ack_lock):
                seq = 1 - seq

    finally:
        sock.close()
        print("Cliente encerrado.")


if __name__ == "__main__":
    main()
