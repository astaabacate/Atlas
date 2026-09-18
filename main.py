"""
Ponto de entrada do bot Farol.
Fluxo: Validação de Configuração → Healthcheck → Inicialização do Bot.
Exit code 2 para erros de configuração ou autenticação (sem traceback).
"""

from __future__ import annotations

import logging
import sys

from apis.base import ApiRegistry
from brain.agent import Agent
from brain.memory import ChannelMemory
from config import Config, ConfigError
from core.bot import FarolBot
from core.health import start_health_server
from llm.auto import AutoProvider


def main() -> None:
    # 1. Carregar e validar configuração
    try:
        config = Config.from_env()
    except ConfigError as exc:
        sys.stderr.write(f"\n❌ Erro de configuração: {exc}\n\n")
        sys.exit(2)
    except Exception as exc:
        sys.stderr.write(f"\n❌ Erro fatal de inicialização: {exc}\n\n")
        sys.exit(2)

    # 2. Configurar logging
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("farol.main")
    logger.info("Iniciando farol com provedor LLM: %s", config.llm_provider)

    # 3. Iniciar servidor de healthcheck opcional
    if config.health_port:
        start_health_server(config.health_port)

    # 4. Inicializar subsistemas
    api_registry = ApiRegistry(
        disabled_apis=config.disabled_apis,
        default_timeout=config.api_timeout,
    )

    try:
        llm_provider = AutoProvider.create_default(
            api_key=config.llm_api_key,
            custom_provider=config.llm_provider,
            custom_model=config.llm_model,
            custom_base_url=config.llm_base_url,
            custom_models=config.llm_models,
            disable_free=config.disable_free_llms,
        )
    except ValueError as exc:
        sys.stderr.write(f"\n❌ Erro de configuração de LLM: {exc}\n\n")
        sys.exit(2)

    logger.info("Corredores de LLM na corrida: %s", llm_provider.describe())

    memory = ChannelMemory(max_turns=config.history_len)

    agent = Agent(
        llm_provider=llm_provider,
        memory=memory,
        max_tool_rounds=config.max_tool_rounds,
        llm_timeout=config.llm_timeout,
        api_registry=api_registry,
        confirm_destructive=config.confirm_destructive,
        direct_tool_reply=config.direct_tool_reply,
        nudge_promise=config.nudge_promise,
    )

    bot = FarolBot(config=config, agent=agent)

    # 5. Executar o bot com tratamento amigável de erros do Discord
    import discord

    try:
        bot.run(config.discord_token, log_handler=None)
    except discord.LoginFailure as exc:
        sys.stderr.write(
            f"\n❌ Falha de autenticação no Discord: Token inválido ou revogado ({exc}).\n"
            "Acesse https://discord.com/developers/applications → Bot → Reset Token "
            "e cadastre o novo token na variável DISCORD_TOKEN.\n\n"
        )
        sys.exit(2)
    except discord.PrivilegedIntentsRequired as exc:
        var = "MEMBERS_INTENT" if config.members_intent else "MESSAGE_CONTENT_INTENT"
        sys.stderr.write(
            f"\n❌ Erro de Intents Privilegiadas ({exc}):\n"
            f"A variável '{var}' está ativada, mas a intent correspondente não foi habilitada no portal.\n"
            "Habilite em: https://discord.com/developers/applications → Bot → Privileged Gateway Intents,\n"
            f"ou desative a variável '{var}' no seu ambiente.\n\n"
        )
        sys.exit(2)
    except KeyboardInterrupt:
        logger.info("Bot encerrado pelo usuário via KeyboardInterrupt.")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Erro crítico no runtime do bot: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
