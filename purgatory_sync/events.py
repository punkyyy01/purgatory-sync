"""Handlers del Gateway — cada uno hace la escritura puntual mínima para
ese evento. La verdad completa y definitiva la vuelve a escribir la
reconciliación (reconcile.py); acá el objetivo es baja latencia, no
ser la única fuente de corrección.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg
import discord

from . import db
from .models import member_snapshot

log = logging.getLogger("purgatory_sync.events")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def handle_member_join(pool: asyncpg.Pool, member: discord.Member) -> None:
    await db.upsert_present(pool, member_snapshot(member))
    await db.touch_sync_meta(pool, last_event_at=_now())
    log.info("join: %s (%s)", member, member.id)


async def handle_member_remove(pool: asyncpg.Pool, member: discord.Member) -> None:
    await db.mark_removed(pool, member.id, member.name)
    await db.touch_sync_meta(pool, last_event_at=_now())
    log.info("remove: %s (%s)", member, member.id)


async def handle_member_update(pool: asyncpg.Pool, before: discord.Member, after: discord.Member) -> None:
    # MEMBER_UPDATE se dispara por muchas razones que no nos importan
    # (pending, avatar decoration, etc.) — solo lo que puede afectar una
    # card justifica escribir.
    relevant_changed = (
        before.roles != after.roles
        or before.premium_since != after.premium_since
        or before.nick != after.nick
    )
    if not relevant_changed:
        return

    await db.upsert_present(pool, member_snapshot(after))
    await db.touch_sync_meta(pool, last_event_at=_now())

    if before.premium_since != after.premium_since:
        log.info("boost change: %s: %s -> %s", after.id, before.premium_since, after.premium_since)
    if before.roles != after.roles:
        log.info("roles change: %s", after.id)


async def handle_member_ban(pool: asyncpg.Pool, guild: discord.Guild, user: discord.User) -> None:
    await db.mark_banned(pool, user.id, user.name)
    await db.touch_sync_meta(pool, last_event_at=_now())
    log.info("ban: %s (%s)", user, user.id)


async def handle_member_unban(pool: asyncpg.Pool, guild: discord.Guild, user: discord.User) -> None:
    await db.mark_unbanned(pool, user.id)
    await db.touch_sync_meta(pool, last_event_at=_now())
    log.info("unban: %s (%s)", user, user.id)
