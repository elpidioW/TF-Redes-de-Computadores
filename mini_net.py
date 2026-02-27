"""
mini_net.py - Utilitários e constantes compartilhadas do Projeto Mini-NET.
"""

from protocol import Segmento, Pacote, Quadro, enviar_pela_rede_ruidosa

# Endereços reais (IP/Porta)
HOST = "127.0.0.1"
ROUTER_ADDR = (HOST, 9000)
SERVER_ADDR = (HOST, 9001)
CLIENT_ADDR = (HOST, 9002)
CLIENT_B_ADDR = (HOST, 9003)

# Endereços virtuais (VIP)
CLIENT_VIP = "HOST_A"
CLIENT_B_VIP = "HOST_B"
SERVER_VIP = "SERVIDOR_PRIME"
ROUTER_VIP = "ROTEADOR"

# Endereços MAC fictícios
CLIENT_MAC = "AA:AA:AA:AA:AA:AA"
CLIENT_B_MAC = "DD:DD:DD:DD:DD:DD"
SERVER_MAC = "BB:BB:BB:BB:BB:BB"
ROUTER_MAC = "CC:CC:CC:CC:CC:CC"

# Parâmetros do protocolo
DEFAULT_TTL = 8
TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 6.0
BACKOFF_FACTOR = 1.5

CLIENTS = {
    "A": {"addr": CLIENT_ADDR, "vip": CLIENT_VIP, "mac": CLIENT_MAC},
    "B": {"addr": CLIENT_B_ADDR, "vip": CLIENT_B_VIP, "mac": CLIENT_B_MAC},
}

# Cores ANSI para logs
ANSI_RESET = "\033[0m"
ANSI_RED = "\033[31m"
ANSI_YELLOW = "\033[33m"
ANSI_GREEN = "\033[32m"
ANSI_CYAN = "\033[36m"


def colorize(text, color_code):
    return f"{color_code}{text}{ANSI_RESET}"


def build_frame_bytes(payload, seq_num, is_ack, src_vip, dst_vip, ttl, src_mac, dst_mac):
    """Encapsula o payload da aplicação em Segmento->Pacote->Quadro e serializa."""
    segmento = Segmento(seq_num=seq_num, is_ack=is_ack, payload=payload).to_dict()
    pacote = Pacote(src_vip=src_vip, dst_vip=dst_vip, ttl=ttl, segmento_dict=segmento).to_dict()
    quadro = Quadro(src_mac=src_mac, dst_mac=dst_mac, pacote_dict=pacote)
    return quadro.serializar()


def parse_frame_bytes(bytes_data):
    """Deserializa um quadro e extrai frame, pacote e segmento."""
    frame_dict, ok = Quadro.deserializar(bytes_data)
    if not ok or frame_dict is None:
        return None, None, None, False

    pacote_dict = frame_dict.get("data")
    if not isinstance(pacote_dict, dict):
        return frame_dict, None, None, False

    segmento_dict = pacote_dict.get("data")
    if not isinstance(segmento_dict, dict):
        return frame_dict, pacote_dict, None, False

    return frame_dict, pacote_dict, segmento_dict, True


def send_frame(sock, frame_bytes, addr):
    """Envia o quadro pela rede ruidosa (obrigatório no projeto)."""
    enviar_pela_rede_ruidosa(sock, frame_bytes, addr)
