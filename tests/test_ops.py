"""
Testes das operações corrigidas (bugs encontrados pela suíte E2E ao vivo):

1. `create_channels` / `apply_template` / `import_structure` dentro de categoria
   → `TypeError: got multiple values for keyword argument 'category'`;
2. `set_icon` dizia "sucesso" sem chamar `guild.edit`;
3. `show_permissions.target` era ignorado.

Os duplos abaixo imitam o discord.py de verdade: assinaturas keyword-only e a
categoria injetando `category=self` ao delegar para a guild (é essa injeção que
estourava o TypeError em produção).
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import sys
import types
import unittest
from typing import Any

from brain import ops
from brain.executors import execute_tool
from brain.ops import _solid_png
from brain.tools import ToolContext, ToolError


# ------------------------------------------------------------------ duplos

class FakePerms:
    def __init__(self, **flags: bool) -> None:
        for name, value in flags.items():
            setattr(self, name, bool(value))


class FakeCategory:
    def __init__(self, name: str, cid: int, guild: "FakeGuild") -> None:
        self.name = name
        self.id = cid
        self.guild = guild
        self.channels: list[Any] = []

    # Igual ao discord.py: a categoria delega passando category=self.
    async def create_text_channel(self, name: str, **options: Any) -> Any:
        if "category" in options:  # pragma: no cover - só acontece com o bug
            raise TypeError("got multiple values for keyword argument 'category'")
        return await self.guild.create_text_channel(name, category=self, **options)

    async def create_voice_channel(self, name: str, **options: Any) -> Any:
        if "category" in options:  # pragma: no cover - só acontece com o bug
            raise TypeError("got multiple values for keyword argument 'category'")
        return await self.guild.create_voice_channel(name, category=self, **options)


class FakeEntity:
    """Cargo/membro de mentira, mas hashable (o discord.py usa como chave de overwrites)."""

    def __init__(self, name: str, eid: int, position: int = 0) -> None:
        self.name = name
        self.id = eid
        self.position = position
        self.nick = None
        self.display_name = name
        self.guild_permissions = FakePerms()
        self.top_role = None

    def is_default(self) -> bool:
        return False


class FakeChannel:
    def __init__(self, name: str, cid: int, category: Any = None, topic: str | None = None) -> None:
        self.name = name
        self.id = cid
        self.category = category
        self.topic = topic
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def edit(self, **kwargs: Any) -> "FakeChannel":
        self.calls.append(("edit", kwargs))
        return self

    async def delete(self) -> None:
        self.calls.append(("delete", {}))

    async def set_permissions(self, target: Any, **kwargs: Any) -> None:
        self.calls.append(("set_permissions", {"target": target, **kwargs}))


class FakeGuild:
    def __init__(self) -> None:
        self.name = "Servidor Teste"
        self.icon = None
        self.description = ""
        self._seq = 5000
        self.channels: list[Any] = []
        self.categories: list[Any] = []
        self.roles = [types.SimpleNamespace(id=1, name="@everyone", position=0, is_default=lambda: True)]
        self.members: list[Any] = []
        self.me = types.SimpleNamespace(id=999, name="farol", guild_permissions=FakePerms(administrator=True),
                                        top_role=types.SimpleNamespace(id=2, name="farol", position=9))
        self.edits: list[dict[str, Any]] = []
        self.creates: list[str] = []

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    async def create_text_channel(self, name: str, *, category: Any = None, topic: str | None = None,
                                 **_: Any) -> FakeChannel:
        channel = FakeChannel(name, self._next_id(), category=category, topic=topic)
        self.creates.append("text")
        self.channels.append(channel)
        return channel

    async def create_voice_channel(self, name: str, *, category: Any = None, **_: Any) -> FakeChannel:
        channel = FakeChannel(name, self._next_id(), category=category)
        self.creates.append("voice")
        self.channels.append(channel)
        return channel

    async def create_category(self, name: str, **_: Any) -> FakeCategory:
        category = FakeCategory(name, self._next_id(), self)
        self.creates.append("category")
        self.channels.append(category)
        self.categories.append(category)
        return category

    async def create_role(self, name: str, **kwargs: Any) -> Any:
        role = types.SimpleNamespace(id=self._next_id(), name=name, position=1, is_default=lambda: False,
                                     **{k: v for k, v in kwargs.items() if k not in ("permissions",)})
        self.creates.append("role")
        self.roles.append(role)
        return role

    async def edit(self, **kwargs: Any) -> "FakeGuild":
        self.edits.append(kwargs)
        for key in ("name", "description", "icon"):
            if key in kwargs:
                setattr(self, key, kwargs[key])
        return self


def make_ctx(guild: FakeGuild | None = None) -> tuple[ToolContext, FakeGuild]:
    guild = guild or FakeGuild()
    actor = types.SimpleNamespace(id=7, name="dono", guild_permissions=FakePerms(administrator=True))
    channel = FakeChannel("geral", 123)
    return ToolContext(guild=guild, channel=channel, actor=actor), guild


# ------------------------------------------------------------------ bug 1

class TestCanaisDentroDeCategoria(unittest.TestCase):
    def test_create_channels_inside_category_nao_duplica_category(self) -> None:
        ctx, guild = make_ctx()
        cat = asyncio.run(guild.create_category("📁 Categoria"))

        out = asyncio.run(execute_tool("create_channels", {"channels": [
            {"name": "dentro-texto", "type": "text", "category": str(cat.id), "topic": "oi"},
            {"name": "dentro-voz", "type": "voice", "category": str(cat.id)},
        ]}, ctx))

        self.assertIn("2 canal(is)", out)
        texto = next(c for c in guild.channels if c.name == "dentro-texto")
        voz = next(c for c in guild.channels if c.name == "dentro-voz")
        self.assertIs(texto.category, cat)
        self.assertIs(voz.category, cat)
        self.assertEqual(texto.topic, "oi")

    def test_cai_para_a_guild_quando_categoria_nao_tem_criador(self) -> None:
        ctx, guild = make_ctx()
        cat = types.SimpleNamespace(id=4242, name="CatSimples")  # sem create_*_channel
        guild.categories.append(cat)

        asyncio.run(execute_tool("create_channels", {"channels": [
            {"name": "filho", "type": "text", "category": "CatSimples"},
        ]}, ctx))

        filho = next(c for c in guild.channels if c.name == "filho")
        self.assertIs(filho.category, cat)

    def test_apply_template_coloca_canais_nas_categorias(self) -> None:
        ctx, guild = make_ctx()
        out = asyncio.run(execute_tool("apply_template", {"template": "gamer"}, ctx))

        self.assertIn("sucesso", out.lower())
        tpl = ops.TEMPLATES_DATA["gamer"]
        criadas = {c.name: c for c in guild.categories}
        self.assertEqual(len(criadas), len(tpl["categories"]))
        for cat_data in tpl["categories"]:
            cat = criadas[cat_data["name"]]
            for ch in cat_data["channels"]:
                alvo = next(c for c in guild.channels if c.name == ch["name"])
                self.assertIs(alvo.category, cat, f"{ch['name']} ficou fora de {cat.name}")
        for role in tpl["roles"]:
            self.assertTrue(any(r.name == role["name"] for r in guild.roles), f"cargo {role['name']} faltando")

    def test_import_structure_coloca_canais_na_categoria(self) -> None:
        ctx, guild = make_ctx()
        estrutura = json.dumps({
            "roles": [{"name": "Importado"}],
            "categories": [{"name": "Cat Import", "channels": [
                {"name": "imp-texto", "type": "text", "topic": "t"},
                {"name": "imp-voz", "type": "voice"},
            ]}],
        })

        asyncio.run(execute_tool("import_structure", {"structure_json": estrutura}, ctx))

        cat = guild.categories[0]
        for nome in ("imp-texto", "imp-voz"):
            alvo = next(c for c in guild.channels if c.name == nome)
            self.assertIs(alvo.category, cat)


# ------------------------------------------------------------------ bug 2

class TestSetIcon(unittest.TestCase):
    PNG = b"\x89PNG\r\n\x1a\nfake"

    def test_baixa_a_url_e_envia_os_bytes(self) -> None:
        ctx, guild = make_ctx()
        urls: list[str] = []
        original = ops._download_image

        async def fake_download(url: str) -> bytes:
            urls.append(url)
            return self.PNG

        ops._download_image = fake_download
        try:
            out = asyncio.run(execute_tool("set_icon", {"url": "https://exemplo.com/i.png"}, ctx))
        finally:
            ops._download_image = original

        self.assertEqual(urls, ["https://exemplo.com/i.png"])
        self.assertEqual(guild.edits, [{"icon": self.PNG}])
        self.assertEqual(guild.icon, self.PNG)
        self.assertIn("sucesso", out.lower())

    def test_aceita_data_uri_sem_rede(self) -> None:
        ctx, guild = make_ctx()
        uri = "data:image/png;base64," + base64.b64encode(self.PNG).decode()

        asyncio.run(execute_tool("set_icon", {"url": uri}, ctx))

        self.assertEqual(guild.icon, self.PNG)

    def test_estilo_gera_png_valido(self) -> None:
        ctx, guild = make_ctx()
        asyncio.run(execute_tool("set_icon", {"style": "gamer"}, ctx))

        icone = guild.icon
        self.assertEqual(bytes(icone[:8]), b"\x89PNG\r\n\x1a\n")
        largura, altura = struct.unpack(">II", bytes(icone[16:24]))
        self.assertGreaterEqual(min(largura, altura), 128)

    def test_estilos_diferentes_geram_icones_diferentes(self) -> None:
        self.assertNotEqual(_solid_png((1, 2, 3)), _solid_png((200, 100, 50)))

    def test_falha_no_download_nao_finge_sucesso(self) -> None:
        ctx, guild = make_ctx()
        original = ops._download_image

        async def download_quebrado(url: str) -> bytes:
            raise ToolError(f"Falha ao baixar a imagem ({url})")

        ops._download_image = download_quebrado
        try:
            with self.assertRaises(ToolError) as ctx_erro:
                asyncio.run(execute_tool("set_icon", {"url": "https://exemplo.com/x.png"}, ctx))
        finally:
            ops._download_image = original

        self.assertNotIn("sucesso", str(ctx_erro.exception).lower())
        self.assertEqual(guild.edits, [])
        self.assertIsNone(guild.icon)

    def test_sem_editor_disponivel_erro_claro(self) -> None:
        ctx, _ = make_ctx()
        ctx.guild = types.SimpleNamespace(name="Sem edição")
        with self.assertRaises(ToolError):
            asyncio.run(execute_tool("set_icon", {"style": "minimal"}, ctx))

    def test_erro_do_discord_vira_toolerror(self) -> None:
        ctx, guild = make_ctx()

        async def edit_quebrado(**kwargs: Any) -> None:
            raise RuntimeError("Invalid Form Body (icon)")

        guild.edit = edit_quebrado  # type: ignore[assignment]
        original = ops._download_image

        async def fake_download(url: str) -> bytes:
            return self.PNG

        ops._download_image = fake_download
        try:
            with self.assertRaises(ToolError) as ctx_erro:
                asyncio.run(execute_tool("set_icon", {"url": "https://exemplo.com/i.png"}, ctx))
        finally:
            ops._download_image = original
        self.assertIn("recusou", str(ctx_erro.exception))


# -------------------------------------------------- _download_image (rede)

class _FakeResponse:
    def __init__(self, status: int = 200, headers: dict[str, str] | None = None, body: bytes = b"") -> None:
        self.status = status
        self.headers = headers or {"Content-Type": "image/png"}
        self._body = body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def read(self) -> bytes:
        return self._body


class _FakeSession:
    last: "_FakeSession | None" = None

    def __init__(self, response: _FakeResponse, **_: Any) -> None:
        self.response = response
        _FakeSession.last = self

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def get(self, url: str) -> _FakeResponse:
        self.url = url
        return self.response


class _FakeAiohttp(types.ModuleType):
    def __init__(self, response: _FakeResponse) -> None:
        super().__init__("aiohttp")
        self.ClientSession = lambda **kwargs: _FakeSession(response, **kwargs)
        self.ClientTimeout = lambda **kwargs: kwargs


class TestDownloadImage(unittest.TestCase):
    def _com_aiohttp(self, response: _FakeResponse) -> Any:
        fake = _FakeAiohttp(response)
        original = sys.modules.get("aiohttp")
        sys.modules["aiohttp"] = fake
        try:
            return asyncio.run(ops._download_image("https://exemplo.com/icone.png"))
        finally:
            if original is None:
                sys.modules.pop("aiohttp", None)
            else:
                sys.modules["aiohttp"] = original

    def test_baixa_imagem_valida(self) -> None:
        self.assertEqual(self._com_aiohttp(_FakeResponse(body=b"PNGDATA")), b"PNGDATA")

    def test_status_diferente_de_200_falha(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self._com_aiohttp(_FakeResponse(status=404))
        self.assertIn("404", str(ctx.exception))

    def test_content_type_nao_imagem_falha(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self._com_aiohttp(_FakeResponse(headers={"Content-Type": "text/html"}, body=b"<html>"))
        self.assertIn("text/html", str(ctx.exception))

    def test_imagem_vazia_falha(self) -> None:
        with self.assertRaises(ToolError):
            self._com_aiohttp(_FakeResponse(body=b""))

    def test_imagem_grande_demais_falha(self) -> None:
        original = ops.MAX_ICON_BYTES
        ops.MAX_ICON_BYTES = 4
        try:
            with self.assertRaises(ToolError) as ctx:
                self._com_aiohttp(_FakeResponse(body=b"12345"))
        finally:
            ops.MAX_ICON_BYTES = original
        self.assertIn("no máximo", str(ctx.exception))


# ------------------------------------------------------------------ bug 3

class TestShowPermissions(unittest.TestCase):
    def _ctx_com_overwrites(self) -> tuple[ToolContext, FakeGuild]:
        ctx, guild = make_ctx()
        canal = FakeChannel("geral", 123)
        canal.overwrites = {}
        ctx.channel = canal
        guild.channels.append(canal)
        guild.roles.append(FakeEntity("cargo-alpha", 77, position=1))
        guild.roles.append(FakeEntity("cargo-beta", 78, position=1))
        guild.members.append(FakeEntity("bia", 55))
        canal.overwrites[guild.roles[1]] = "alpha-ow"
        canal.overwrites[guild.roles[2]] = "beta-ow"
        return ctx, guild

    def test_target_filtra_apenas_o_alvo_pedido(self) -> None:
        ctx, _ = self._ctx_com_overwrites()
        out = asyncio.run(execute_tool("show_permissions", {"channel": "123", "target": "cargo-alpha"}, ctx))

        self.assertIn("cargo-alpha", out)
        self.assertIn("alpha-ow", out)
        self.assertNotIn("cargo-beta", out)

    def test_target_por_mencao_de_cargo(self) -> None:
        ctx, _ = self._ctx_com_overwrites()
        out = asyncio.run(execute_tool("show_permissions", {"channel": "123", "target": "<@&78>"}, ctx))

        self.assertIn("cargo-beta", out)
        self.assertNotIn("cargo-alpha", out)

    def test_target_sem_overwrite_avisa_que_herda(self) -> None:
        ctx, _ = self._ctx_com_overwrites()
        out = asyncio.run(execute_tool("show_permissions", {"channel": "123", "target": "bia"}, ctx))

        self.assertIn("não tem permissões personalizadas", out)

    def test_target_por_id_busca_na_api_quando_o_cache_esta_vazio(self) -> None:
        """
        Sem a intent de membros, `guild.members` vem vazio: o alvo por ID precisa ser buscado
        com `fetch_member` (foi o que o teste ao vivo pegou em show_permissions(target=<id>)).
        """
        ctx, guild = make_ctx()
        canal = FakeChannel("geral", 123)
        canal.overwrites = {}
        ctx.channel = canal
        guild.channels.append(canal)
        guild.members = []  # cache vazio (sem MEMBERS intent)

        alvo = FakeEntity("dono", 4242)
        buscados: list[int] = []

        async def fetch_member(mid: int) -> Any:
            buscados.append(mid)
            if mid != alvo.id:
                raise LookupError("Unknown Member")
            return alvo

        guild.fetch_member = fetch_member  # type: ignore[attr-defined]
        canal.overwrites[alvo] = "ow-do-dono"

        out = asyncio.run(execute_tool("show_permissions", {"channel": "123", "target": str(alvo.id)}, ctx))

        self.assertEqual(buscados, [alvo.id])
        self.assertIn("dono", out)
        self.assertIn("ow-do-dono", out)

    def test_target_por_id_sem_overwrite_avisa_que_herda(self) -> None:
        ctx, guild = make_ctx()
        canal = FakeChannel("geral", 123)
        canal.overwrites = {}
        ctx.channel = canal
        guild.channels.append(canal)
        guild.members = []
        alvo = FakeEntity("dono", 4242)

        async def fetch_member(mid: int) -> Any:
            return alvo

        guild.fetch_member = fetch_member  # type: ignore[attr-defined]

        out = asyncio.run(execute_tool("show_permissions", {"channel": "123", "target": str(alvo.id)}, ctx))
        self.assertIn("não tem permissões personalizadas", out)

    def test_alvo_inexistente_erro_claro(self) -> None:
        ctx, _ = self._ctx_com_overwrites()
        with self.assertRaises(ToolError) as ctx_erro:
            asyncio.run(execute_tool("show_permissions", {"channel": "123", "target": "ninguem-aqui"}, ctx))
        self.assertIn("ninguem-aqui", str(ctx_erro.exception))

    def test_sem_ow_avisa_que_nao_tem_permissao_personalizada(self) -> None:
        ctx, _ = make_ctx()
        canal = FakeChannel("vazio", 321)
        canal.overwrites = {}
        ctx.channel = canal
        ctx.guild.channels.append(canal)

        out = asyncio.run(execute_tool("show_permissions", {"channel": "321"}, ctx))
        self.assertIn("não possui permissões personalizadas", out)

    def test_formato_usa_allow_e_deny(self) -> None:
        class Overwrite:
            def pair(self) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
                return ([("view_channel", True)], [("send_messages", True), ("view_channel", False)])

        texto = ops._format_overwrite(Overwrite())
        self.assertIn("view_channel", texto)
        self.assertIn("send_messages", texto)

    def test_formato_overwrite_neutro(self) -> None:
        class Overwrite:
            def pair(self) -> tuple[list[Any], list[Any]]:
                return ([], [])

        self.assertIn("neutro", ops._format_overwrite(Overwrite()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
