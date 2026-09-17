"""
Provedor de corrida concorrente (AutoProvider).
Dispara a requisição simultaneamente para todos os corredores configurados com o mesmo timeout.
O primeiro que responder com sucesso vence e os demais são cancelados imediatamente.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llm.base import ChatProvider, LLMResponse
from llm.free_providers import (
    BlackboxProvider,
    GitHubModelsProvider,
    KiloProvider,
    LLM7Provider,
    OVHProvider,
    PollinationsProvider,
    ZenProvider,
)
from llm.key_providers import AnthropicProvider, GeminiProvider, OpenAIProvider

logger = logging.getLogger("farol.llm.auto")


class AutoProvider(ChatProvider):
    name = "auto"

    def __init__(self, providers: list[ChatProvider] | None = None) -> None:
        self.providers: list[ChatProvider] = providers if providers is not None else []

    @classmethod
    def create_default(
        cls,
        github_token: str = "",
        api_key: str = "",
        custom_provider: str = "",
        custom_model: str = "",
        custom_base_url: str = "",
    ) -> AutoProvider:
        runners: list[ChatProvider] = []

        # 1. Se foi especificado um provedor com chave ou customizado
        if custom_provider and custom_provider not in ("auto", "none"):
            if custom_provider == "openai" and api_key:
                runners.append(OpenAIProvider(api_key=api_key, model=custom_model, base_url=custom_base_url or "https://api.openai.com/v1"))
            elif custom_provider == "anthropic" and api_key:
                runners.append(AnthropicProvider(api_key=api_key, model=custom_model, base_url=custom_base_url or "https://api.anthropic.com/v1"))
            elif custom_provider == "gemini" and api_key:
                runners.append(GeminiProvider(api_key=api_key, model=custom_model, base_url=custom_base_url or "https://generativelanguage.googleapis.com/v1beta/openai"))

        # 2. GitHub Models (o corredor confiável com function calling nativo, se houver GITHUB_TOKEN)
        if github_token:
            runners.append(GitHubModelsProvider(github_token=github_token))

        # 3. Os 6 corredores gratuitos anônimos
        runners.extend([
            LLM7Provider(),
            ZenProvider(),
            KiloProvider(),
            OVHProvider(),
            PollinationsProvider(),
            BlackboxProvider(),
        ])

        return cls(providers=runners)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.providers:
            raise RuntimeError("Nenhum corredor LLM configurado na corrida.")

        tasks: list[asyncio.Task[tuple[str, LLMResponse]]] = []

        async def _run_candidate(provider: ChatProvider) -> tuple[str, LLMResponse]:
            resp = await provider.chat(
                messages=messages,
                tools=tools,
                timeout=timeout,
                max_tokens=max_tokens,
            )
            return provider.name, resp

        for p in self.providers:
            tasks.append(asyncio.create_task(_run_candidate(p)))

        errors: list[str] = []
        winner_name: str | None = None
        winner_response: LLMResponse | None = None

        try:
            for fut in asyncio.as_completed(tasks):
                try:
                    p_name, resp = await fut
                    if resp and (resp.content or resp.has_tool_calls):
                        winner_name = p_name
                        winner_response = resp
                        break
                except Exception as exc:
                    errors.append(str(exc))
                    continue

        finally:
            # Cancela imediatamente todos os corredores que ainda estão processando
            for t in tasks:
                if not t.done():
                    t.cancel()
            # Aguardar cancelamento sem propagar exceções
            await asyncio.gather(*tasks, return_exceptions=True)

        if winner_response is not None:
            logger.info("Corrida de LLMs vencida por: %s", winner_name)
            return winner_response

        err_summary = "; ".join(errors[:5])
        raise RuntimeError(
            f"Todos os {len(self.providers)} provedores de LLM falharam nesta rodada. Erros: {err_summary}"
        )

    async def close(self) -> None:
        for p in self.providers:
            try:
                await p.close()
            except Exception:
                pass
