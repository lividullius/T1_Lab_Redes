
## Capturas: (ajeitar isso ou nao colocar no final)
* C1 e C2, enunciado
* `t1pacotesespecificos` wireshark pegando quando entramos no http sendo cliente
* `teste2clientes...` wireshark rodando o servidor e dois clientes tentando conectar ao mesmo tempo
* `teste403` tem no enunciado sobre o 403


RTT médio via ping:

T1_Lab_Redes> ping -n 10 192.168.18.220

Disparando 192.168.18.220 com 32 bytes de dados:
Resposta de 192.168.18.220: bytes=32 tempo=78ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=88ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=105ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=103ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=110ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=115ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=32ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=39ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=42ms TTL=64
Resposta de 192.168.18.220: bytes=32 tempo=4ms TTL=64

Estatísticas do Ping para 192.168.18.220:
    Pacotes: Enviados = 10, Recebidos = 10, Perdidos = 0 (0% de
             perda),
Aproximar um número redondo de vezes em milissegundos:
    Mínimo = 4ms, Máximo = 115ms, Média = 71ms