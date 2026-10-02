#!/usr/bin/env python3
import os
import socket
import sys
import threading
import time

# Identificador do grupo enviado no header Server de toda resposta
SERVER_NAME = "T1-Lab-Redes/1.0"
# Sugestão de 5 segundos para timeout de conexão ociosa
IDLE_TIMEOUT = 5
# Limite do cabeçalho (16 KB): impede que um cliente mande headers infinitos e encha a memória
MAX_HEAD_SIZE = 16384

# Frase de razão que acompanha cada código na linha de status (ex: "HTTP/1.1 404 Not Found")
REASONS = {
    200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 500: "Internal Server Error", 505: "HTTP Version Not Supported",
}

# Extensão -> Content-Type. Extensão fora da tabela vira application/octet-stream
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".json": "application/json",
    ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".pdf": "application/pdf",
}

# Nomes fixos em inglês exigidos pelo IMF-fixdate (não dependem do idioma do sistema)
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Bytes aceitos como dígito hexadecimal depois de um "%"
HEX = b"0123456789abcdefABCDEF"


# Classe de exceção para erros HTTP, contendo o status e cabeçalhos opcionais.
# Herda de Exception e instancia a superclasse com a razão do status.
# Qualquer função pode dar "raise HttpError(404)" e o handle_connection transforma isso na resposta de erro.
class HttpError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(REASONS[status])
        self.status = status
        # Headers extras da resposta de erro (ex: Allow no 405)
        self.headers = headers or {}


# Função que gera a data no formato HTTP.
# time.gmtime() retorna o horário em UTC e as tuplas DAYS, MONTHS convertem os índices para as abreviações
def http_date():
    # IMF-fixdate (RFC 9110): "Sun, 06 Nov 1994 08:49:37 GMT"
    t = time.gmtime()
    # :02d completa com zero à esquerda (ex: 6 -> "06"); tm_wday começa em segunda = 0, tm_mon começa em 1
    return (f"{DAYS[t.tm_wday]}, {t.tm_mday:02d} {MONTHS[t.tm_mon - 1]} {t.tm_year} "
            f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d} GMT")


# Converte sequências percentuais (%XX) em seus bytes correspondentes (ex: "%20" -> espaço)
def percent_decode(path):
    # O cabeçalho foi decodificado em iso-8859-1 (1 caractere = 1 byte), então encode volta aos bytes originais
    raw, out, i = path.encode("iso-8859-1"), bytearray(), 0
    # Enquanto houverem bytes a serem processados
    while i < len(raw):
        # Se o byte atual for um sinal de porcentagem, consumir os próximos dois bytes e convertê-los em um byte correspondente
        if raw[i] == ord("%"):
            pair = raw[i + 1:i + 3]
            # Se algum caractere não for um hexa válido, ou se não houverem dois bytes a serem consumidos, lançar um erro HTTP 400
            if len(pair) != 2 or any(c not in HEX for c in pair):
                raise HttpError(400)
            # int(..., 16) interpreta os dois dígitos como hexadecimal (ex: b"2e" -> 46, que é ".")
            out.append(int(pair, 16))
            # Avançar o índice para pular o "%" e os dois bytes consumidos
            i += 3
        else:
            # Se o byte atual não for um sinal de porcentagem, apenas adicioná-lo ao array de saída e avançar o índice
            out.append(raw[i])
            i += 1
    try:
        # Só agora decodifica como UTF-8: um caractere como "é" ocupa 2 bytes (%C3%A9) e precisa dos dois juntos
        return out.decode("utf-8")
    except UnicodeDecodeError:
        raise HttpError(400)


def read_head(conn, buffer):
    """Acumula bytes até CRLFCRLF. Retorna (head, sobra) ou (None, b"") se o cliente fechou."""
    # Loop que lê dados da conexão até encontrar o final do cabeçalho HTTP (CRLFCRLF) ou até que o cliente feche a conexão.
    while True:
        # Descarta CRLFs soltos antes da request-line (a RFC 9112 manda o servidor tolerar isso entre requisições)
        buffer = buffer.lstrip(b"\r\n")
        # Se encontrar o final do cabeçalho, separa o cabeçalho do restante dos dados e retorna ambos.
        if b"\r\n\r\n" in buffer:
            head, _, rest = buffer.partition(b"\r\n\r\n")
            # Decodifica o cabeçalho e devolve o resto, que pode ser o início da PRÓXIMA requisição (não pode ser descartado)
            return head.decode("iso-8859-1"), rest
        # Se o tamanho do cabeçalho exceder o limite máximo, lança um erro HTTP 400 (Bad Request).
        if len(buffer) > MAX_HEAD_SIZE:
            raise HttpError(400)
        # Lê até 4096 bytes da conexão. Bloqueia até chegar algo ou estourar o timeout (socket.timeout)
        chunk = conn.recv(4096)
        # recv devolver b"" significa que o cliente fechou a conexão (mandou FIN)
        if not chunk:
            # Se fechou no meio de um cabeçalho, a requisição ficou incompleta: erro
            if buffer:
                raise HttpError(400)
            # Se não, o cliente fechou entre requisições: fim normal de uma conexão persistente
            return None, b""
        # Adiciona o chunk atual ao buffer e repete
        buffer += chunk


def parse_request(head):
    """Recebe o cabeçalho já extraído (sem o CRLFCRLF final) e devolve método, alvo, versão e headers."""
    # Separa em linhas, quebrando em CRLF
    lines = head.split("\r\n")
    # Separa a primeira linha em partes por espaço simples (método, alvo, versão)
    parts = lines[0].split(" ")
    # Se não houver exatamente 3 partes, a request-line é inválida
    if len(parts) != 3:
        raise HttpError(400)
    method, target, version = parts
    # Checa a validade da versão: "HTTP/2.0" é HTTP mas não suportado (505); qualquer outra coisa é malformada (400)
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise HttpError(505 if version.startswith("HTTP/") else 400)

    # Dicionário com os cabeçalhos, nomes em minúsculas (nomes de header não diferenciam maiúsculas)
    headers = {}
    for line in lines[1:]:
        # Separa nome e valor no PRIMEIRO ":" (o valor pode conter ":", ex: "Host: 10.0.0.1:8080")
        name, sep, value = line.partition(":")
        # Header sem ":", nome vazio ou com espaço antes do ":" é malformado
        if not sep or not name or name != name.strip():
            raise HttpError(400)
        headers[name.lower()] = value.strip()
    return method, target, version, headers


def skip_body(conn, buffer, headers):
    """GET/HEAD não têm corpo, mas se vier um é descartado para não corromper a próxima requisição."""
    # Sem Content-Length, considera corpo de tamanho 0
    length = headers.get("content-length", "0")
    # Content-Length tem que ser um número inteiro não negativo
    if not length.isdigit():
        raise HttpError(400)
    length = int(length)
    # Parte do corpo pode já estar no buffer; lê do socket só o que falta
    while len(buffer) < length:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError
        buffer += chunk
    # Joga fora os bytes do corpo e devolve o que sobrar (próxima requisição)
    return buffer[length:]


def wants_keep_alive(version, headers):
    # O header Connection pode ter vários valores separados por vírgula (ex: "keep-alive, Upgrade")
    tokens = {t.strip().lower() for t in headers.get("connection", "").split(",")}
    # Cliente pediu para fechar
    if "close" in tokens:
        return False
    # HTTP/1.1 é persistente por padrão; HTTP/1.0 só se pedir keep-alive explicitamente
    return version == "HTTP/1.1" or "keep-alive" in tokens


def resolve_path(root, target):
    """Converte o alvo da requisição em um caminho de arquivo dentro de root, ou lança 400/403/404."""
    # Remove query string (?...) e fragmento (#...): não fazem parte do caminho do arquivo
    path = target.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        raise HttpError(400)
    # Decodifica ANTES de checar "..": senão "%2e%2e" passaria pela checagem e viraria ".." depois
    path = percent_decode(path)
    # Byte nulo pode truncar o caminho em chamadas do sistema operacional
    if "\0" in path:
        raise HttpError(400)
    # Qualquer segmento ".." é tentativa de travessia; "\\" é tratado como "/" por segurança
    if ".." in path.replace("\\", "/").split("/"):
        raise HttpError(403)

    # realpath resolve symlinks: um link em www/ apontando para fora também é barrado
    full_path = os.path.realpath(os.path.join(root, path.lstrip("/")))
    # Segunda barreira: o caminho final tem que estar dentro de root
    if full_path != root and not full_path.startswith(root + os.sep):
        raise HttpError(403)
    # Pedido de diretório (ex: "/") serve o index.html dele
    if os.path.isdir(full_path):
        full_path = os.path.join(full_path, "index.html")
    if not os.path.isfile(full_path):
        raise HttpError(404)
    # Arquivo existe mas o servidor não tem permissão de leitura
    if not os.access(full_path, os.R_OK):
        raise HttpError(403)
    return full_path


def send_response(conn, status, body, content_type, keep_alive, head_only, extra_headers=None):
    """Monta e envia uma resposta completa (status-line + headers + corpo)."""
    headers = {
        "Date": http_date(),
        "Server": SERVER_NAME,
        "Content-Type": content_type,
        # Tamanho do corpo em bytes; é assim que o cliente sabe onde a resposta termina
        "Content-Length": str(len(body)),
        # Avisa ao cliente se a conexão continua aberta (ecoa o Connection: close do cliente)
        "Connection": "keep-alive" if keep_alive else "close",
        # Junta os headers extras (ex: Allow do 405)
        **(extra_headers or {}),
    }
    # Linha de status, ex: "HTTP/1.1 200 OK\r\n"
    head = f"HTTP/1.1 {status} {REASONS[status]}\r\n"
    # Uma linha "Nome: valor\r\n" por header, mais um "\r\n" final que forma a linha em branco
    head += "".join(f"{name}: {value}\r\n" for name, value in headers.items()) + "\r\n"
    # HEAD: mesmos headers do GET (inclusive Content-Length), mas sem corpo
    # sendall repete send() até todos os bytes saírem (send sozinho pode enviar só parte)
    conn.sendall(head.encode("iso-8859-1") + (b"" if head_only else body))


def handle_connection(conn, addr, root):
    """Lida com uma conexão de cliente, processando requisições HTTP
    até que o cliente feche ou o timeout seja atingido."""
    # Tempo limite de inatividade: cada recv() espera no máximo IDLE_TIMEOUT segundos
    conn.settimeout(IDLE_TIMEOUT)
    # Buffer da conexão: guarda bytes que sobraram de uma requisição para a próxima
    buffer = b""
    # Garante que a conexão seja fechada ao sair do bloco
    with conn:
        # Cada volta do loop atende uma requisição na mesma conexão (conexão persistente)
        while True:
            # Inicializadas como None/False para o tratamento de erro saber o que já foi lido
            method = target = None
            keep_alive = False
            try:
                head, buffer = read_head(conn, buffer)
                # Se o cabeçalho for None, o cliente fechou a conexão: encerra
                if head is None:
                    return
                # Parse do cabeçalho, extraindo método, alvo, versão e headers
                method, target, version, headers = parse_request(head)
                # Descarta o corpo da requisição, pois GET/HEAD não devem ter corpo
                buffer = skip_body(conn, buffer, headers)
                # Decide se a conexão continua aberta após a resposta (versão do HTTP e header Connection)
                keep_alive = wants_keep_alive(version, headers)
                # Host é obrigatório no HTTP/1.1
                if version == "HTTP/1.1" and "host" not in headers:
                    raise HttpError(400)
                if method not in ("GET", "HEAD"):
                    raise HttpError(405, {"Allow": "GET, HEAD"})

                # Lê o arquivo inteiro em bytes ("rb") para saber o tamanho exato do corpo
                file_path = resolve_path(root, target)
                with open(file_path, "rb") as f:
                    body = f.read()
                # Content-Type pela extensão, em minúsculas (".PNG" == ".png")
                ext = os.path.splitext(file_path)[1].lower()
                content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
                send_response(conn, 200, body, content_type, keep_alive, method == "HEAD")
                status = 200
            # Timeout de ociosidade ou erro de rede (cliente sumiu): só fecha, não há para quem responder
            except (socket.timeout, OSError):
                return
            except Exception as e:
                # Erro inesperado (bug) vira 500 e fecha a conexão
                if not isinstance(e, HttpError):
                    e, keep_alive = HttpError(500), False
                # Resposta de erro com corpo de texto curto, ex: "404 Not Found"
                status = e.status
                body = f"{status} {REASONS[status]}\n".encode()
                # keep_alive continua False se o erro foi de parsing (400): a conexão fica fora de sincronia e é fechada
                send_response(conn, status, body, "text/plain; charset=utf-8",
                              keep_alive, method == "HEAD", e.headers)

            # Log de cada requisição: IP:porta do cliente, método, alvo e status (evidência de concorrência)
            print(f"{addr[0]}:{addr[1]} {method} {target} -> {status}", flush=True)
            if not keep_alive:
                return


def serve(port, root):
    """Inicia o servidor na porta e diretório raiz especificados."""
    # Caminho absoluto e sem symlinks, usado como referência na checagem de travessia
    root = os.path.realpath(root)
    # Verifica se o diretório raiz existe e é um diretório válido. Se não for, encerra o programa com uma mensagem de erro.
    if not os.path.isdir(root):
        sys.exit(f"diretório raiz não encontrado: {root}")

    # Cria um socket TCP (AF_INET = IPv4, SOCK_STREAM = TCP)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        # Permite reutilizar a porta logo após reiniciar o servidor (conexões antigas em TIME_WAIT),
        # evitando erros de "endereço já em uso"
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Associa o socket a todas as interfaces de rede disponíveis na porta especificada e começa a escutar por conexões.
        server_sock.bind(("0.0.0.0", port))
        server_sock.listen()
        print(f"Servindo {root} em 0.0.0.0:{port}", flush=True)
        while True:
            # Loop que aceita conexões de clientes e cria uma nova thread para cada conexão,
            # chamando a função handle_connection. accept() bloqueia até um cliente completar o handshake TCP
            conn, addr = server_sock.accept()
            # Thread por conexão, daemon=True para não impedir o encerramento do programa
            threading.Thread(target=handle_connection, args=(conn, addr, root), daemon=True).start()


def main():
    """
    Puxa os argumentos da linha de comando,
    valida-os e inicia o servidor.
    """
    # sys.argv = ["server.py", "--port", "8080", "--root", "./www"]: pareia posições ímpares (nomes) com pares (valores)
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    if len(sys.argv) != 5 or set(args) != {"--port", "--root"} or not args["--port"].isdigit():
        sys.exit("uso: server.py --port <porta> --root <diretorio>")
    # Portas até 1024 são privilegiadas (exigem admin) e o enunciado pede porta alta
    if int(args["--port"]) <= 1024:
        sys.exit("porta deve ser > 1024")
    try:
        # Inicia o servidor com a porta e diretório raiz especificados
        serve(int(args["--port"]), args["--root"])
    # Ctrl+C encerra sem mostrar traceback
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
