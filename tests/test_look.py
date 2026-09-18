"""
A cara das respostas: cor medida do avatar + mensagem em Components V2.

O dono pediu (18/09): "queria que ele respondesse em embed naquele componente V2 ... não sei
qual a cor vou usar, queria uma que combinasse com a foto dele". Então a cor não é chutada:
ela é MEDIDA do avatar (PNG decodificado sem biblioteca externa) e o container usa essa cor.

Estes testes cobrem o caminho inteiro com um PNG de verdade montado aqui dentro (RGB e RGBA,
todos os filtros por linha), o fallback quando a imagem é ruim, e a montagem do LayoutView.
"""

from __future__ import annotations

import asyncio
import struct
import unittest
import zlib
from typing import Any

from core import look


# --------------------------------------------------------------- PNG de teste

def _png(largura: int, altura: int, pixels: list[list[tuple[int, int, int, int]]],
         *, alfa: bool = False, filtro: int = 0) -> bytes:
    """Monta um PNG 8 bits de verdade (mesmos filtros do formato) para testar o decodificador."""
    canais = 4 if alfa else 3
    linhas = bytearray()
    anterior = bytearray(len(pixels[0]) * canais)
    for linha in pixels:
        bruto = bytearray()
        for p in linha:
            bruto += bytes(p[:canais])
        linhas.append(filtro)
        if filtro == 0:
            linhas += bruto
        elif filtro == 1:  # Sub (resíduo em relação ao pixel à esquerda, por canal)
            for i, valor in enumerate(bruto):
                esq = bruto[i - canais] if i >= canais else 0
                linhas.append((valor - esq) & 0xFF)
        elif filtro == 2:  # Up (em relação à linha de cima)
            for i, valor in enumerate(bruto):
                linhas.append((valor - anterior[i]) & 0xFF)
        elif filtro == 3:  # Average
            for i, valor in enumerate(bruto):
                esq = bruto[i - canais] if i >= canais else 0
                linhas.append((valor - ((esq + anterior[i]) >> 1)) & 0xFF)
        elif filtro == 4:  # Paeth
            for i, valor in enumerate(bruto):
                esq = bruto[i - canais] if i >= canais else 0
                cima = anterior[i]
                diag = anterior[i - canais] if i >= canais else 0
                pred = esq + cima - diag
                pa, pb, pc = abs(pred - esq), abs(pred - cima), abs(pred - diag)
                escolhido = esq if (pa <= pb and pa <= pc) else (cima if pb <= pc else diag)
                linhas.append((valor - escolhido) & 0xFF)
        anterior = bruto
    tipo = 6 if alfa else 2
    ihdr = struct.pack(">IIBB", largura, altura, 8, tipo) + b"\x00\x00\x00"
    dados = b"\x89PNG\r\n\x1a\n"
    for tipo_chunk, conteudo in ((b"IHDR", ihdr), (b"IDAT", zlib.compress(bytes(linhas)))):
        dados += struct.pack(">I", len(conteudo)) + tipo_chunk + conteudo
        dados += struct.pack(">I", zlib.crc32(tipo_chunk + conteudo) & 0xFFFFFFFF)
    dados += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return dados


def _cor_de(pixels: list[list[tuple[int, int, int, int]]], cor: tuple[int, int, int, int],
            amostra: int = 1) -> list[list[tuple[int, int, int, int]]]:
    """Pinta um quadrado de `cor` no meio de um fundo branco."""
    altura, largura = len(pixels), len(pixels[0])
    for y in range(altura // 2 - amostra, altura // 2 + amostra):
        for x in range(largura // 2 - amostra, largura // 2 + amostra):
            pixels[y][x] = cor
    return pixels


def _fundo_branco(largura: int = 4, altura: int = 4) -> list[list[tuple[int, int, int, int]]]:
    return [[(255, 255, 255, 255)] * largura for _ in range(altura)]


# --------------------------------------------------------------- cor

class TestLeituraDePng(unittest.TestCase):
    def test_decodifica_rgb(self) -> None:
        px = _fundo_branco(2, 2)
        px[0][0] = (255, 0, 0, 255)
        lidos = look.pixels_do_png(_png(2, 2, px))
        self.assertEqual(lidos[0], (255, 0, 0, 255))
        self.assertEqual(lidos[1], (255, 255, 255, 255))

    def test_decodifica_rgba(self) -> None:
        px = _fundo_branco(2, 2)
        px[1][1] = (0, 0, 255, 128)
        lidos = look.pixels_do_png(_png(2, 2, px, alfa=True))
        self.assertEqual(lidos[3], (0, 0, 255, 128))

    def test_todos_os_filtros_por_linha(self) -> None:
        px = _fundo_branco(3, 3)
        esperado = []
        for filtro in (0, 1, 2, 3, 4):
            lidos = look.pixels_do_png(_png(3, 3, px, filtro=filtro))
            esperado.append(lidos)
            self.assertEqual(lidos[0], (255, 255, 255, 255), f"filtro {filtro}")

    def test_arquivo_que_nao_e_png_levanta(self) -> None:
        with self.assertRaises(ValueError):
            look.pixels_do_png(b"nao sou um png")


class TestCorDeDestaque(unittest.TestCase):
    def test_acha_a_cor_viva_e_ignora_o_fundo_branco(self) -> None:
        px = _cor_de(_fundo_branco(8, 8), (220, 30, 40, 255), amostra=2)
        cor = look.cor_do_avatar(_png(8, 8, px, alfa=True))
        r, g, b = (cor >> 16) & 0xFF, (cor >> 8) & 0xFF, cor & 0xFF
        self.assertGreater(r, 180, "o vermelho do desenho tem que dominar")
        self.assertLess(g, 90)
        self.assertLess(b, 90)

    def test_imagem_toda_cinza_cai_na_media(self) -> None:
        px = [[(120, 120, 120, 255)] * 4 for _ in range(4)]
        cor = look.cor_do_avatar(_png(4, 4, px))
        self.assertEqual(cor, 0x787878)

    def test_foto_de_uma_cor_so_devolve_exatamente_essa_cor(self) -> None:
        """Truncar a média errava por 1 (230 → 229); a cor da foto tem que sair inteira."""
        px = [[(230, 40, 60, 255)] * 64 for _ in range(64)]
        self.assertEqual(look.cor_do_avatar(_png(64, 64, px, alfa=True)), 0xE6283C)

    def test_bytes_invalidos_devolvem_a_reserva(self) -> None:
        self.assertEqual(look.cor_do_avatar(b"lixo"), look.COR_RESERVA)

    def test_pixels_transparentes_sao_ignorados(self) -> None:
        px = [[(255, 0, 0, 0)] * 4 for _ in range(4)]
        px = _cor_de(px, (0, 140, 255, 255), amostra=1)
        cor = look.cor_do_avatar(_png(4, 4, px, alfa=True))
        b = cor & 0xFF
        self.assertGreater(b, 120, "o azul opaco tem que ganhar do vermelho transparente")

    def test_hex_da_cor(self) -> None:
        self.assertEqual(look.hex_da_cor(0x5865F2), "#5865F2")


# --------------------------------------------------------------- mensagem V2

class TestMensagemV2(unittest.TestCase):
    def test_monta_container_com_a_cor_do_farol(self) -> None:
        import discord

        view = look.montar_view("🗑️ Apaguei 3 canais.", 0x5865F2)
        assert view is not None
        self.assertIsInstance(view, discord.ui.LayoutView)
        container = view.children[0]
        self.assertIsInstance(container, discord.ui.Container)
        self.assertEqual(container.accent_color, 0x5865F2)
        self.assertIsInstance(container.children[0], discord.ui.TextDisplay)

    def test_com_avatar_usa_secao_com_miniatura(self) -> None:
        import discord

        view = look.montar_view("Pronto!", 0x112233, "https://cdn.discordapp.com/avatar.png")
        assert view is not None
        secao = view.children[0].children[0]
        self.assertIsInstance(secao, discord.ui.Section)
        self.assertIsInstance(secao.accessory, discord.ui.Thumbnail)

    def test_texto_longo_demais_nao_vira_container(self) -> None:
        self.assertIsNone(look.montar_view("x" * (look.LIMITE_V2 + 1), 0x112233))

    def test_texto_vazio_nao_vira_container(self) -> None:
        self.assertIsNone(look.montar_view("   ", 0x112233))


class TestAparencia(unittest.TestCase):
    class _Asset:
        def __init__(self, dados: bytes, erro: Exception | None = None, *,
                     url: str = "https://cdn.discordapp.com/avatars/1/fake.png") -> None:
            self.dados = dados
            self.erro = erro
            self.url = url
            self.formatos: list[str] = []
            self.tamanhos: list[int] = []

        def with_format(self, fmt: str) -> "TestAparencia._Asset":
            self.formatos.append(fmt)
            return self

        def with_size(self, tamanho: int) -> "TestAparencia._Asset":
            self.tamanhos.append(tamanho)
            return self

        async def read(self) -> bytes:
            if self.erro:
                raise self.erro
            return self.dados

    class _Usuario:
        def __init__(self, asset: Any) -> None:
            self.display_avatar = asset

    def _png_vermelho(self) -> bytes:
        px = _cor_de(_fundo_branco(8, 8), (230, 40, 60, 255), amostra=2)
        return _png(8, 8, px, alfa=True)

    def test_mede_a_cor_do_avatar_em_png(self) -> None:
        asset = self._Asset(self._png_vermelho())
        aparencia = look.Aparencia()
        cor = asyncio.run(aparencia.preparar(self._Usuario(asset)))
        self.assertEqual(asset.formatos, ["png"], "a cor é medida do PNG, não do webp animado")
        self.assertEqual(asset.tamanhos, [look.LADO_DO_AVATAR])
        self.assertGreater((cor >> 16) & 0xFF, 180)
        self.assertTrue(aparencia.cor_medida)

    def test_falha_de_rede_mantem_a_reserva_e_nao_quebra(self) -> None:
        asset = self._Asset(b"", erro=RuntimeError("sem rede"))
        aparencia = look.Aparencia()
        cor = asyncio.run(aparencia.preparar(self._Usuario(asset)))
        self.assertEqual(cor, look.COR_RESERVA)
        self.assertFalse(aparencia.cor_medida)

    def test_cor_fixa_no_config_nao_e_medida(self) -> None:
        asset = self._Asset(self._png_vermelho())
        aparencia = look.Aparencia(0x00FF00)
        cor = asyncio.run(aparencia.preparar(self._Usuario(asset)))
        self.assertEqual(cor, 0x00FF00)
        self.assertEqual(asset.formatos, [], "com cor fixa não precisa baixar o avatar")

    def test_view_da_aparencia_usa_a_cor_medida(self) -> None:
        asset = self._Asset(self._png_vermelho())
        aparencia = look.Aparencia()
        asyncio.run(aparencia.preparar(self._Usuario(asset)))
        view = aparencia.view("🗑️ Exclusão concluída: #teste (✅ 1/1).")
        assert view is not None
        self.assertEqual(view.children[0].accent_color, aparencia.cor)

    def test_v2_desligado_devolve_none(self) -> None:
        aparencia = look.Aparencia(0x112233, v2=False)
        self.assertIsNone(aparencia.view("Pronto!"))

    def test_avatar_medido_uma_vez_so(self) -> None:
        asset = self._Asset(self._png_vermelho())
        aparencia = look.Aparencia()
        usuario = self._Usuario(asset)
        asyncio.run(aparencia.preparar(usuario))
        asyncio.run(aparencia.preparar(usuario))
        self.assertEqual(len(asset.formatos), 1, "a cor fica em cache; não baixa a cada resposta")

    def test_foto_trocada_com_o_bot_no_ar_e_medida_de_novo(self) -> None:
        """O dono vai colocar a foto dele: a cor nova tem que valer sem reiniciar o farol."""
        antiga = self._Asset(self._png_vermelho())
        aparencia = look.Aparencia()
        asyncio.run(aparencia.preparar(self._Usuario(antiga)))
        primeira = aparencia.cor

        nova = self._Asset(self._png_vermelho(), url="https://cdn.discordapp.com/avatars/1/outra.png")
        asyncio.run(aparencia.preparar(self._Usuario(nova)))
        self.assertEqual(len(nova.formatos), 1, "endereço novo = cor medida de novo")
        self.assertNotEqual(aparencia.cor, look.COR_RESERVA)
        self.assertGreater((aparencia.cor >> 16) & 0xFF, 180)
        self.assertEqual(primeira, aparencia.cor, "as duas fotos de teste são iguais")

    def test_cor_fixa_nunca_e_sobrescrita_pela_foto(self) -> None:
        aparencia = look.Aparencia(0x00FF00)
        primeira = self._Asset(self._png_vermelho(), url="https://cdn.discordapp.com/1.png")
        segunda = self._Asset(self._png_vermelho(), url="https://cdn.discordapp.com/2.png")
        asyncio.run(aparencia.preparar(self._Usuario(primeira)))
        asyncio.run(aparencia.preparar(self._Usuario(segunda)))
        self.assertEqual(aparencia.cor, 0x00FF00)
        self.assertEqual(primeira.formatos + segunda.formatos, [],
                         "ACCENT_COLOR fixo manda: nada de medir por cima")

    def test_falha_na_leitura_tenta_de_novo_na_proxima(self) -> None:
        quebrado = self._Asset(b"", erro=RuntimeError("CDN fora"))
        aparencia = look.Aparencia()
        asyncio.run(aparencia.preparar(self._Usuario(quebrado)))
        self.assertFalse(aparencia.cor_medida, "falhou = não marca como medido")
        certo = self._Asset(self._png_vermelho())
        asyncio.run(aparencia.preparar(self._Usuario(certo)))
        self.assertTrue(aparencia.cor_medida, "a resposta seguinte mede de novo")
        self.assertGreater((aparencia.cor >> 16) & 0xFF, 180)


if __name__ == "__main__":
    unittest.main()


class TestConfigDaAparencia(unittest.TestCase):
    """ACCENT_COLOR e MENSAGEM_V2 (a cara do bot também é configuração)."""

    def _config(self, **env: str):
        from config import Config

        base = {"DISCORD_TOKEN": "123456789012345678." + "a" * 6 + "." + "b" * 27}
        base.update(env)
        return Config.from_env(base)

    def test_sem_accennt_color_mede_do_avatar(self) -> None:
        cfg = self._config()
        self.assertIsNone(cfg.accent_color)
        self.assertTrue(cfg.mensagem_v2)

    def test_aceita_hex_com_e_sem_cerquilha(self) -> None:
        self.assertEqual(self._config(ACCENT_COLOR="#5865F2").accent_color, 0x5865F2)
        self.assertEqual(self._config(ACCENT_COLOR="5865f2").accent_color, 0x5865F2)
        self.assertEqual(self._config(ACCENT_COLOR="0xFFAA00").accent_color, 0xFFAA00)

    def test_auto_e_valor_invalido_caem_na_medicao(self) -> None:
        self.assertIsNone(self._config(ACCENT_COLOR="auto").accent_color)
        self.assertIsNone(self._config(ACCENT_COLOR="roxo-bonito").accent_color)

    def test_mensagem_v2_pode_ser_desligada(self) -> None:
        self.assertFalse(self._config(MENSAGEM_V2="false").mensagem_v2)
