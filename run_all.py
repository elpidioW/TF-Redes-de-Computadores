"""
run_all.py - Inicia roteador, servidor e dois clientes GUI em um só comando.
"""

import subprocess
import sys
import time


def start(cmd, title):
    print(f"Iniciando: {title}")
    return subprocess.Popen(cmd)


def main():
    python = sys.executable

    procs = []
    try:
        procs.append(start([python, "router.py"], "Roteador"))
        time.sleep(0.3)
        procs.append(start([python, "server.py"], "Servidor"))
        time.sleep(0.3)
        procs.append(start([python, "gui_client.py", "--id", "A"], "Cliente GUI A"))
        time.sleep(0.3)
        procs.append(start([python, "gui_client.py", "--id", "B"], "Cliente GUI B"))

        print("Todos os processos iniciados. Feche esta janela para encerrar tudo.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Encerrando...")
    finally:
        for proc in procs:
            proc.terminate()


if __name__ == "__main__":
    main()
