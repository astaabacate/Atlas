"""
Módulo de provedores LLM.
"""

from llm.auto import AutoProvider
from llm.base import ChatProvider, LLMResponse, ProviderError, ToolCall
from llm.free_providers import (
    FREE_PROVIDERS,
    KNOWN_GATEWAYS,
    OpenAICompatibleHttpProvider,
    build_free_runners,
    build_gateway_provider,
    descrever_pool,
    relatorio_do_pool,
    secrets_faltando,
    tabela_do_pool,
)
from llm.key_providers import AnthropicProvider, GeminiProvider, OpenAIProvider

__all__ = [
    "ChatProvider",
    "LLMResponse",
    "ProviderError",
    "ToolCall",
    "AutoProvider",
    "OpenAICompatibleHttpProvider",
    "FREE_PROVIDERS",
    "build_free_runners",
    "relatorio_do_pool",
    "secrets_faltando",
    "tabela_do_pool",
    "descrever_pool",
    "build_gateway_provider",
    "KNOWN_GATEWAYS",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
]
