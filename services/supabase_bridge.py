from __future__ import annotations

import json
from datetime import datetime, timezone
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
    # Discord's new username system often exposes discriminator "0".
    # SAVL stores the clean username, never "name#0".
    discriminator = str(getattr(member, "discriminator", "0") or "0")
    name = str(getattr(member, "name", "") or "").replace("#0", "").lstrip("@")
    if discriminator and discriminator != "0":
        return f"{name}#{discriminator}"
    return name


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

    try:
        site_team_id = team_row["site_team_id"]
    except Exception:
        site_team_id = None

    if site_team_id:
        rows = await _request(
            "GET",
            "teams",
            f"?select=*&id=eq.{quote(str(site_team_id))}&limit=1",
            prefer=None,
        )
        if isinstance(rows, list) and rows:
            return rows[0]

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


async def fetch_site_team_by_role(role_id: int | str) -> dict[str, Any] | None:
    if not is_enabled() or not role_id:
        return None

    rows = await _request(
        "GET",
        "teams",
        f"?select=*&discord_role_id=eq.{quote(str(role_id))}&limit=1",
        prefer=None,
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


async def fetch_site_team_by_id(site_team_id: int | str | None) -> dict[str, Any] | None:
    if not is_enabled() or not site_team_id:
        return None

    rows = await _request(
        "GET",
        "teams",
        f"?select=*&id=eq.{quote(str(site_team_id))}&limit=1",
        prefer=None,
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


async def fetch_site_team_by_captain(discord_id: int | str) -> dict[str, Any] | None:
    if not is_enabled() or not discord_id:
        return None

    rows = await _request(
        "GET",
        "teams",
        f"?select=*&captain_discord_id=eq.{quote(str(discord_id))}&limit=1",
        prefer=None,
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


async def fetch_site_team_for_manager(discord_id: int | str) -> dict[str, Any] | None:
    """Return the site team managed by this Discord user as captain or vice captain."""
    if not is_enabled() or not discord_id:
        return None

    captain_team = await fetch_site_team_by_captain(discord_id)
    if captain_team:
        return captain_team

    player_rows = await _request(
        "GET",
        "team_players",
        f"?select=team_id&discord_id=eq.{quote(str(discord_id))}&role=eq.Vice%20Captain&limit=1",
        prefer=None,
    )
    if isinstance(player_rows, list) and player_rows:
        return await fetch_site_team_by_id(player_rows[0].get("team_id"))

    return None


async def fetch_site_team_for_player(discord_id: int | str) -> dict[str, Any] | None:
    if not is_enabled() or not discord_id:
        return None

    captain_team = await fetch_site_team_by_captain(discord_id)
    if captain_team:
        return captain_team

    player_rows = await _request(
        "GET",
        "team_players",
        f"?select=team_id&discord_id=eq.{quote(str(discord_id))}&limit=1",
        prefer=None,
    )
    if isinstance(player_rows, list) and player_rows:
        return await fetch_site_team_by_id(player_rows[0].get("team_id"))

    return None


async def fetch_site_roster(site_team_id: int | str | None) -> list[dict[str, Any]]:
    if not is_enabled() or not site_team_id:
        return []

    rows = await _request(
        "GET",
        "team_players",
        f"?select=*&team_id=eq.{quote(str(site_team_id))}",
        prefer=None,
    )
    if isinstance(rows, list):
        return rows
    return []


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

    site_team = await get_site_team_by_bot_team(team_row)
    season_id = (site_team or {}).get("season_id") or await get_active_season_id()
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

    existing = await _request(
        "GET",
        "team_transactions",
        f"?select=id&external_source=eq.discord_bot&external_id=eq.{quote(str(external_id))}&limit=1",
        prefer=None,
    )

    if isinstance(existing, list) and existing:
        rows = await _request(
            "PATCH",
            "team_transactions",
            f"?id=eq.{quote(str(existing[0]['id']))}",
            payload,
            prefer="return=representation",
        )
    else:
        rows = await _request(
            "POST",
            "team_transactions",
            "",
            payload,
            prefer="return=representation",
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
        payload["handled_at"] = _now_iso()
        await upsert_profile_from_member(handled_by)
    if reason is not None:
        payload["reason"] = reason
    if message_id:
        payload["discord_message_id"] = str(message_id)

    if not payload:
        return

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _team_code_from_name(team_name: str) -> str:
    cleaned = "".join(char for char in str(team_name).upper() if char.isalnum())
    return (cleaned[:8] or "TEAM")


async def mirror_team_create(*, team_row: Any, captain: discord.Member | discord.User) -> dict[str, Any] | None:
    """Create or update the matching site team when /team create links a Discord role."""
    if not is_enabled() or not team_row:
        return None

    season_id = await get_active_season_id()
    captain_profile = await upsert_profile_from_member(captain)
    existing = await get_site_team_by_bot_team(team_row)

    team_name = str(team_row["team_name"])
    payload = {
        "country": team_name,
        "code": existing.get("code") if existing else _team_code_from_name(team_name),
        "captain_name": (captain_profile or {}).get("roblox_username") or getattr(captain, "display_name", team_name),
        "captain_discord": _discord_username(captain),
        "captain_discord_id": str(captain.id),
        "captain_roblox_id": str((captain_profile or {}).get("roblox_user_id") or captain.id),
        "discord_role_id": str(team_row["team_role_id"]),
        "approved": True,
        "approved_at": _now_iso(),
    }
    if season_id:
        payload["season_id"] = season_id

    if existing:
        rows = await _request(
            "PATCH",
            "teams",
            f"?id=eq.{quote(str(existing['id']))}",
            payload,
            prefer="return=representation",
        )
    else:
        rows = await _request("POST", "teams", "", payload, prefer="return=representation")

    if isinstance(rows, list) and rows:
        return rows[0]
    return existing


async def mirror_team_delete(*, team_row: Any) -> None:
    """Remove the linked site team when /team delete is used in Discord."""
    if not is_enabled() or not team_row:
        return

    site_team = await get_site_team_by_bot_team(team_row)
    if not site_team:
        return

    site_team_id = site_team.get("id")
    await _request("DELETE", "team_players", f"?team_id=eq.{quote(str(site_team_id))}", prefer="return=minimal")
    await _request("DELETE", "team_transactions", f"?team_id=eq.{quote(str(site_team_id))}", prefer="return=minimal")
    await _request("DELETE", "teams", f"?id=eq.{quote(str(site_team_id))}", prefer="return=minimal")


async def record_roster_transaction(
    *,
    team_row: Any,
    transaction_type: str,
    player: discord.Member | discord.User,
    actor: discord.Member | discord.User | None = None,
    role_type: str | None = None,
    roblox_username: str | None = None,
    roblox_user_id: int | str | None = None,
    status: str = "accepted",
    reason: str | None = None,
) -> dict[str, Any] | None:
    """Create a site-visible transaction log for immediate Discord roster actions.

    /team add already creates a pending transaction and then updates it on Accept/Deny.
    This helper is for direct actions such as /team remove, /team leave,
    /team staffadd and /team staffremove so Profile stays complete.
    """
    if not is_enabled():
        return None

    site_team = await get_site_team_by_bot_team(team_row)
    season_id = (site_team or {}).get("season_id") or await get_active_season_id()
    requested_role = None
    if role_type:
        requested_role = "Vice Captain" if role_type == "vice_captain" else "Player"

    if actor:
        await upsert_profile_from_member(actor)

    player_profile = await upsert_profile_from_member(
        player,
        roblox_username=roblox_username,
        roblox_user_id=roblox_user_id,
    )

    external_id = f"log_{transaction_type}_{getattr(player, 'id', 'unknown')}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    actor_id = str(actor.id) if actor else str(player.id)
    actor_username = _discord_username(actor) if actor else _discord_username(player)

    payload = {
        "season_id": season_id,
        "team_id": (site_team or {}).get("id"),
        "team_name": str(team_row["team_name"]),
        "team_discord_role_id": str(team_row["team_role_id"]),
        "transaction_type": transaction_type,
        "requested_role": requested_role,
        "status": status,
        "source": "discord",
        "external_source": "discord_bot",
        "external_id": external_id,
        "requester_discord_id": actor_id,
        "requester_discord_username": actor_username,
        "handled_by_discord_id": actor_id,
        "handled_by_discord_username": actor_username,
        "handled_at": _now_iso(),
        "player_profile_id": player_profile.get("id") if player_profile else None,
        "player_discord_id": str(player.id),
        "player_discord_username": _discord_username(player),
        "roblox_username": roblox_username or (player_profile or {}).get("roblox_username"),
        "roblox_user_id": str(roblox_user_id or (player_profile or {}).get("roblox_user_id") or "") or None,
        "reason": reason,
    }

    rows = await _request(
        "POST",
        "team_transactions",
        "",
        payload,
        prefer="return=representation",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


async def clear_team_transaction(*, external_id: int | str | None = None, player_discord_id: int | str | None = None) -> None:
    """Delete a pending site transfer when /team clear removes it in Discord."""
    if not is_enabled():
        return

    if external_id is not None:
        await _request(
            "DELETE",
            "team_transactions",
            f"?external_source=eq.discord_bot&external_id=eq.{quote(str(external_id))}&status=eq.pending",
            prefer="return=minimal",
        )

    if player_discord_id is not None:
        await _request(
            "DELETE",
            "team_transactions",
            f"?player_discord_id=eq.{quote(str(player_discord_id))}&status=eq.pending",
            prefer="return=minimal",
        )
