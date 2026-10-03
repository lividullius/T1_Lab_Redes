# T1 — Servidor HTTP/1.1 sobre Sockets TCP

Trabalho 1 de Laboratório de Redes de Computadores: implementação de um
servidor HTTP/1.1 diretamente sobre sockets TCP (sem bibliotecas HTTP prontas),
em Python, com foco em como o comportamento do TCP (handshake, RTT,
conexões persistentes) afeta o desempenho percebido do HTTP.

## Grupo

- Integrante(s): Livia, Luthero, Mariana e Nicolas
- Identificador usado no header `Server` das respostas: `T1-Lab-Redes/1.0`

## Requisitos

- Python 3.x (apenas biblioteca padrão — sem Flask, `http.server`,
  `socketserver`-como-framework-HTTP, etc.).
- `curl` e um navegador para testes manuais.
- Wireshark, para captura de tráfego (`tcp.port == <porta>`).
- Duas máquinas na mesma rede (as medições da Parte 2 exigem RTT real, não
  `localhost`).

## Estrutura do repositório

```
T1_Lab_Redes/
├── src/                    # código-fonte do servidor (Python)
├── www/                    # diretório raiz de teste servido pelo servidor
├── testes/                 # test_server.py — checklist de conformidade (status codes + traversal)
└── medicoes/
    ├── capturas/           # capturas .pcapng do Wireshark (c1.pcapng, c2.pcapng — ignoradas no git)
    ├── resultados/         # métricas extraídas das capturas (handshakes, pacotes, bytes, tempo)
    └── scripts/            # cliente de medição (measure.py) para os cenários C1/C2
```

## Como compilar/executar

Não há compilação: é um único script Python, sem dependências externas.

```bash
python3 src/server.py --port 8080 --root ./www
```

### Argumentos de linha de comando

| Argumento | Obrigatório | Descrição |
|---|---|---|
| `--port` | sim | Porta TCP em que o servidor escuta. Deve ser > 1024 (porta alta, não privilegiada). |
| `--root` | sim | Diretório raiz servido (caminho absoluto ou relativo). Nenhum arquivo fora dele é servido, nem com `..` ou percent-encoding. |

O servidor faz *bind* em `0.0.0.0` (todas as interfaces), nunca só em
`127.0.0.1`, para aceitar conexões de outras máquinas da rede. Encerra com
`Ctrl+C`.

### Teste local rápido (sanity check)

As medições oficiais da Parte 2 exigem duas máquinas distintas (RTT real),
mas para checar que o servidor está de pé:

```bash
curl -i http://<ip-da-maquina>:8080/index.html
curl -I http://<ip-da-maquina>:8080/index.html   # HEAD
```

## Escopo do trabalho

### Parte 1 — Servidor

- Parsing manual da request-line e dos headers (CRLF, acumulação de buffer
  entre chamadas de `recv()`, decodificação de percent-encoding no path).
- Métodos `GET` e `HEAD`; qualquer outro método → `405 Method Not Allowed`
  com `Allow: GET, HEAD`.
- Respostas com `Content-Length`, `Content-Type` (por extensão, mínimo
  `.html .css .js .json .txt .png .jpg .pdf`, com fallback
  `application/octet-stream`), `Date` em IMF-fixdate/GMT e `Server`.
- Códigos obrigatórios: `200`, `400`, `403`, `404`, `405`.
- Proteção contra path traversal: nenhum arquivo fora do diretório raiz é
  servido, mesmo com `..` ou percent-encoding.
- Concorrência: uma conexão lenta não pode bloquear as demais (estratégia:
  thread por conexão — justificativa detalhada no relatório).

### Parte 2 — Conexões persistentes

- Conexão HTTP/1.1 persistente por padrão; `Connection: close` do cliente é
  respeitado (eco do header + encerramento).
- Timeout de conexão ociosa (5s).
- Suporte a múltiplas requisições sequenciais na mesma conexão.
- Medição comparativa entre dois cenários, sempre entre duas máquinas
  distintas e com captura Wireshark ativa:
  - **C1**: 10 requisições, uma conexão nova por requisição
    (`Connection: close`).
  - **C2**: 10 requisições em uma única conexão persistente.
  - Métricas extraídas por cenário: nº de handshakes TCP completos, total de
    pacotes, bytes totais, tempo total — mais o RTT médio (`ping`) de
    referência.

## Verificação de conformidade (status codes)

`testes/test_server.py` automatiza os 5 status codes obrigatórios e as 3
tentativas de path traversal numa só execução (sockets crus, sem `curl`):

```bash
python3 testes/test_server.py --host <ip> --port 8080
```

Os comandos abaixo produzem os mesmos casos manualmente, úteis para colar a
requisição/resposta completa na tabela de conformidade do relatório:

```bash
# 200 OK
curl -i http://<ip>:8080/index.html

# 200 OK, sem corpo (HEAD)
curl -I http://<ip>:8080/index.html

# 404 Not Found
curl -i http://<ip>:8080/naoexiste.html

# 405 Method Not Allowed (Allow: GET, HEAD)
curl -i -X DELETE http://<ip>:8080/index.html

# 400 Bad Request (request-line sem versão HTTP)
printf 'GET /index.html\r\nHost: x\r\n\r\n' | nc <ip> 8080
```

## Testes de segurança (path traversal)

Também cobertas por `testes/test_server.py` (acima). Três tentativas
distintas, todas devendo resultar em `403 Forbidden` — os mesmos comandos
curl abaixo usam `--path-as-is` para o `..` não ser normalizado *antes* de
sair da máquina cliente:

```bash
# 1. travessia direta
curl -i --path-as-is http://<ip>:8080/../../etc/passwd

# 2. travessia com percent-encoding simples (%2e%2e = "..")
curl -i --path-as-is http://<ip>:8080/%2e%2e/%2e%2e/etc/passwd

# 3. travessia com barra percent-encoded (%2f = "/")
curl -i --path-as-is http://<ip>:8080/..%2f..%2fetc/passwd
```

## Medição C1 vs C2 (Parte 2)

A partir da outra máquina (cliente), com o Wireshark capturando
(`tcp.port == <porta>`), iniciar uma captura por cenário:

```bash
# C1: uma conexão nova por requisição
python3 medicoes/scripts/measure.py --host <ip-servidor> --port 8080 \
    --path /index.html --scenario c1 --requests 10

# C2: uma única conexão persistente para as 10 requisições
python3 medicoes/scripts/measure.py --host <ip-servidor> --port 8080 \
    --path /index.html --scenario c2 --requests 10
```

Salvar as capturas como `medicoes/capturas/c1.pcapng` e
`medicoes/capturas/c2.pcapng`. Antes de medir, registrar o RTT médio entre
as máquinas com `ping <ip-servidor>`.
