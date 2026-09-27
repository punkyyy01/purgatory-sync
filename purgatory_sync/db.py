"""Acceso a Postgres — todas las queries del contrato viven acá adentro,
en un solo lugar, para que sql/0001_init.sql y este archivo nunca se
desincronicen entre sí.

Conexión directa (puerto 5432 de Supabase, no el pooler 6543): asyncpg
usa prepared statements por default, que no conviven bien con PgBouncer
en modo transacción. Un solo proceso siempre vivo con un pool chico no
necesita ese pooler para nada.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

import asyncpg

_UPSERT_PRESENT = """
insert into discord_members (
  discord_id, username, global_name, avatar_url, joined_at,
  is_member, left_at, roles, is_booster, boosting_since, raw_member, synced_at
) values ($1, $2, $3, $4, $5, true, null, $6, $7, $8, $9, now())
on conflict (discord_id) do update set
  username       = excluded.username,
  global_name    = excluded.global_name,
  avatar_url     = excluded.avatar_url,
  joined_at      = coalesce(discord_members.joined_at, excluded.joined_at),
  is_member      = true,
  left_at        = null,
  roles          = excluded.roles,
  is_booster     = excluded.is_booster,
  boosting_since = excluded.boosting_since,
  raw_member     = excluded.raw_member,
  synced_at      = now();
"""

_MARK_REMOVED = """
insert into discord_members (discord_id, username, is_member, left_at, synced_at)
values ($1, $2, false, $3, now())
on conflict (discord_id) do update set
  is_member = false,
  left_at   = coalesce(discord_members.left_at, excluded.left_at),
  synced_at = now();
"""

_MARK_BANNED = """
insert into discord_members (discord_id, username, is_member, left_at, is_banned, banned_at, synced_at)
values ($1, $2, false, $3, true, $3, now())
on conflict (discord_id) do update set
  is_member  = false,
  left_at    = coalesce(discord_members.left_at, excluded.left_at),
  is_banned  = true,
  banned_at  = coalesce(discord_members.banned_at, excluded.banned_at),
  synced_at  = now();
"""

_MARK_UNBANNED = """
update discord_members set
  is_banned   = false,
  unbanned_at = $2,
  synced_at   = now()
where discord_id = $1;
"""

# Anti-join: cualquiera marcado presente/baneado en la DB que la
# reconciliación NO vio en la lista fresca de Discord quedó desactualizado
# (se fue / lo desbanearon mientras el bot estaba caído).
_RECONCILE_MARK_LEFT = """
update discord_members set is_member = false, left_at = now(), synced_at = now()
where is_member = true and discord_id <> all($1::bigint[]);
"""

_RECONCILE_MARK_UNBANNED = """
update discord_members set is_banned = false, unbanned_at = now(), synced_at = now()
where is_banned = true and discord_id <> all($1::bigint[]);
"""

_TOUCH_SYNC_META = """
update sync_meta set
  last_event_at      = coalesce($1, last_event_at),
  last_reconciled_at = coalesce($2, last_reconciled_at),
  last_reconcile_ms  = coalesce($3, last_reconcile_ms),
  guild_member_count = coalesce($4, guild_member_count)
where id = true;
"""


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str)


async def create_pool(database_url: str) -> asyncpg.Pool:
    # min_size=1: no tiene sentido pagar el rato de conexiones ociosas en
    # un worker de bajo tráfico. max_size=3 alcanza de sobra: nunca hay
    # más que un puñado de eventos concurrentes en un server de este tamaño.
    return await asyncpg.create_pool(database_url, min_size=1, max_size=3)


async def upsert_present(pool: asyncpg.Pool, snapshot: dict) -> None:
    await pool.execute(
        _UPSERT_PRESENT,
        snapshot["discord_id"],
        snapshot["username"],
        snapshot.get("global_name"),
        snapshot.get("avatar_url"),
        snapshot.get("joined_at"),
        snapshot.get("roles", []),
        snapshot.get("is_booster", False),
        snapshot.get("boosting_since"),
        _json(snapshot.get("raw_member")),
    )


async def mark_removed(pool: asyncpg.Pool, discord_id: int, username: str, when: datetime | None = None) -> None:
    await pool.execute(_MARK_REMOVED, discord_id, username, when or datetime.now(timezone.utc))


async def mark_banned(pool: asyncpg.Pool, discord_id: int, username: str, when: datetime | None = None) -> None:
    await pool.execute(_MARK_BANNED, discord_id, username, when or datetime.now(timezone.utc))


async def mark_unbanned(pool: asyncpg.Pool, discord_id: int, when: datetime | None = None) -> None:
    await pool.execute(_MARK_UNBANNED, discord_id, when or datetime.now(timezone.utc))


async def reconcile_mark_left(pool: asyncpg.Pool, current_member_ids: Iterable[int]) -> None:
    await pool.execute(_RECONCILE_MARK_LEFT, list(current_member_ids))


async def reconcile_mark_unbanned(pool: asyncpg.Pool, current_ban_ids: Iterable[int]) -> None:
    await pool.execute(_RECONCILE_MARK_UNBANNED, list(current_ban_ids))


async def touch_sync_meta(
    pool: asyncpg.Pool,
    *,
    last_event_at: datetime | None = None,
    last_reconciled_at: datetime | None = None,
    last_reconcile_ms: int | None = None,
    guild_member_count: int | None = None,
) -> None:
    await pool.execute(
        _TOUCH_SYNC_META, last_event_at, last_reconciled_at, last_reconcile_ms, guild_member_count
    )
