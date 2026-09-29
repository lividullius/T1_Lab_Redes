import argparse
import socket
import time

DEFAULT_TIMEOUT = 10


def build_request(path, host, keep_alive):
    # Connection: close força o servidor a fechar o socket após responder
    # (usado em C1, e na última requisição de C2, para não deixar a conexão pendurada até o timeout de ociosidade do servidor).
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}",
        f"Connection: {'keep-alive' if keep_alive else 'close'}",
        "",
        "",  # linha em branco final -> CRLFCRLF, marca o fim dos headers
    ]
    return "\r\n".join(lines).encode("ascii")


def recv_response(sock):
    # TCP entrega um fluxo de bytes, não mensagens prontas: um único recv() pode trazer a resposta incompleta. 
    # Por isso acumulamos em `buffer` até encontrar a linha em branco (\r\n\r\n) que fecha a seção de headers.
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            return buffer
        buffer += chunk

    header_end = buffer.index(b"\r\n\r\n") + 4
    headers = buffer[:header_end].decode("iso-8859-1")
    body = buffer[header_end:]

    # Em C2 a mesma conexão é reaproveitada para as próximas requisições,
    # então é essencial saber exatamente onde este corpo termina (via
    # Content-Length) para não misturar bytes desta resposta com o início da próxima.
    content_length = 0
    for line in headers.split("\r\n")[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            content_length = int(value.strip())
            break

    while len(body) < content_length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk

    return buffer[:header_end] + body


def run_c1(host, port, path, count):
    # Cenário 1 (C1): uma conexão TCP nova para cada requisição. Isso significa
    # um handshake (SYN/SYN-ACK/ACK) completo por requisição, mais o
    # encerramento da conexão (FIN/ACK) logo em seguida — é esse overhead que a captura do Wireshark deve evidenciar.
    timings = []
    start_all = time.perf_counter()
    for i in range(count):
        t0 = time.perf_counter()
        with socket.create_connection((host, port), timeout=DEFAULT_TIMEOUT) as sock:
            sock.sendall(build_request(path, host, keep_alive=False))
            recv_response(sock)
        t1 = time.perf_counter()
        timings.append(t1 - t0)
        print(f"[C1] requisicao {i + 1}/{count}: {t1 - t0:.4f}s")
    total = time.perf_counter() - start_all
    return timings, total


def run_c2(host, port, path, count):
    # Cenário 2 (C2): uma única conexão TCP (um só handshake) é reaproveitada
    # para as `count` requisições, enviadas sequencialmente (espera a resposta completa antes de mandar a próxima). 
    # Só a última requisição pede Connection: close, para fechar a conexão de forma limpa no final.
    timings = []
    start_all = time.perf_counter()
    with socket.create_connection((host, port), timeout=DEFAULT_TIMEOUT) as sock:
        for i in range(count):
            t0 = time.perf_counter()
            last = i == count - 1
            sock.sendall(build_request(path, host, keep_alive=not last))
            recv_response(sock)
            t1 = time.perf_counter()
            timings.append(t1 - t0)
            print(f"[C2] requisicao {i + 1}/{count}: {t1 - t0:.4f}s")
    total = time.perf_counter() - start_all
    return timings, total


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Cliente de medicao HTTP/1.1: C1 abre uma conexao TCP nova por "
            "requisicao (Connection: close); C2 reusa uma unica conexao "
            "persistente para todas as requisicoes."
        )
    )
    parser.add_argument("--host", required=True, help="IP ou hostname do servidor")
    parser.add_argument("--port", type=int, required=True, help="Porta do servidor")
    parser.add_argument("--path", default="/", help="Recurso requisitado (ex: /index.html)")
    parser.add_argument("--scenario", choices=["c1", "c2"], required=True)
    parser.add_argument("--requests", type=int, default=10, help="Numero de requisicoes sequenciais")
    args = parser.parse_args()

    runner = run_c1 if args.scenario == "c1" else run_c2
    timings, total = runner(args.host, args.port, args.path, args.requests)

    print()
    print(f"Cenario: {args.scenario.upper()}")
    print(f"Requisicoes: {len(timings)}")
    print(f"Tempo total: {total:.4f}s")
    print(f"Tempo medio por requisicao: {sum(timings) / len(timings):.4f}s")


if __name__ == "__main__":
    main()
