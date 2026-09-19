"""Liga o bot: `python -m atlas2.run`."""

from __future__ import annotations

import logging
import sys

import discord

from atlas2.config import Config
from atlas2.core import Atlas


def configurar_log() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("discord").setLevel(logging.WARNING)


def main() -> int:
    configurar_log()
    log = logging.getLogger("atlas2.run")
    cfg = Config.do_ambiente()

    if not cfg.token:
        print("\n❌ Falta o DISCORD_TOKEN.\n"
              "   Cadastre em Settings → Secrets and variables → Actions → New repository secret.\n")
        return 2
    if not cfg.tem_llm:
        log.warning("Sem OMNIROUTE_URL/OMNIROUTE_KEY: os comandos reconhecidos funcionam, "
                    "os pedidos livres não.")

    bot = Atlas(cfg)
    try:
        bot.run(cfg.token, log_handler=None)
    except discord.LoginFailure as exc:
        print(f"\n❌ Token recusado pelo Discord ({exc}). Gere outro e atualize o segredo.\n")
        return 2
    except discord.PrivilegedIntentsRequired:
        print("\n❌ O portal do Discord precisa das intents: ative 'Message Content Intent' "
              "em https://discord.com/developers/applications → Bot.\n")
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
