"""Entrypoint del worker. Se corre como `python -m purgatory_sync.main`
(ver railway.toml) — no expone ningún puerto, es un proceso de fondo.
"""
from __future__ import annotations

import asyncio
import logging

import discord

from . import db, events
from .config import load_config
from .reconcile import build_reconcile_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("purgatory_sync")


def build_intents() -> discord.Intents:
    """El mínimo necesario — ver el análisis en el README antes de tocar esto."""
    intents = discord.Intents.none()
    intents.guilds = True   # base: sin esto no llega ni GUILD_CREATE
    intents.members = True  # privilegiado — hay que activarlo en el Developer Portal
    intents.bans = True     # GUILD_MODERATION: ban add/remove
    return intents


class SyncClient(discord.Client):
    def __init__(self, *, guild_id: int, pool: db.asyncpg.Pool, reconcile_interval_hours: float, **kwargs):
        super().__init__(**kwargs)
        self.guild_id = guild_id
        self.pool = pool
        self._reconcile_loop = build_reconcile_loop(self, pool, guild_id, reconcile_interval_hours)

    async def on_ready(self) -> None:
        guild = self.get_guild(self.guild_id)
        if guild is None:
            log.error(
                "No veo el guild %s — ¿el bot está invitado ahí? Nada va a sincronizar hasta resolver esto.",
                self.guild_id,
            )
            return

        log.info("conectado como %s — guild: %s (~%s miembros)", self.user, guild.name, guild.member_count)

        try:
            await self.change_presence(activity=discord.CustomActivity(name="sincronizando 4LMAs"))
        except discord.HTTPException:
            pass  # cosmético — si falla no es motivo para nada más

        if not self._reconcile_loop.is_running():
            self._reconcile_loop.start()  # corre una vez ya mismo y después cada N horas

    def _is_our_guild(self, guild_id: int) -> bool:
        if guild_id == self.guild_id:
            return True
        log.warning("evento de un guild distinto al configurado (%s) — se ignora", guild_id)
        return False

    async def on_member_join(self, member: discord.Member) -> None:
        if self._is_our_guild(member.guild.id):
            await events.handle_member_join(self.pool, member)

    async def on_member_remove(self, member: discord.Member) -> None:
        if self._is_our_guild(member.guild.id):
            await events.handle_member_remove(self.pool, member)

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if self._is_our_guild(after.guild.id):
            await events.handle_member_update(self.pool, before, after)

    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        if self._is_our_guild(guild.id):
            await events.handle_member_ban(self.pool, guild, user)

    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        if self._is_our_guild(guild.id):
            await events.handle_member_unban(self.pool, guild, user)


async def main() -> None:
    config = load_config()
    pool = await db.create_pool(config.database_url)
    client = SyncClient(
        guild_id=config.guild_id,
        pool=pool,
        reconcile_interval_hours=config.reconcile_interval_hours,
        intents=build_intents(),
        chunk_guilds_at_startup=False,  # la reconciliación propia (REST, paginada) reemplaza esto
        max_messages=None,  # no leemos mensajes — no tiene sentido cachearlos
    )
    try:
        await client.start(config.discord_token)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
