# T1 — Servidor HTTP/1.1 sobre Sockets TCP

Trabalho 1 de Laboratório de Redes de Computadores: implementação de um
servidor HTTP/1.1 diretamente sobre sockets TCP (sem bibliotecas HTTP prontas),
em Python, com foco em como o comportamento do TCP (handshake, RTT,
conexões persistentes) afeta o desempenho percebido do HTTP.


## Grupo

- Integrante(s): Livia, Luthero, Mariana e Nicolas
- Identificador usado no header `Server` das respostas: _preencher_

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
├── testes/                 # scripts de verificação manual (curl/nc, traversal, concorrência)
└── medicoes/
    ├── capturas/           # capturas .pcapng do Wireshark (ignoradas no git)
    ├── resultados/         # métricas extraídas das capturas (handshakes, pacotes, bytes, tempo)
    └── scripts/            # cliente de medição para os cenários C1/C2
```

## Como executar (previsto)

```bash
python3 src/server.py --port 8080 --root ./www
```

- `--port`: porta alta (> 1024) em que o servidor escuta.
- `--root`: diretório raiz servido. O servidor faz bind em `0.0.0.0`
  (todas as interfaces), nunca só em `127.0.0.1`.

Teste local rápido (na mesma máquina, apenas para sanity check — as medições
oficiais exigem duas máquinas):

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

## Testes de segurança 

No mínimo três tentativas de path traversal distintas, sendo pelo menos uma
com percent-encoding, todas devendo resultar em `403 Forbidden`. Scripts em
`testes/test_traversal.sh`.



