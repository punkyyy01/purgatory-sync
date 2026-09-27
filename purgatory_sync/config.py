"""Carga y valida la configuración desde variables de entorno.

Falla rápido y con un mensaje claro si falta algo — mejor eso que un
bot que arranca a medias y falla silenciosamente tres pasos después.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # no-op en Railway (las env vars ya están en el entorno); útil en local


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: int
    database_url: str
    reconcile_interval_hours: float


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno {name}. Revisá .env.example."
        )
    return value


def load_config() -> Config:
    guild_id_raw = _require("DISCORD_GUILD_ID")
    if not guild_id_raw.isdigit():
        raise RuntimeError("DISCORD_GUILD_ID debe ser un ID numérico (sin comillas).")

    interval_raw = os.environ.get("RECONCILE_INTERVAL_HOURS", "6").strip()
    try:
        interval = float(interval_raw)
    except ValueError:
        raise RuntimeError("RECONCILE_INTERVAL_HOURS debe ser un número.") from None
    if interval <= 0:
        raise RuntimeError("RECONCILE_INTERVAL_HOURS debe ser mayor a 0.")

    return Config(
        discord_token=_require("DISCORD_BOT_TOKEN"),
        guild_id=int(guild_id_raw),
        database_url=_require("DATABASE_URL"),
        reconcile_interval_hours=interval,
    )
