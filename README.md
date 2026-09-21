# T1 — Servidor HTTP/1.1 sobre Sockets TCP

Trabalho 1 de Laboratório de Redes de Computadores: implementação de um
servidor HTTP/1.1 diretamente sobre sockets TCP (sem bibliotecas HTTP prontas),
em Python, com foco em como o comportamento do TCP (handshake, RTT,
conexões persistentes) afeta o desempenho percebido do HTTP.

**Status atual:** planejamento/estrutura do repositório. Nenhum código do
servidor foi implementado ainda (ver seção [Progresso](#progresso)).

## Grupo

- Integrante(s): _preencher_
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
├── tests/                  # scripts de verificação manual (curl/nc, traversal, concorrência)
├── measurements/
│   ├── captures/           # capturas .pcapng do Wireshark (ignoradas no git)
│   ├── results/            # métricas extraídas das capturas (handshakes, pacotes, bytes, tempo)
│   └── scripts/            # cliente de medição para os cenários C1/C2
└── docs/report/            # fontes do relatório técnico final
```

Cada uma dessas pastas tem um `README.md` próprio detalhando o que vai nela.

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

## Testes de segurança (obrigatório no relatório)

No mínimo três tentativas de path traversal distintas, sendo pelo menos uma
com percent-encoding, todas devendo resultar em `403 Forbidden`. Scripts em
`tests/test_traversal.sh`.

## Restrições técnicas

- Sockets TCP diretos (`socket`, `bind`, `listen`, `accept`, `recv`, `send`).
- Proibido usar qualquer biblioteca/módulo que implemente HTTP do lado
  servidor (`http.server`, Flask, etc.). Parsing e geração das mensagens
  HTTP são feitos manualmente.
- Permitido usar bibliotecas padrão para arquivos, datas, hashes e
  concorrência (threads).

## Progresso

- [x] Estrutura de pastas do repositório
- [ ] Parsing de requisição (request-line + headers)
- [ ] Respostas (status, headers obrigatórios, Content-Type)
- [ ] GET / HEAD / 405 para outros métodos
- [ ] Proteção contra path traversal
- [ ] Concorrência (múltiplas conexões simultâneas)
- [ ] Conexões persistentes + timeout de ociosidade
- [ ] Scripts de medição C1/C2
- [ ] Relatório técnico

## Relatório e apresentação

- Relatório técnico em `docs/report/`.
- Apresentação da solução ao professor.
- Teste de interoperabilidade com outro grupo durante a aula de apresentação.
