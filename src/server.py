#!/usr/bin/env python3
import os
import socket
import sys
import threading
import time

SERVER_NAME = "T1-Lab-Redes/1.0"
IDLE_TIMEOUT = 5 #Sugestão de 5 segundos para timeout
MAX_HEAD_SIZE = 16384

REASONS = {
    200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 500: "Internal Server Error", 505: "HTTP Version Not Supported",
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".json": "application/json",
    ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".pdf": "application/pdf",
}

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HEX = b"0123456789abcdefABCDEF"


# Classe de exceção para erros HTTP, contendo o status e cabeçalhos opcionais.
# Herda de exception e instancia a superclasse com a razão do status.
class HttpError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(REASONS[status])
        self.status = status
        self.headers = headers or {}

#Função que gera a data no formato HTTP.
#time.gmtime() retorna o horário em UTC e as tuplas DAYS, MONTHS convertem os índices para as abreviações
def http_date():
    # IMF-fixdate (RFC 9110): "Sun, 06 Nov 1994 08:49:37 GMT"
    t = time.gmtime()
    return (f"{DAYS[t.tm_wday]}, {t.tm_mday:02d} {MONTHS[t.tm_mon - 1]} {t.tm_year} "
            f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d} GMT")

#Converte sequências percentuais em seus bytes correspondentes
def percent_decode(path):
    raw, out, i = path.encode("iso-8859-1"), bytearray(), 0
    while i < len(raw): #Enquanto houverem bytes a ser processados
        if raw[i] == ord("%"):
        #Se o byte atual for um sinal de porcentagem, consumir os próximos dois bytes e convertê-los em um byte correspondente
            pair = raw[i + 1:i + 3]
            if len(pair) != 2 or any(c not in HEX for c in pair):
                #se algum caractere não for um hexa válido, ou se não houverem dois bytes a serem consumidos, lançar um erro HTTP 400
                raise HttpError(400)
            out.append(int(pair, 16))
            #Avançar o índice para pular os dois bytes consumidos
            i += 3
        else:
            #Se o byte atual não for um sinal de porcentagem, apenas adicioná-lo ao array de saída e avançar o índice
            out.append(raw[i])
            i += 1
    try:
        #Tentar decodificar o array de bytes resultante em uma string UTF-8
        return out.decode("utf-8")
    except UnicodeDecodeError:
        raise HttpError(400)


def read_head(conn, buffer):
    """Acumula bytes até CRLFCRLF. Retorna (head, sobra) ou (None, b"") se o cliente fechou."""
    while True: #Loop que lê dados da conexão até encontrar o final do cabeçalho HTTP (CRLFCRLF) ou até que o cliente feche a conexão.
        buffer = buffer.lstrip(b"\r\n") #Remove quaisquer quebras de linha no início do buffer, garantindo que o cabeçalho comece com uma linha válida.
        if b"\r\n\r\n" in buffer: #Se encontrar o final do cabeçalho, separa o cabeçalho do restante dos dados e retorna ambos.
            head, _, rest = buffer.partition(b"\r\n\r\n")
            return head.decode("iso-8859-1"), rest #Decodifica o cabeçalho, e retorna o resto.
        if len(buffer) > MAX_HEAD_SIZE: #Se o tamanho do cabeçalho exceder o limite máximo, lança um erro HTTP 400 (Bad Request).
            raise HttpError(400)
        chunk = conn.recv(4096) #Lê até 4096 bytes da conexão e adiciona ao buffer.
        if not chunk: #Se acabou os dados e ainda não achamos CRLFCRLF, significa que o cliente fechou a conexão antes de enviar um cabeçalho completo.
            if buffer: #Se ainda houver algo no buffer, erro
                raise HttpError(400)
            return None, b"" #Se não, era uma request vazia
        buffer += chunk #Adiciona a chunk atual ao buffer e repete


def parse_request(head):
    """Já com o cabecalho extraido da requisicao.."""
    lines = head.split("\r\n") #Separa em linhas, splitando em CRLF
    parts = lines[0].split(" ") #Separa a primeira linha em partes por whitespace (método, alvo, versão)
    if len(parts) != 3: #Se não houver 3 coisas, erro
        raise HttpError(400)
    method, target, version = parts #Seta as variáveis
    if version not in ("HTTP/1.0", "HTTP/1.1"): #Checka por validade da versao
        raise HttpError(505 if version.startswith("HTTP/") else 400)

    headers = {} #Dicionário para armazenar os cabeçalhos da requisição, com os nomes dos cabeçalhos em minúsculas e os valores correspondentes.
    for line in lines[1:]:
        name, sep, value = line.partition(":") #Separa
        if not sep or not name or name != name.strip():
            raise HttpError(400)
        headers[name.lower()] = value.strip()
    return method, target, version, headers


def skip_body(conn, buffer, headers):
    """GET/HEAD não têm corpo, mas se vier um é descartado para não corromper a próxima requisição."""
    length = headers.get("content-length", "0")
    if not length.isdigit():
        raise HttpError(400)
    length = int(length)
    while len(buffer) < length:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError
        buffer += chunk
    return buffer[length:]


def wants_keep_alive(version, headers):
    tokens = {t.strip().lower() for t in headers.get("connection", "").split(",")}
    if "close" in tokens:
        return False
    return version == "HTTP/1.1" or "keep-alive" in tokens


def resolve_path(root, target):
    path = target.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        raise HttpError(400)
    path = percent_decode(path)
    if "\0" in path:
        raise HttpError(400)
    if ".." in path.replace("\\", "/").split("/"):
        raise HttpError(403)

    # realpath resolve symlinks: um link em www/ apontando para fora também é barrado
    full_path = os.path.realpath(os.path.join(root, path.lstrip("/")))
    if full_path != root and not full_path.startswith(root + os.sep):
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
    head = f"HTTP/1.1 {status} {REASONS[status]}\r\n"
    head += "".join(f"{name}: {value}\r\n" for name, value in headers.items()) + "\r\n"
    # HEAD: mesmos headers do GET (inclusive Content-Length), mas sem corpo
    conn.sendall(head.encode("iso-8859-1") + (b"" if head_only else body))


def handle_connection(conn, addr, root):
    """Lida com uma conexão de cliente, processando requisições HTTP
    até que o cliente feche ou o timeout seja atingido."""
    conn.settimeout(IDLE_TIMEOUT) #Tempo limite de inatividade
    buffer = b"" #Buffer para armazenar dados recebidos da conexão
    with conn: #Garante que a conexão seja fechada ao sair do bloco
        while True:
            method = target = None #Variáveis para armazenar o método e o alvo da requisição, inicializadas como None
            keep_alive = False #Variável para indicar se a conexão deve ser mantida aberta após a resposta, inicializada como False
            try:
                head, buffer = read_head(conn, buffer)
                if head is None: #Se o cabeçalho for None, significa que o cliente fechou a conexão, então a função retorna e encerra o loop.
                    return
                method, target, version, headers = parse_request(head) #Parse do cabeçalho da requisição, extraindo o método, alvo, versão e cabeçalhos
                buffer = skip_body(conn, buffer, headers) #Descarta o corpo da requisição pois GET/HEAD não devem ter corpo 
                keep_alive = wants_keep_alive(version, headers) #Determina se a conexão deve ser mantida aberta com base na versão do HTTP e nos cabeçalhos da requisição.
                if version == "HTTP/1.1" and "host" not in headers:
                    raise HttpError(400)
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, {"Allow": "GET, HEAD"})

                file_path = resolve_path(root, target)
                with open(file_path, "rb") as f:
                    body = f.read()
                ext = os.path.splitext(file_path)[1].lower()
                content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
                send_response(conn, 200, body, content_type, keep_alive, method == "HEAD")
                status = 200
            except (socket.timeout, OSError):
                return
            except Exception as e:
                if not isinstance(e, HttpError):
                    e, keep_alive = HttpError(500), False
                status = e.status
                body = f"{status} {REASONS[status]}\n".encode()
                send_response(conn, status, body, "text/plain; charset=utf-8",
                              keep_alive, method == "HEAD", e.headers)

            print(f"{addr[0]}:{addr[1]} {method} {target} -> {status}", flush=True)
            if not keep_alive:
                return


def serve(port, root):
    """Inicia o servidor na porta e diretório raiz especificados."""
    root = os.path.realpath(root)
    #Verifica se o diretório raiz existe e é um diretório válido. Se não for, encerra o programa com uma mensagem de erro.
    if not os.path.isdir(root):
        sys.exit(f"diretório raiz não encontrado: {root}")

    #Cria um socket TCP
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        #Permite que o socket seja reutilizado imediatamente após o encerramento,
        #evitando erros de "endereço já em uso"
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        #Associa o socket a todas as interfaces de rede disponíveis na porta especificada e começa a escutar por conexões.
        server_sock.bind(("0.0.0.0", port))
        server_sock.listen()
        print(f"Servindo {root} em 0.0.0.0:{port}", flush=True)
        while True:
            #Loop que aceita conexões de clientes e cria uma nova thread para cada conexão, 
            #chamando a função handle_connection.
            conn, addr = server_sock.accept()
            # thread por conexão, daemon=True para não impedir o encerramento do programa
            threading.Thread(target=handle_connection, args=(conn, addr, root), daemon=True).start()


def main():
    """
    Puxa os argumentos da linha de comando,
    valida-os e inicia o servidor.
    """
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    if len(sys.argv) != 5 or set(args) != {"--port", "--root"} or not args["--port"].isdigit():
        sys.exit("uso: server.py --port <porta> --root <diretorio>")
    if int(args["--port"]) <= 1024:
        sys.exit("porta deve ser > 1024")
    try:
        serve(int(args["--port"]), args["--root"]) #Inicia o servidor com a porta e diretório raiz especificados
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
