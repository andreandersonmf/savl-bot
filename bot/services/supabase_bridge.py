from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import aiohttp
import discord

import config


def is_enabled() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY)


def _headers(prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


async def _request(
    method: str,
    table: str,
    query: str = "",
    payload: Any | None = None,
    *,
    prefer: str | None = "return=representation",
) -> Any | None:
    if not is_enabled():
        return None

    url = f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/{table}{query}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                headers=_headers(prefer),
                data=json.dumps(payload) if payload is not None else None,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    print(f"[SUPABASE] {method} {table}{query} failed: {response.status} {text}")
                    return None
                if not text:
                    return None
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
    except Exception as exc:
        print(f"[SUPABASE] request error: {exc}")
        return None


async def get_active_season_id() -> str | None:
    rows = await _request(
        "GET",
        "seasons",
        "?select=id&is_active=eq.true&limit=1",
        prefer=None,
    )
    if isinstance(rows, list) and rows:
        return rows[0].get("id")
    return None


def _discord_username(member: discord.Member | discord.User) -> str:
    discriminator = getattr(member, "discriminator", "0")
    if discriminator and discriminator != "0":
        return f"{member.name}#{discriminator}"
    return member.name


async def upsert_profile_from_member(
    member: discord.Member | discord.User,
    *,
    roblox_username: str | None = None,
    roblox_user_id: int | str | None = None,
) -> dict[str, Any] | None:
    if not is_enabled():
        return None

    avatar_url = None
    try:
        avatar_url = str(member.display_avatar.url)
    except Exception:
        avatar_url = None

    payload = {
        "discord_id": str(member.id),
        "discord_username": _discord_username(member),
        "discord_global_name": getattr(member, "global_name", None) or getattr(member, "display_name", None),
        "avatar_url": avatar_url,
    }

    if roblox_username:
        payload["roblox_username"] = roblox_username
    if roblox_user_id:
        payload["roblox_user_id"] = str(roblox_user_id)

    rows = await _request(
        "POST",
        "profiles",
        "?on_conflict=discord_id",
        payload,
        prefer="resolution=merge-duplicates,return=representation",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


async def get_site_team_by_bot_team(team_row: Any) -> dict[str, Any] | None:
    if not is_enabled() or not team_row:
        return None

    role_id = str(team_row["team_role_id"])
    rows = await _request(
        "GET",
        "teams",
        f"?select=*&discord_role_id=eq.{quote(role_id)}&limit=1",
        prefer=None,
    )
    if isinstance(rows, list) and rows:
        return rows[0]

    # Fallback: exact match by visible team/element name. The recommended mapping is still discord_role_id.
    team_name = str(team_row["team_name"])
    rows = await _request(
        "GET",
        "teams",
        f"?select=*&country=eq.{quote(team_name)}&limit=1",
        prefer=None,
    )
    if isinstance(rows, list) and rows:
        return rows[0]

    return None


async def create_team_transaction(
    *,
    external_id: int | str,
    team_row: Any,
    requester: discord.Member | discord.User,
    player: discord.Member | discord.User,
    requested_role_type: str,
    roblox_username: str | None,
    roblox_user_id: int | str | None,
    channel_id: int | None,
    message_id: int | None = None,
) -> dict[str, Any] | None:
    if not is_enabled():
        return None

    season_id = await get_active_season_id()
    site_team = await get_site_team_by_bot_team(team_row)
    requested_role = "Vice Captain" if requested_role_type == "vice_captain" else "Player"

    await upsert_profile_from_member(requester)
    player_profile = await upsert_profile_from_member(
        player,
        roblox_username=roblox_username,
        roblox_user_id=roblox_user_id,
    )

    payload = {
        "season_id": season_id,
        "team_id": site_team.get("id") if site_team else None,
        "team_name": team_row["team_name"],
        "team_discord_role_id": str(team_row["team_role_id"]),
        "transaction_type": "add_player",
        "requested_role": requested_role,
        "status": "pending",
        "source": "discord",
        "external_source": "discord_bot",
        "external_id": str(external_id),
        "requester_discord_id": str(requester.id),
        "requester_discord_username": _discord_username(requester),
        "player_profile_id": player_profile.get("id") if player_profile else None,
        "player_discord_id": str(player.id),
        "player_discord_username": _discord_username(player),
        "roblox_username": roblox_username,
        "roblox_user_id": str(roblox_user_id) if roblox_user_id else None,
        "discord_channel_id": str(channel_id) if channel_id else None,
        "discord_message_id": str(message_id) if message_id else None,
    }

    rows = await _request(
        "POST",
        "team_transactions",
        "?on_conflict=external_source,external_id",
        payload,
        prefer="resolution=merge-duplicates,return=representation",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


async def update_team_transaction(
    *,
    external_id: int | str,
    status: str | None = None,
    handled_by: discord.Member | discord.User | None = None,
    reason: str | None = None,
    message_id: int | None = None,
) -> None:
    if not is_enabled():
        return

    payload: dict[str, Any] = {}
    if status:
        payload["status"] = status
    if handled_by:
        payload["handled_by_discord_id"] = str(handled_by.id)
        payload["handled_by_discord_username"] = _discord_username(handled_by)
        payload["handled_at"] = "now()"
        await upsert_profile_from_member(handled_by)
    if reason is not None:
        payload["reason"] = reason
    if message_id:
        payload["discord_message_id"] = str(message_id)

    if not payload:
        return

    # PostgREST cannot accept now() as a function through JSON, so replace with ISO-less server-side field omitted.
    if payload.get("handled_at") == "now()":
        payload.pop("handled_at", None)

    await _request(
        "PATCH",
        "team_transactions",
        f"?external_source=eq.discord_bot&external_id=eq.{quote(str(external_id))}",
        payload,
        prefer="return=minimal",
    )


async def mirror_roster_add(
    *,
    team_row: Any,
    player: discord.Member | discord.User,
    role_type: str,
    added_by: discord.Member | discord.User | None = None,
    roblox_username: str | None = None,
    roblox_user_id: int | str | None = None,
) -> None:
    if not is_enabled():
        return

    site_team = await get_site_team_by_bot_team(team_row)
    if not site_team:
        print(f"[SUPABASE] No site team mapping for Discord role {team_row['team_role_id']} / {team_row['team_name']}")
        return

    season_id = site_team.get("season_id") or await get_active_season_id()
    profile = await upsert_profile_from_member(
        player,
        roblox_username=roblox_username,
        roblox_user_id=roblox_user_id,
    )

    role = "Vice Captain" if role_type == "vice_captain" else "Player"
    payload = {
        "season_id": season_id,
        "team_id": site_team.get("id"),
        "profile_id": profile.get("id") if profile else None,
        "discord_id": str(player.id),
        "discord_username": _discord_username(player),
        "roblox_username": roblox_username or (profile or {}).get("roblox_username") or player.display_name,
        "roblox_user_id": str(roblox_user_id or (profile or {}).get("roblox_user_id") or player.id),
        "role": role,
    }

    # If an old row exists for this Discord account, update it; otherwise insert.
    existing = await _request(
        "GET",
        "team_players",
        f"?select=id&discord_id=eq.{quote(str(player.id))}&limit=1",
        prefer=None,
    )
    if isinstance(existing, list) and existing:
        await _request(
            "PATCH",
            "team_players",
            f"?id=eq.{existing[0]['id']}",
            payload,
            prefer="return=minimal",
        )
    else:
        await _request("POST", "team_players", "", payload, prefer="return=minimal")


async def mirror_roster_remove(*, team_row: Any, player: discord.Member | discord.User) -> None:
    if not is_enabled():
        return

    site_team = await get_site_team_by_bot_team(team_row)
    if not site_team:
        return

    await _request(
        "DELETE",
        "team_players",
        f"?team_id=eq.{site_team.get('id')}&discord_id=eq.{quote(str(player.id))}",
        prefer="return=minimal",
    )
