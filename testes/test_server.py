#!/usr/bin/env python3
"""
Script de verificação manual de conformidade do servidor.

Dispara, via socket TCP cru (sem bibliotecas HTTP), as requisições que
produzem cada código de status obrigatório e as três tentativas de path
traversal, e confere se a resposta bate com o esperado. Serve de checklist
rápido antes da sessão de medição com a outra máquina, e a saída pode ser
colada direto na tabela de conformidade do relatório.

Uso:
    python3 testes/test_server.py --host 127.0.0.1 --port 8080
"""
import argparse
import socket

# Tempo máximo (s) esperando uma resposta antes de considerar falha
TIMEOUT = 5


def send_raw(host, port, request_bytes):
    """Abre uma conexão nova, envia os bytes crus da requisição e devolve a
    resposta (ou só o que chegou, se o servidor fechar antes)."""
    with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
        sock.sendall(request_bytes)
        chunks = []
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout:
            # Conexão keep-alive: o servidor não fecha por conta própria,
            # então o timeout aqui só marca "acabou de chegar o que tinha".
            pass
        return b"".join(chunks)


def status_code(response):
    """Extrai o código numérico da status-line (ex: b'HTTP/1.1 404 Not Found\\r\\n...' -> 404)."""
    if not response:
        return None
    first_line = response.split(b"\r\n", 1)[0]
    parts = first_line.split(b" ")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def header_value(response, name):
    """Procura um header pelo nome (case-insensitive) e devolve seu valor, ou None."""
    head = response.split(b"\r\n\r\n", 1)[0]
    for line in head.split(b"\r\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == name.lower().encode():
            return value.strip().decode("iso-8859-1")
    return None


def run_case(name, host, port, request_lines, expected_status, expect_header=None):
    """Monta a requisição a partir das linhas dadas, envia e compara com o esperado."""
    request = ("\r\n".join(request_lines) + "\r\n\r\n").encode("iso-8859-1")
    response = send_raw(host, port, request)
    got_status = status_code(response)
    ok = got_status == expected_status
    if ok and expect_header:
        header_name, expected_value = expect_header
        ok = header_value(response, header_name) == expected_value

    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}: esperado {expected_status}, obtido {got_status}")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Checklist de conformidade do servidor HTTP.")
    parser.add_argument("--host", required=True, help="IP ou hostname do servidor")
    parser.add_argument("--port", type=int, required=True, help="Porta do servidor")
    args = parser.parse_args()
    host, port = args.host, args.port

    results = []

    # 200 OK — GET de um recurso existente
    results.append(run_case(
        "GET /index.html -> 200",
        host, port,
        [f"GET /index.html HTTP/1.1", f"Host: {host}", "Connection: close"],
        200,
    ))

    # 200 OK sem corpo — HEAD do mesmo recurso
    results.append(run_case(
        "HEAD /index.html -> 200 (sem corpo)",
        host, port,
        [f"HEAD /index.html HTTP/1.1", f"Host: {host}", "Connection: close"],
        200,
    ))

    # 404 Not Found — recurso inexistente
    results.append(run_case(
        "GET /naoexiste.html -> 404",
        host, port,
        [f"GET /naoexiste.html HTTP/1.1", f"Host: {host}", "Connection: close"],
        404,
    ))

    # 405 Method Not Allowed — método não suportado, com Allow: GET, HEAD
    results.append(run_case(
        "DELETE /index.html -> 405 (Allow: GET, HEAD)",
        host, port,
        [f"DELETE /index.html HTTP/1.1", f"Host: {host}", "Connection: close"],
        405,
        expect_header=("Allow", "GET, HEAD"),
    ))

    # 400 Bad Request — request-line sem a versão HTTP
    results.append(run_case(
        "GET /index.html (sem versão) -> 400",
        host, port,
        [f"GET /index.html", f"Host: {host}", "Connection: close"],
        400,
    ))

    # 403 Forbidden — três tentativas de path traversal distintas
    results.append(run_case(
        "GET /../../etc/passwd -> 403 (travessia direta)",
        host, port,
        [f"GET /../../etc/passwd HTTP/1.1", f"Host: {host}", "Connection: close"],
        403,
    ))
    results.append(run_case(
        "GET /%2e%2e/%2e%2e/etc/passwd -> 403 (percent-encoding em '..')",
        host, port,
        [f"GET /%2e%2e/%2e%2e/etc/passwd HTTP/1.1", f"Host: {host}", "Connection: close"],
        403,
    ))
    results.append(run_case(
        "GET /..%2f..%2fetc/passwd -> 403 (percent-encoding na barra)",
        host, port,
        [f"GET /..%2f..%2fetc/passwd HTTP/1.1", f"Host: {host}", "Connection: close"],
        403,
    ))

    total, passed = len(results), sum(results)
    print(f"\n{passed}/{total} casos OK")
    raise SystemExit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
