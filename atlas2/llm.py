"""
Cliente do OmniRoute (qualquer gateway OpenAI-compatível serve) com STREAMING.

Streaming é o que faz o usuário ver texto na tela no primeiro segundo em vez de encarar um
"digitando…" por 4s. A chave vem do ambiente — nunca do código (repositório é público).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import aiohttp

logger = logging.getLogger("atlas2.llm")


class LLMIndisponivel(Exception):
    """Nenhuma resposta utilizável do gateway (sem chave, rede, limite, modelo fora)."""


@dataclass
class Chamada:
    id: str
    nome: str
    argumentos: str = ""

    @property
    def dados(self) -> dict[str, Any]:
        try:
            valor = json.loads(self.argumentos or "{}")
            return valor if isinstance(valor, dict) else {}
        except Exception:  # noqa: BLE001 - argumento quebrado não pode derrubar o turno
            return {}


@dataclass
class Resposta:
    texto: str = ""
    chamadas: list[Chamada] = field(default_factory=list)


class LLM:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.sessao: aiohttp.ClientSession | None = None

    async def fechar(self) -> None:
        if self.sessao is not None and not self.sessao.closed:
            await self.sessao.close()
        self.sessao = None

    async def _sessao(self) -> aiohttp.ClientSession:
        if self.sessao is None or self.sessao.closed:
            self.sessao = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.cfg.timeout_llm, sock_read=self.cfg.timeout_llm)
            )
        return self.sessao

    async def conversar(
        self,
        mensagens: list[dict[str, Any]],
        ferramentas: list[dict[str, Any]] | None = None,
        ao_pedaco: Callable[[str], Awaitable[None]] | None = None,
        modelo: str | None = None,
    ) -> Resposta:
        """
        Manda a conversa e devolve a resposta. Se `ao_pedaco` for dado, cada pedaço de texto é
        entregue na hora (é assim que a resposta aparece na tela enquanto sai do modelo).
        """
        if not self.cfg.tem_llm:
            raise LLMIndisponivel("sem chave/endereço do OmniRoute configurado")

        corpo: dict[str, Any] = {
            "model": modelo or self.cfg.modelo_rapido or self.cfg.modelo,
            "messages": mensagens,
            "stream": True,
            "max_tokens": 900,
            "temperature": 0.2,
        }
        if ferramentas:
            corpo["tools"] = ferramentas
            corpo["tool_choice"] = "auto"

        url = f"{self.cfg.base_url}/chat/completions"
        cabecalhos = {"Authorization": f"Bearer {self.cfg.chave}", "Content-Type": "application/json"}
        sessao = await self._sessao()
        resposta = Resposta()
        parciais: dict[int, Chamada] = {}
        erro: str | None = None
        try:
            async with sessao.post(url, json=corpo, headers=cabecalhos) as resposta_http:
                if resposta_http.status >= 400:
                    corpo_erro = (await resposta_http.text())[:300]
                    raise LLMIndisponivel(f"HTTP {resposta_http.status}: {corpo_erro}")
                tipo = resposta_http.headers.get("Content-Type", "")
                if "text/event-stream" not in tipo:
                    # Alguns gateways ignoram stream=true: trata como JSON de uma vez.
                    dado = await resposta_http.json(content_type=None)
                    return self._de_json(dado, ao_pedaco)
                async for linha_bruta in resposta_http.content:
                    linha = linha_bruta.decode("utf-8", "replace").strip()
                    if not linha or not linha.startswith("data:"):
                        continue
                    dado_txt = linha[5:].strip()
                    if dado_txt == "[DONE]":
                        break
                    try:
                        dado = json.loads(dado_txt)
                    except json.JSONDecodeError:
                        continue
                    pedaco, chamadas = self._do_pedaco(dado, parciais)
                    if pedaco:
                        resposta.texto += pedaco
                        if ao_pedaco is not None:
                            await ao_pedaco(pedaco)
                    if chamadas:
                        resposta.chamadas = chamadas
        except LLMIndisponivel:
            raise
        except Exception as exc:  # noqa: BLE001 - rede do gateway grátis é instável por natureza
            erro = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("Falha falando com o OmniRoute: %s", erro)

        if not resposta.texto.strip() and not resposta.chamadas:
            raise LLMIndisponivel(erro or "o gateway respondeu vazio")
        return resposta

    # ------------------------------------------------------------------ parsing
    @staticmethod
    def _do_pedaco(dado: dict[str, Any], parciais: dict[int, Chamada]) -> tuple[str, list[Chamada]]:
        escolhas = dado.get("choices") or []
        if not escolhas:
            return "", []
        delta = escolhas[0].get("delta") or escolhas[0].get("message") or {}
        texto = delta.get("content") or ""
        for bruto in delta.get("tool_calls") or []:
            indice = int(bruto.get("index", 0) or 0)
            atual = parciais.setdefault(indice, Chamada(id=f"call_{indice}", nome=""))
            if bruto.get("id"):
                atual.id = bruto["id"]
            funcao = bruto.get("function") or {}
            if funcao.get("name"):
                atual.nome = funcao["name"]
            if funcao.get("arguments"):
                atual.argumentos += funcao["arguments"]
        prontas = [c for c in parciais.values() if c.nome]
        return texto, prontas

    def _de_json(self, dado: dict[str, Any], ao_pedaco) -> Resposta:
        escolhas = dado.get("choices") or []
        if not escolhas:
            raise LLMIndisponivel("resposta sem 'choices'")
        mensagem = escolhas[0].get("message") or {}
        chamadas = []
        for bruto in mensagem.get("tool_calls") or []:
            funcao = bruto.get("function") or {}
            chamadas.append(Chamada(id=bruto.get("id", "call_0"), nome=funcao.get("name", ""),
                                    argumentos=funcao.get("arguments", "") or ""))
        texto = (mensagem.get("content") or "").strip()
        if not texto and not chamadas:
            raise LLMIndisponivel("resposta vazia do gateway")
        return Resposta(texto=texto, chamadas=chamadas)
