"""Atlas — bot de Discord que faz o que a pessoa manda.

Feito do zero (19/09/2026). A regra do projeto é uma só:

    COMANDO RECONHECIDO NÃO PASSA POR LLM.

Explicar o pedido para um modelo e esperar a resposta dele leva 2–4s (e às vezes ele responde
outra coisa, como aconteceu quando o dono pediu "apague todos os canais" e recebeu uma ficha do
servidor). Aqui o pedido é lido no próprio processo, em milissegundos, e a ação roda na hora.
O modelo (OmniRoute) só entra quando o pedido NÃO é reconhecido — e, nesse caso, a resposta sai
em pedaços (streaming) para o usuário ver texto na tela no primeiro segundo.
"""

__version__ = "2.0.0"
