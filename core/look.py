"""
A cara das respostas do farol: mensagem em Components V2 com a cor do avatar dele.

O dono pediu (18/09): "queria que ele respondesse em embed naquele componente V2 ... as
mensagens dele vão vim organizadas", e não sabia qual cor usar — queria uma que combinasse
com a foto do bot. Então a cor é CALCULADA da própria foto, não chutada:

  1. baixa o avatar do bot em PNG (a API do Discord sempre entrega PNG nesse formato);
  2. decodifica o PNG sem depender de biblioteca externa (zlib + filtros, stdlib);
  3. escolhe a cor de destaque: média das cores com saturação alta (ignora branco, preto e
     cinza, que são fundo), ponderada pelo quanto a cor "salta";
  4. devolve essa cor em `accent_color` do container — e o resultado é cacheado.

Se qualquer passo falhar (avatar sem cor viva, PNG exótico, rede), o farol usa a cor de
reserva e continua respondendo normalmente: enfeite nunca pode derrubar a resposta.
"""

from __future__ import annotations

import logging
import struct
import zlib
from typing import Any, Iterable

logger = logging.getLogger("farol.look")

# Cor de reserva (o amarelo do farol) — usada quando não dá para medir o avatar.
COR_RESERVA = 0xF1C40F

# Largura em que pedimos o avatar: pequena de propósito (só precisamos da paleta).
LADO_DO_AVATAR = 64


# ------------------------------------------------------------------ PNG (stdlib)

def _canais_por_pixel(tipo_cor: int) -> tuple[int, int]:
    """(canais por pixel, canais úteis) do tipo de cor do PNG."""
    return {
        0: (1, 1),   # tons de cinza
        2: (3, 3),   # RGB
        3: (1, 1),   # paleta (índice)
        4: (2, 1),   # cinza + alfa
        6: (4, 3),   # RGBA
    }[tipo_cor]


def _desfiltra(bruto: bytes, largura: int, altura: int, bpp: int) -> bytes:
    """Desfaz os filtros por linha do PNG (0=Nenhum, 1=Sub, 2=Up, 3=Average, 4=Paeth)."""
    passo = largura * bpp
    saida = bytearray()
    anterior = bytearray(passo)
    pos = 0
    for _ in range(altura):
        if pos >= len(bruto):
            break
        filtro = bruto[pos]
        pos += 1
        linha = bytearray(bruto[pos:pos + passo])
        pos += passo
        if filtro == 1:
            for i in range(bpp, passo):
                linha[i] = (linha[i] + linha[i - bpp]) & 0xFF
        elif filtro == 2:
            for i in range(passo):
                linha[i] = (linha[i] + anterior[i]) & 0xFF
        elif filtro == 3:
            for i in range(passo):
                esq = linha[i - bpp] if i >= bpp else 0
                linha[i] = (linha[i] + ((esq + anterior[i]) >> 1)) & 0xFF
        elif filtro == 4:
            for i in range(passo):
                esq = linha[i - bpp] if i >= bpp else 0
                cima = anterior[i]
                diag = anterior[i - bpp] if i >= bpp else 0
                p = esq + cima - diag
                pa, pb, pc = abs(p - esq), abs(p - cima), abs(p - diag)
                pred = esq if (pa <= pb and pa <= pc) else (cima if pb <= pc else diag)
                linha[i] = (linha[i] + pred) & 0xFF
        elif filtro != 0:
            raise ValueError(f"filtro PNG desconhecido: {filtro}")
        saida += linha
        anterior = linha
    return bytes(saida)


def pixels_do_png(dados: bytes) -> list[tuple[int, int, int, int]]:
    """
    Decodifica um PNG simples (8 bits, sem entrelaçamento) em pixels RGBA.

    Suporta os tipos que a API do Discord usa no avatar (RGB e RGBA) e também cinza e
    cinza+alfa. Não suporta 16 bits nem Adam7 — nesses casos levanta ValueError e o
    chamador cai na cor de reserva.
    """
    if not dados.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("não é um PNG")
    pos = 8
    largura = altura = profundidade = tipo_cor = 0
    idat = bytearray()
    paleta: list[tuple[int, int, int]] = []
    while pos + 8 <= len(dados):
        tamanho = struct.unpack(">I", dados[pos:pos + 4])[0]
        tipo = dados[pos + 4:pos + 8]
        corpo = dados[pos + 8:pos + 8 + tamanho]
        pos += 12 + tamanho  # + CRC
        if tipo == b"IHDR":
            largura, altura, profundidade, tipo_cor = struct.unpack(">IIBB", corpo[:10])
        elif tipo == b"PLTE":
            paleta = [(corpo[i], corpo[i + 1], corpo[i + 2]) for i in range(0, len(corpo), 3)]
        elif tipo == b"IDAT":
            idat += corpo
        elif tipo == b"IEND":
            break
    if profundidade != 8:
        raise ValueError(f"profundidade PNG não suportada: {profundidade} bits")
    if largura <= 0 or altura <= 0:
        raise ValueError("PNG sem dimensões")
    bpp, uteis = _canais_por_pixel(tipo_cor)
    linhas = _desfiltra(zlib.decompress(bytes(idat)), largura, altura, bpp)
    pixels: list[tuple[int, int, int, int]] = []
    passo = largura * bpp
    for y in range(altura):
        base = y * passo
        for x in range(largura):
            i = base + x * bpp
            if i + bpp > len(linhas):
                break
            if tipo_cor == 0:
                v = linhas[i]
                pixels.append((v, v, v, 255))
            elif tipo_cor == 4:
                v, a = linhas[i], linhas[i + 1]
                pixels.append((v, v, v, a))
            elif tipo_cor == 2:
                pixels.append((linhas[i], linhas[i + 1], linhas[i + 2], 255))
            elif tipo_cor == 6:
                pixels.append((linhas[i], linhas[i + 1], linhas[i + 2], linhas[i + 3]))
            else:  # paleta
                idx = linhas[i]
                r, g, b = paleta[idx] if idx < len(paleta) else (0, 0, 0)
                pixels.append((r, g, b, 255))
    return pixels


# ------------------------------------------------------------------ cor de destaque

def _hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    """HSV com H em [0,360), S e V em [0,1]."""
    r_, g_, b_ = r / 255, g / 255, b / 255
    maximo, minimo = max(r_, g_, b_), min(r_, g_, b_)
    delta = maximo - minimo
    if delta == 0:
        matiz = 0.0
    elif maximo == r_:
        matiz = (60 * ((g_ - b_) / delta)) % 360
    elif maximo == g_:
        matiz = 60 * ((b_ - r_) / delta) + 120
    else:
        matiz = 60 * ((r_ - g_) / delta) + 240
    saturacao = 0.0 if maximo == 0 else delta / maximo
    return matiz, saturacao, maximo


def cor_de_destaque(pixels: Iterable[tuple[int, int, int, int]]) -> int:
    """
    Escolhe a cor que "salta" da imagem: média das cores vivas, ponderada pela saturação.

    Fundo branco/preto/cinza e pixels quase transparentes ficam de fora; se a imagem for
    toda neutra, cai na média geral (melhor uma cor qualquer do que nenhuma).
    """
    soma_r = soma_g = soma_b = 0.0
    peso_total = 0.0
    geral = [0, 0, 0, 0]
    for r, g, b, a in pixels:
        if a < 128:
            continue
        geral[0] += r
        geral[1] += g
        geral[2] += b
        geral[3] += 1
        _, s, v = _hsv(r, g, b)
        if s < 0.25 or v < 0.12 or v > 0.98:
            continue
        peso = s * s
        soma_r += r * peso
        soma_g += g * peso
        soma_b += b * peso
        peso_total += peso
    # round (e não int) para uma foto de cor única devolver exatamente aquela cor: somar em
    # ponto flutuante e truncar erra por 1 (230 · 4096 → 229,99999999999997 → 229).
    if peso_total <= 0:
        if geral[3] == 0:
            return COR_RESERVA
        return ((round(geral[0] / geral[3]) << 16)
                | (round(geral[1] / geral[3]) << 8)
                | round(geral[2] / geral[3]))
    return ((round(soma_r / peso_total) << 16)
            | (round(soma_g / peso_total) << 8)
            | round(soma_b / peso_total))


def cor_do_avatar(dados: bytes, *, reserva: int = COR_RESERVA) -> int:
    """Cor do avatar a partir dos bytes do PNG. Nunca levanta: na dúvida, a reserva."""
    try:
        return cor_de_destaque(pixels_do_png(dados))
    except Exception as exc:  # noqa: BLE001 - enfeite não pode derrubar resposta
        logger.debug("Não consegui medir a cor do avatar (%s); usando a reserva.", exc)
        return reserva


def hex_da_cor(cor: int) -> str:
    return f"#{cor:06X}"


# ------------------------------------------------------------------ mensagem V2

# Teto de texto por mensagem em Components V2 (o Discord aceita 4000 no total). Acima disso,
# é resposta comprida demais para um container: cai no envio em blocos de texto normal.
LIMITE_V2 = 3800
TITULO_V2 = "**🏮 Farol**"
RODAPE_V2 = "-# resposta automática do farol"
# Capa do card (imagem hospedada no próprio repositório). TODO(merge): quando a PR da sessão
# entrar na main, trocar a referência para o raw da main e apagar esta nota.
URL_BANNER_V2 = "https://raw.githubusercontent.com/astaabacate/Atlas/arena/01a0b13c-atlas/assets/banner-farol.png"


def montar_view(texto: str, cor: int, avatar_url: str | None = None) -> Any:
    """
    Monta a resposta como mensagem em Components V2: card com capa, cabeçalho com o nome
    (e o avatar, quando conhecido), divisória, a mensagem e um rodapé discreto.

    Enfeite na medida: hierarquia de leitura, sem virar cartão de Natal.
    O `LayoutView` do discord.py liga sozinho a flag de Components V2 na mensagem. Se qualquer
    coisa falhar (versão do discord.py, texto fora do limite, componente exótico), devolve None
    e quem chamou responde em texto normal — enfeite nunca pode custar a resposta.
    """
    import discord  # import tardio: a medição de cor não depende do discord.py

    conteudo = (texto or "").strip()
    if not conteudo or len(conteudo) > LIMITE_V2:
        return None
    try:
        view = discord.ui.LayoutView(timeout=None)
        filhos: list[Any] = []
        if URL_BANNER_V2:
            filhos.append(discord.ui.MediaGallery(
                discord.MediaGalleryItem(URL_BANNER_V2, description="Farol")))
        cabecalho: Any
        if avatar_url:
            cabecalho = discord.ui.Section(discord.ui.TextDisplay(TITULO_V2),
                                           accessory=discord.ui.Thumbnail(avatar_url))
        else:
            cabecalho = discord.ui.TextDisplay(TITULO_V2)
        filhos.append(cabecalho)
        filhos.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        filhos.append(discord.ui.TextDisplay(conteudo))
        filhos.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        filhos.append(discord.ui.TextDisplay(RODAPE_V2))
        view.add_item(discord.ui.Container(*filhos, accent_color=int(cor)))
        return view
    except Exception as exc:  # noqa: BLE001 - cai no texto simples
        logger.debug("Não consegui montar a mensagem V2 (%s); respondendo em texto.", exc)
        return None


class Aparencia:
    """
    A identidade visual do farol: cor de destaque (medida do próprio avatar) e a mensagem V2.

    A cor é medida UMA vez e fica em cache — ler a imagem a cada resposta seria desperdício de
    rede e de tempo. Se o dono trocar a foto com o bot no ar, o endereço do avatar muda e a cor
    é medida de novo na resposta seguinte (sem reiniciar nada).
    """

    def __init__(self, cor_fixa: int | None = None, *, v2: bool = True) -> None:
        self.cor_fixa: int | None = int(cor_fixa) if cor_fixa is not None else None
        self.cor: int = self.cor_fixa if self.cor_fixa is not None else COR_RESERVA
        self.cor_medida: bool = self.cor_fixa is not None
        self.v2 = v2
        self.avatar_url: str | None = None
        self._avatar_medido: str | None = None  # endereço da imagem que deu a cor atual

    async def preparar(self, user: Any, *, forcar: bool = False) -> int:
        """Mede a cor do avatar e guarda o endereço da imagem para o container."""
        avatar = getattr(user, "display_avatar", None)
        endereco = getattr(avatar, "url", None)
        self.avatar_url = endereco or self.avatar_url
        if avatar is None or self.cor_fixa is not None:
            # Cor fixada por ACCENT_COLOR: o dono mandou, ninguém mede por cima.
            return self.cor
        if not forcar and self.cor_medida and endereco == self._avatar_medido:
            return self.cor
        try:
            dados = await avatar.with_format("png").with_size(LADO_DO_AVATAR).read()
            self.cor = cor_do_avatar(dados, reserva=self.cor or COR_RESERVA)
            self.cor_medida = True
            self._avatar_medido = endereco
            logger.info("Cor do farol medida no avatar: %s", hex_da_cor(self.cor))
        except Exception as exc:  # noqa: BLE001 - segue com a reserva
            # Sem marcar como medido: a próxima resposta tenta de novo (a CDN pode ter caído).
            logger.debug("Não consegui medir a cor do avatar (%s); sigo com %s.",
                         exc, hex_da_cor(self.cor))
        return self.cor

    def view(self, texto: str) -> Any:
        """Mensagem em Components V2, ou None quando é melhor responder em texto."""
        if not self.v2:
            return None
        return montar_view(texto, self.cor, self.avatar_url)
