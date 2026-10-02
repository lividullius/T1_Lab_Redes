#!/usr/bin/env python3
import argparse
import email.utils
import os
import socket
import threading
import urllib.parse

SERVER_NAME = "T1-Lab-Redes/1.0"
IDLE_TIMEOUT = 5
MAX_HEAD_SIZE = 16384
RECV_SIZE = 4096

REASONS = {
    200: "OK",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
    505: "HTTP Version Not Supported",
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".pdf": "application/pdf",
}


class HttpError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(REASONS[status])
        self.status = status
        self.headers = headers or {}


def http_date():
    # IMF-fixdate (RFC 9110), ex: "Sun, 06 Nov 1994 08:49:37 GMT"
    return email.utils.formatdate(usegmt=True)


def content_type_for(path):
    ext = os.path.splitext(path)[1].lower()
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def read_head(conn, buffer):
    """Acumula bytes do socket até CRLFCRLF. Retorna (head, sobra) ou (None, b"") se o cliente fechou."""
    while True:
        buffer = buffer.lstrip(b"\r\n")  # RFC 9112 permite CRLFs soltos antes da request-line
        if b"\r\n\r\n" in buffer:
            break
        if len(buffer) > MAX_HEAD_SIZE:
            raise HttpError(400)
        chunk = conn.recv(RECV_SIZE)
        if not chunk:
            if buffer:
                raise HttpError(400)
            return None, b""
        buffer += chunk
    head, _, rest = buffer.partition(b"\r\n\r\n")
    return head.decode("iso-8859-1"), rest


def parse_request(head):
    lines = head.split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3:
        raise HttpError(400)
    method, target, version = parts
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise HttpError(505 if version.startswith("HTTP/") else 400)

    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if not sep or not name or name != name.strip():
            raise HttpError(400)
        headers[name.lower()] = value.strip()
    return method, target, version, headers


def skip_body(conn, buffer, headers):
    """GET/HEAD não usam corpo, mas se vier um é descartado para não corromper a próxima requisição."""
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        raise HttpError(400)
    if length < 0:
        raise HttpError(400)
    while len(buffer) < length:
        chunk = conn.recv(RECV_SIZE)
        if not chunk:
            raise ConnectionError("cliente fechou no meio do corpo")
        buffer += chunk
    return buffer[length:]


def wants_keep_alive(version, headers):
    tokens = {t.strip().lower() for t in headers.get("connection", "").split(",")}
    if "close" in tokens:
        return False
    return version == "HTTP/1.1" or "keep-alive" in tokens


def resolve_path(root, target):
    path = urllib.parse.urlsplit(target).path
    if not path.startswith("/"):
        raise HttpError(400)
    path = urllib.parse.unquote(path)
    if "\0" in path:
        raise HttpError(400)
    if ".." in path.replace("\\", "/").split("/"):
        raise HttpError(403)

    full_path = os.path.realpath(os.path.join(root, path.lstrip("/")))
    # realpath resolve symlinks: um link dentro de www/ apontando para fora também é barrado
    if os.path.commonpath([root, full_path]) != root:
        raise HttpError(403)
    if os.path.isdir(full_path):
        full_path = os.path.join(full_path, "index.html")
    if not os.path.isfile(full_path):
        raise HttpError(404)
    if not os.access(full_path, os.R_OK):
        raise HttpError(403)
    return full_path


def send_response(conn, status, body, content_type, keep_alive, head_only, extra_headers=None):
    headers = {
        "Date": http_date(),
        "Server": SERVER_NAME,
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Connection": "keep-alive" if keep_alive else "close",
        **(extra_headers or {}),
    }
    lines = [f"HTTP/1.1 {status} {REASONS[status]}"]
    lines += [f"{name}: {value}" for name, value in headers.items()]
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")
    # HEAD: mesmos headers (inclusive Content-Length) do GET, mas sem corpo
    conn.sendall(head if head_only else head + body)


def send_error(conn, error, keep_alive, head_only):
    body = f"{error.status} {REASONS[error.status]}\n".encode("utf-8")
    send_response(conn, error.status, body, "text/plain; charset=utf-8", keep_alive, head_only, error.headers)


def handle_connection(conn, addr, root):
    conn.settimeout(IDLE_TIMEOUT)
    buffer = b""
    with conn:
        while True:
            method, target, keep_alive = None, None, False
            try:
                head, buffer = read_head(conn, buffer)
                if head is None:
                    return
                method, target, version, headers = parse_request(head)
                buffer = skip_body(conn, buffer, headers)
                keep_alive = wants_keep_alive(version, headers)

                if version == "HTTP/1.1" and "host" not in headers:
                    raise HttpError(400)
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, {"Allow": "GET, HEAD"})

                file_path = resolve_path(root, target)
                with open(file_path, "rb") as f:
                    body = f.read()
                send_response(conn, 200, body, content_type_for(file_path), keep_alive, method == "HEAD")
                status = 200
            except HttpError as e:
                send_error(conn, e, keep_alive, method == "HEAD")
                status = e.status
            except (socket.timeout, OSError):
                return
            except Exception:
                send_error(conn, HttpError(500), False, method == "HEAD")
                status, keep_alive = 500, False

            print(f"{addr[0]}:{addr[1]} {method} {target} -> {status}", flush=True)
            if not keep_alive:
                return


def serve(port, root):
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        raise SystemExit(f"diretório raiz não encontrado: {root}")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("0.0.0.0", port))
        server_sock.listen()
        print(f"Servindo {root} em 0.0.0.0:{port}", flush=True)
        while True:
            conn, addr = server_sock.accept()
            # thread por conexão: uma conexão lenta não bloqueia as demais
            threading.Thread(target=handle_connection, args=(conn, addr, root), daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="Servidor HTTP/1.1 sobre sockets TCP")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        serve(args.port, args.root)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
