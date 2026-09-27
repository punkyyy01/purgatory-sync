"""Traduce objetos de discord.py a la forma exacta que espera db.py.

Un solo lugar que sabe leer un Member de discord.py — así ni events.py
ni reconcile.py repiten esta lógica cada uno a su manera.
"""
from __future__ import annotations

import discord


def member_snapshot(member: discord.Member) -> dict:
    role_ids = [r.id for r in member.roles if not r.is_default()]

    raw_extra = {
        "nick": member.nick,
        "pending": getattr(member, "pending", None),
        "communication_disabled_until": _iso(getattr(member, "timed_out_until", None)),
    }

    return {
        "discord_id": member.id,
        "username": member.name,
        "global_name": member.global_name,
        "avatar_url": str(member.display_avatar.url),
        "joined_at": member.joined_at,
        "roles": role_ids,
        "is_booster": member.premium_since is not None,
        "boosting_since": member.premium_since,
        "raw_member": raw_extra,
    }


def _iso(value):
    return value.isoformat() if value is not None else None
