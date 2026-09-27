"""Reconciliación completa: la red de seguridad para todo lo que el
Gateway se haya perdido mientras el bot estuvo desconectado.

Trae el estado actual y completo desde Discord (paginado) y lo escribe
como la verdad — sin importar qué decía la base antes. Corre una vez al
arrancar y después cada `reconcile_interval_hours`.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import asyncpg
import discord
from discord.ext import tasks

from . import db
from .models import member_snapshot

log = logging.getLogger("purgatory_sync.reconcile")


async def run_reconciliation(client: discord.Client, pool: asyncpg.Pool, guild_id: int) -> None:
    guild = client.get_guild(guild_id)
    if guild is None:
        log.warning("reconcile: guild %s no está en caché todavía, se salta esta vuelta", guild_id)
        return

    started = time.monotonic()
    member_ids: list[int] = []
    ban_ids: list[int] = []

    async for member in guild.fetch_members(limit=None):
        await db.upsert_present(pool, member_snapshot(member))
        member_ids.append(member.id)

    async for ban_entry in guild.bans(limit=None):
        await db.mark_banned(pool, ban_entry.user.id, ban_entry.user.name)
        ban_ids.append(ban_entry.user.id)

    # Todo lo que la DB tenía como presente/baneado y Discord ya no
    # confirma quedó desactualizado — se corrige acá.
    await db.reconcile_mark_left(pool, member_ids)
    await db.reconcile_mark_unbanned(pool, ban_ids)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    await db.touch_sync_meta(
        pool,
        last_reconciled_at=datetime.now(timezone.utc),
        last_reconcile_ms=elapsed_ms,
        guild_member_count=len(member_ids),
    )
    log.info(
        "reconcile: %d miembros, %d baneos, %d ms", len(member_ids), len(ban_ids), elapsed_ms
    )


def build_reconcile_loop(
    client: discord.Client, pool: asyncpg.Pool, guild_id: int, interval_hours: float
) -> tasks.Loop:
    @tasks.loop(hours=interval_hours)
    async def _loop() -> None:
        try:
            await run_reconciliation(client, pool, guild_id)
        except Exception:  # noqa: BLE001 — un fallo acá no puede tirar abajo el bot
            log.exception("reconcile: falló esta vuelta, se reintenta en la próxima")

    @_loop.before_loop
    async def _before() -> None:
        await client.wait_until_ready()

    return _loop
