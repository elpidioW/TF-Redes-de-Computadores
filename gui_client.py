"""
gui_client.py - Cliente com interface gráfica (Tkinter) para o Mini-NET.
"""

import argparse
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

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
    MAX_TIMEOUT_SECONDS,
    BACKOFF_FACTOR,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", choices=["A", "B"], default="A")
    parser.add_argument("--name", default=None)
    parser.add_argument("--to", dest="target", default=None)
    return parser.parse_args()


def receiver_loop(sock, self_vip, self_mac, ack_events, ack_lock, expected_in, ui_queue, stop_event):
    while not stop_event.is_set():
        try:
            data, _ = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break

        frame_dict, packet_dict, segment_dict, ok = parse_frame_bytes(data)
        if not ok:
            ui_queue.put(("log", "[ENLACE] Quadro inválido ou corrompido. Ignorando."))
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
            ui_queue.put(("msg", f"{sender} @ {ts:.3f}: {msg}"))
            expected_in["seq"] = 1 - expected_in["seq"]
        else:
            ui_queue.put(("log", f"[TRANSPORTE] Duplicata recebida seq={seq_num}."))

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


def send_with_retry(sock, frame_bytes, dst_vip, seq_num, ack_events, ack_lock, ui_queue):
    event = threading.Event()
    with ack_lock:
        ack_events[(dst_vip, seq_num)] = event

    try:
        timeout = TIMEOUT_SECONDS
        while True:
            ui_queue.put(("log", f"[TRANSPORTE] Enviando seq={seq_num}"))
            send_frame(sock, frame_bytes, ROUTER_ADDR)

            if event.wait(timeout):
                ui_queue.put(("log", f"[TRANSPORTE] ACK recebido seq={seq_num}"))
                return True

            ui_queue.put(("log", "[TRANSPORTE] Timeout. Retransmitindo..."))
            timeout = min(MAX_TIMEOUT_SECONDS, timeout * BACKOFF_FACTOR)
    finally:
        with ack_lock:
            ack_events.pop((dst_vip, seq_num), None)


def build_gui():
    root = tk.Tk()
    root.title("Mini-NET Chat")
    root.geometry("720x480")

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    main = ttk.Frame(root, padding=10)
    main.grid(row=0, column=0, sticky="nsew")
    main.columnconfigure(0, weight=1)
    main.rowconfigure(1, weight=1)

    top = ttk.Frame(main)
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(3, weight=1)

    ttk.Label(top, text="Nome:").grid(row=0, column=0, padx=(0, 6))
    name_var = tk.StringVar()
    name_entry = ttk.Entry(top, textvariable=name_var, width=16)
    name_entry.grid(row=0, column=1, padx=(0, 12))

    ttk.Label(top, text="Destino (VIP):").grid(row=0, column=2, padx=(0, 6))
    target_var = tk.StringVar()
    target_entry = ttk.Entry(top, textvariable=target_var, width=16)
    target_entry.grid(row=0, column=3, sticky="ew")

    log = tk.Text(main, state="disabled", height=12)
    log.grid(row=1, column=0, sticky="nsew", pady=8)

    bottom = ttk.Frame(main)
    bottom.grid(row=2, column=0, sticky="ew")
    bottom.columnconfigure(0, weight=1)

    msg_var = tk.StringVar()
    msg_entry = ttk.Entry(bottom, textvariable=msg_var)
    msg_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

    send_btn = ttk.Button(bottom, text="Enviar")
    send_btn.grid(row=0, column=1)

    return root, name_var, target_var, msg_var, log, send_btn, msg_entry


def main():
    args = parse_args()
    profile = CLIENTS[args.id]
    self_addr = profile["addr"]
    self_vip = profile["vip"]
    self_mac = profile["mac"]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:
        sock.bind(self_addr)
    except OSError as exc:
        print(
            "Erro ao abrir a porta do cliente. Outro processo já está usando o endereço.\n"
            "Feche outros clientes (CLI/GUI) e tente novamente."
        )
        print(f"Detalhe: {exc}")
        sys.exit(1)
    sock.settimeout(0.2)

    ack_events = {}
    ack_lock = threading.Lock()
    expected_in = {"seq": 0}
    seq_state = {"seq": 0}
    send_queue = queue.Queue()
    ui_queue = queue.Queue()
    stop_event = threading.Event()

    root, name_var, target_var, msg_var, log_widget, send_btn, msg_entry = build_gui()

    name_var.set(args.name or self_vip)
    if args.target:
        target_var.set(args.target)

    def append_text(text):
        log_widget.configure(state="normal")
        log_widget.insert("end", text + "\n")
        log_widget.see("end")
        log_widget.configure(state="disabled")

    def process_queue():
        try:
            while True:
                kind, text = ui_queue.get_nowait()
                if kind == "msg":
                    append_text(text)
                else:
                    append_text(text)
        except queue.Empty:
            pass
        if not stop_event.is_set():
            root.after(100, process_queue)

    def on_send(event=None):
        message = msg_var.get().strip()
        if not message:
            return

        target = target_var.get().strip() or None
        payload = {
            "type": "msg",
            "sender": name_var.get().strip() or self_vip,
            "message": message,
            "timestamp": time.time(),
        }
        if target:
            payload["to"] = target

        send_queue.put(payload)
        msg_var.set("")

    def on_close():
        stop_event.set()
        try:
            sock.close()
        finally:
            root.destroy()

    send_btn.configure(command=on_send)
    msg_entry.bind("<Return>", on_send)

    def sender_worker():
        while not stop_event.is_set():
            try:
                payload = send_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            seq = seq_state["seq"]
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
            if send_with_retry(sock, frame_bytes, SERVER_VIP, seq, ack_events, ack_lock, ui_queue):
                seq_state["seq"] = 1 - seq

    threading.Thread(
        target=receiver_loop,
        args=(sock, self_vip, self_mac, ack_events, ack_lock, expected_in, ui_queue, stop_event),
        daemon=True,
    ).start()
    threading.Thread(target=sender_worker, daemon=True).start()

    root.after(100, process_queue)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
