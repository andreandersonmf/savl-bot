from __future__ import annotations

from datetime import datetime
import random

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import execute, fetchone, fetchall


# =========================
# CONFIG / FALLBACKS
# =========================

MATCH_ORGANIZER_ROLE_ID = getattr(config, "MATCH_ORGANIZER_ROLE_ID", 1486904493080711218)
MATCHMAKING_CATEGORY_ID = getattr(config, "MATCHMAKING_CATEGORY_ID", 1484645219059372163)
MM_RESULTS_CHANNEL_ID = getattr(config, "MM_RESULTS_CHANNEL_ID", 1486900210436276294)

MAX_SETTERS = 4
MAX_SPIKERS = 8

WIN_ELO = 25
WIN_MVP_BONUS = 10
LOSS_ELO = -20
LOSS_MVP_ELO = -10


# =========================
# BASIC HELPERS
# =========================

def now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator


def has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def can_manage_season(member: discord.Member) -> bool:
    if is_admin(member):
        return True

    staff_ids = getattr(config, "STAFF_APPROVER_ROLE_IDS", [])
    member_role_ids = {role.id for role in member.roles}
    return any(role_id in member_role_ids for role_id in staff_ids)


def can_manage_matchmaking(member: discord.Member) -> bool:
    return is_admin(member) or has_role(member, MATCH_ORGANIZER_ROLE_ID)


def team_side_label(side: str) -> str:
    return "Team A" if side == "A" else "Team B"


def role_short(role_pref: str) -> str:
    return "S" if role_pref == "setter" else "WS"


def get_active_season():
    return fetchone("""
        SELECT * FROM mm_seasons
        WHERE is_active = 1
        ORDER BY number DESC
        LIMIT 1
    """)


def ensure_mm_player(user_id: int):
    existing = fetchone("SELECT * FROM mm_players WHERE user_id = ?", (user_id,))
    if not existing:
        execute("""
            INSERT INTO mm_players (
                user_id, elo, matches, wins, losses,
                win_mvp, loss_mvp, elo_gained_total, elo_lost_total, created_at
            )
            VALUES (?, 1000, 0, 0, 0, 0, 0, 0, 0, ?)
        """, (user_id, now_str()))


def ensure_mm_season_player(season_number: int, user_id: int):
    existing = fetchone("""
        SELECT * FROM mm_season_players
        WHERE season_number = ? AND user_id = ?
    """, (season_number, user_id))

    if not existing:
        execute("""
            INSERT INTO mm_season_players (
                season_number, user_id, matches, wins, losses,
                win_mvp, loss_mvp, elo_gained, elo_lost, created_at
            )
            VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, ?)
        """, (season_number, user_id, now_str()))


def get_match_by_number(match_number: int):
    return fetchone("""
        SELECT * FROM mm_matches
        WHERE match_number = ?
    """, (match_number,))


def get_match_players(match_number: int):
    return fetchall("""
        SELECT * FROM mm_match_players
        WHERE match_number = ?
        ORDER BY captain DESC, pick_order ASC, id ASC
    """, (match_number,))


def get_team_players(match_number: int, side: str):
    return fetchall("""
        SELECT * FROM mm_match_players
        WHERE match_number = ? AND team_side = ?
        ORDER BY captain DESC, pick_order ASC, id ASC
    """, (match_number, side))


def get_available_players(match_number: int):
    return fetchall("""
        SELECT * FROM mm_match_players
        WHERE match_number = ? AND team_side IS NULL
        ORDER BY
            CASE role_pref WHEN 'setter' THEN 0 ELSE 1 END,
            id ASC
    """, (match_number,))


def count_team_role(match_number: int, side: str, role_pref: str) -> int:
    row = fetchone("""
        SELECT COUNT(*) AS total
        FROM mm_match_players
        WHERE match_number = ? AND team_side = ? AND role_pref = ?
    """, (match_number, side, role_pref))
    return row["total"] if row else 0


def get_captain_side(match_number: int, user_id: int):
    row = fetchone("""
        SELECT team_side FROM mm_match_players
        WHERE match_number = ? AND user_id = ? AND captain = 1
    """, (match_number, user_id))
    return row["team_side"] if row else None


def get_pick_count(match_number: int) -> int:
    row = fetchone("""
        SELECT COUNT(*) AS total
        FROM mm_match_players
        WHERE match_number = ? AND team_side IS NOT NULL AND captain = 0
    """, (match_number,))
    return row["total"] if row else 0


def get_current_turn_side(match_row) -> str | None:
    available = get_available_players(match_row["match_number"])
    if not available:
        return None

    picks_done = get_pick_count(match_row["match_number"])
    first_side = "A" if match_row["first_picker_id"] == match_row["captain1_id"] else "B"
    second_side = "B" if first_side == "A" else "A"

    return first_side if picks_done % 2 == 0 else second_side


def is_user_busy(user_id: int) -> bool:
    row = fetchone("""
        SELECT mp.id
        FROM mm_match_players mp
        JOIN mm_matches m ON m.match_number = mp.match_number
        WHERE mp.user_id = ?
          AND m.status IN ('queue_open', 'captains_pending', 'draft', 'ready_to_start', 'in_progress')
        LIMIT 1
    """, (user_id,))
    return row is not None


def init_matchmaking_tables():
    execute("""
        CREATE TABLE IF NOT EXISTS mm_players (
            user_id INTEGER PRIMARY KEY,
            elo INTEGER NOT NULL DEFAULT 1000,
            matches INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            win_mvp INTEGER NOT NULL DEFAULT 0,
            loss_mvp INTEGER NOT NULL DEFAULT 0,
            elo_gained_total INTEGER NOT NULL DEFAULT 0,
            elo_lost_total INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )
    """)

    execute("""
        CREATE TABLE IF NOT EXISTS mm_seasons (
            number INTEGER PRIMARY KEY,
            is_active INTEGER NOT NULL DEFAULT 0,
            started_at TEXT,
            ended_at TEXT
        )
    """)

    execute("""
        CREATE TABLE IF NOT EXISTS mm_season_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_number INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            matches INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            win_mvp INTEGER NOT NULL DEFAULT 0,
            loss_mvp INTEGER NOT NULL DEFAULT 0,
            elo_gained INTEGER NOT NULL DEFAULT 0,
            elo_lost INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            UNIQUE(season_number, user_id)
        )
    """)

    execute("""
        CREATE TABLE IF NOT EXISTS mm_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_number INTEGER NOT NULL UNIQUE,
            season_number INTEGER,
            status TEXT NOT NULL,
            created_by_id INTEGER NOT NULL,
            queue_channel_id INTEGER,
            queue_message_id INTEGER,
            captain1_id INTEGER,
            captain2_id INTEGER,
            first_picker_id INTEGER,
            private_server_link TEXT,
            text_channel_id INTEGER,
            team_a_voice_id INTEGER,
            team_b_voice_id INTEGER,
            winner_side TEXT,
            loser_side TEXT,
            wmvp_id INTEGER,
            lmvp_id INTEGER,
            created_at TEXT,
            started_at TEXT,
            finished_at TEXT
        )
    """)

    execute("""
        CREATE TABLE IF NOT EXISTS mm_match_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_number INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role_pref TEXT NOT NULL,
            team_side TEXT,
            captain INTEGER NOT NULL DEFAULT 0,
            pick_order INTEGER,
            joined_at TEXT,
            UNIQUE(match_number, user_id)
        )
    """)


# =========================
# EMBED HELPERS
# =========================

def mention_or_name(guild: discord.Guild | None, user_id: int) -> str:
    if guild is None:
        return f"<@{user_id}>"
    member = guild.get_member(user_id)
    return member.mention if member else f"<@{user_id}>"


def build_queue_lines(guild: discord.Guild | None, match_number: int):
    rows = fetchall("""
        SELECT * FROM mm_match_players
        WHERE match_number = ?
        ORDER BY
            CASE role_pref WHEN 'setter' THEN 0 ELSE 1 END,
            id ASC
    """, (match_number,))

    setters = []
    spikers = []

    for row in rows:
        line = f"{mention_or_name(guild, row['user_id'])} `[{role_short(row['role_pref'])}]`"
        if row["role_pref"] == "setter":
            setters.append(line)
        else:
            spikers.append(line)

    return setters, spikers


def build_queue_embed(guild: discord.Guild | None, match_row):
    setters, spikers = build_queue_lines(guild, match_row["match_number"])

    embed = discord.Embed(
        title=f"SAVL Match Making Queue #{match_row['match_number']}",
        description=(
            f"**Setters ({len(setters)}/{MAX_SETTERS})**\n"
            f"{chr(10).join(setters) if setters else '—'}\n\n"
            f"**Spikers ({len(spikers)}/{MAX_SPIKERS})**\n"
            f"{chr(10).join(spikers) if spikers else '—'}"
        ),
        color=discord.Color.blurple()
    )

    season = get_active_season()
    embed.set_footer(text=f"SAVL Match Making • Season {season['number']}" if season else "SAVL Match Making")
    return embed


def build_captains_embed(guild: discord.Guild | None, match_row):
    all_players = fetchall("""
        SELECT * FROM mm_match_players
        WHERE match_number = ?
        ORDER BY
            CASE role_pref WHEN 'setter' THEN 0 ELSE 1 END,
            id ASC
    """, (match_row["match_number"],))

    lines = []
    for row in all_players:
        suffix = f" [{role_short(row['role_pref'])}]"
        if match_row["captain1_id"] == row["user_id"]:
            suffix += " • CAPTAIN 1"
        elif match_row["captain2_id"] == row["user_id"]:
            suffix += " • CAPTAIN 2"

        lines.append(f"{mention_or_name(guild, row['user_id'])}`{suffix}`")

    embed = discord.Embed(
        title=f"Queue #{match_row['match_number']} • Set Captains",
        description=(
            "The queue is now full.\n\n"
            "**Queued Players**\n"
            f"{chr(10).join(lines) if lines else '—'}\n\n"
            f"**Captain 1:** {mention_or_name(guild, match_row['captain1_id']) if match_row['captain1_id'] else 'Not selected'}\n"
            f"**Captain 2:** {mention_or_name(guild, match_row['captain2_id']) if match_row['captain2_id'] else 'Not selected'}"
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text="Only Match Organizer can choose captains")
    return embed


def build_team_lines(guild: discord.Guild | None, players, wmvp_id: int | None = None, lmvp_id: int | None = None):
    lines = []
    for row in players:
        tags = [role_short(row["role_pref"])]
        if row["captain"]:
            tags.append("CAP")
        if wmvp_id and row["user_id"] == wmvp_id:
            tags.append("WMVP")
        if lmvp_id and row["user_id"] == lmvp_id:
            tags.append("LMVP")

        lines.append(f"{mention_or_name(guild, row['user_id'])} `[{', '.join(tags)}]`")

    return chr(10).join(lines) if lines else "—"


def build_draft_embed(guild: discord.Guild | None, match_row):
    team_a = get_team_players(match_row["match_number"], "A")
    team_b = get_team_players(match_row["match_number"], "B")
    available = get_available_players(match_row["match_number"])
    current_turn_side = get_current_turn_side(match_row)

    available_lines = [
        f"{mention_or_name(guild, row['user_id'])} `[{role_short(row['role_pref'])}]`"
        for row in available
    ]

    if not current_turn_side:
        turn_text = "Draft complete"
    else:
        turn_text = f"{team_side_label(current_turn_side)} Captain"

    embed = discord.Embed(
        title=f"Queue #{match_row['match_number']} • Draft Phase",
        color=discord.Color.green()
    )
    embed.add_field(name="Team A", value=build_team_lines(guild, team_a), inline=False)
    embed.add_field(name="Team B", value=build_team_lines(guild, team_b), inline=False)
    embed.add_field(
        name=f"Available Players ({len(available)})",
        value=chr(10).join(available_lines) if available_lines else "—",
        inline=False
    )
    embed.add_field(name="Current Turn", value=turn_text, inline=False)

    first_picker = mention_or_name(guild, match_row["first_picker_id"]) if match_row["first_picker_id"] else "—"
    embed.set_footer(text=f"First pick: {first_picker}")
    return embed


def build_ready_embed(guild: discord.Guild | None, match_row):
    team_a = get_team_players(match_row["match_number"], "A")
    team_b = get_team_players(match_row["match_number"], "B")

    embed = discord.Embed(
        title=f"Queue #{match_row['match_number']} • Teams Ready",
        description="All picks are complete. Match Organizer can now start the match.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Team A", value=build_team_lines(guild, team_a), inline=False)
    embed.add_field(name="Team B", value=build_team_lines(guild, team_b), inline=False)
    return embed


def build_match_started_embed(guild: discord.Guild | None, match_row):
    team_a = get_team_players(match_row["match_number"], "A")
    team_b = get_team_players(match_row["match_number"], "B")

    embed = discord.Embed(
        title=f"Match In Progress • #{match_row['match_number']}",
        description=f"**Private Server Link**\n{match_row['private_server_link']}",
        color=discord.Color.dark_green()
    )
    embed.add_field(name="Team A", value=build_team_lines(guild, team_a), inline=False)
    embed.add_field(name="Team B", value=build_team_lines(guild, team_b), inline=False)
    embed.set_footer(text="SAVL Match Making")
    return embed


def build_result_embed(guild: discord.Guild | None, match_row):
    winners = get_team_players(match_row["match_number"], match_row["winner_side"])
    losers = get_team_players(match_row["match_number"], match_row["loser_side"])

    embed = discord.Embed(
        title=f"Match Result • #{match_row['match_number']}",
        color=discord.Color.purple()
    )
    embed.add_field(
        name=f"{team_side_label(match_row['winner_side'])} • Winner",
        value=build_team_lines(guild, winners, wmvp_id=match_row["wmvp_id"]),
        inline=False
    )
    embed.add_field(
        name=f"{team_side_label(match_row['loser_side'])} • Loser",
        value=build_team_lines(guild, losers, lmvp_id=match_row["lmvp_id"]),
        inline=False
    )
    embed.set_footer(text="SAVL Match Making Results")
    return embed


# =========================
# ELO / STATS UPDATE
# =========================

def apply_match_result_to_player(user_id: int, season_number: int | None, delta: int, is_win: bool, is_win_mvp: bool, is_loss_mvp: bool):
    ensure_mm_player(user_id)

    player = fetchone("SELECT * FROM mm_players WHERE user_id = ?", (user_id,))
    if not player:
        return

    new_elo = max(0, player["elo"] + delta)
    elo_gained = delta if delta > 0 else 0
    elo_lost = abs(delta) if delta < 0 else 0

    execute("""
        UPDATE mm_players
        SET elo = ?,
            matches = matches + 1,
            wins = wins + ?,
            losses = losses + ?,
            win_mvp = win_mvp + ?,
            loss_mvp = loss_mvp + ?,
            elo_gained_total = elo_gained_total + ?,
            elo_lost_total = elo_lost_total + ?
        WHERE user_id = ?
    """, (
        new_elo,
        1 if is_win else 0,
        0 if is_win else 1,
        1 if is_win_mvp else 0,
        1 if is_loss_mvp else 0,
        elo_gained,
        elo_lost,
        user_id
    ))

    if season_number is not None:
        ensure_mm_season_player(season_number, user_id)

        execute("""
            UPDATE mm_season_players
            SET matches = matches + 1,
                wins = wins + ?,
                losses = losses + ?,
                win_mvp = win_mvp + ?,
                loss_mvp = loss_mvp + ?,
                elo_gained = elo_gained + ?,
                elo_lost = elo_lost + ?
            WHERE season_number = ? AND user_id = ?
        """, (
            1 if is_win else 0,
            0 if is_win else 1,
            1 if is_win_mvp else 0,
            1 if is_loss_mvp else 0,
            elo_gained,
            elo_lost,
            season_number,
            user_id
        ))


def get_member_label(guild: discord.Guild | None, user_id: int, fallback: str | None = None) -> str:
    if guild is not None:
        member = guild.get_member(user_id)
        if member:
            return member.display_name[:80]

    return (fallback or str(user_id))[:80]


# =========================
# COMPONENTS
# =========================

class JoinQueueView(discord.ui.View):
    def __init__(self, cog: "MatchmakingCog", match_number: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_number = match_number

    def refresh_labels(self):
        setters, spikers = build_queue_lines(None, self.match_number)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == f"mm_join_setter_{self.match_number}":
                    item.label = f"Join Setter ({len(setters)}/{MAX_SETTERS})"
                elif item.custom_id == f"mm_join_spiker_{self.match_number}":
                    item.label = f"Join Spiker ({len(spikers)}/{MAX_SPIKERS})"

    async def refresh_message(self, interaction: discord.Interaction):
        self.refresh_labels()
        match_row = get_match_by_number(self.match_number)
        if not match_row:
            return

        total_row = fetchone("""
            SELECT COUNT(*) AS total
            FROM mm_match_players
            WHERE match_number = ?
        """, (self.match_number,))
        total = total_row["total"] if total_row else 0

        if total == 12 and match_row["status"] == "queue_open":
            execute("""
                UPDATE mm_matches
                SET status = 'captains_pending'
                WHERE match_number = ?
            """, (self.match_number,))
            updated = get_match_by_number(self.match_number)
            await interaction.message.edit(
                embed=build_captains_embed(interaction.guild, updated),
                view=CaptainSetupView(self.cog, self.match_number)
            )
            return

        await interaction.message.edit(
            embed=build_queue_embed(interaction.guild, match_row),
            view=self
        )

    @discord.ui.button(
        label="Join Setter (0/4)",
        style=discord.ButtonStyle.primary,
        custom_id="temp"
    )
    async def join_setter(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.custom_id = f"mm_join_setter_{self.match_number}"

        if not isinstance(interaction.user, discord.Member):
            return

        match_row = get_match_by_number(self.match_number)
        if not match_row or match_row["status"] != "queue_open":
            await interaction.response.send_message("This queue is no longer open.", ephemeral=True)
            return

        if is_user_busy(interaction.user.id):
            await interaction.response.send_message("Você já está em outra queue/match ativa.", ephemeral=True)
            return

        count_row = fetchone("""
            SELECT COUNT(*) AS total
            FROM mm_match_players
            WHERE match_number = ? AND role_pref = 'setter'
        """, (self.match_number,))
        setter_count = count_row["total"] if count_row else 0

        if setter_count >= MAX_SETTERS:
            await interaction.response.send_message("A fila de setters já está cheia.", ephemeral=True)
            return

        execute("""
            INSERT INTO mm_match_players (
                match_number, user_id, role_pref, team_side, captain, pick_order, joined_at
            )
            VALUES (?, ?, 'setter', NULL, 0, NULL, ?)
        """, (self.match_number, interaction.user.id, now_str()))

        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(
        label="Join Spiker (0/8)",
        style=discord.ButtonStyle.success,
        custom_id="temp2"
    )
    async def join_spiker(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.custom_id = f"mm_join_spiker_{self.match_number}"

        if not isinstance(interaction.user, discord.Member):
            return

        match_row = get_match_by_number(self.match_number)
        if not match_row or match_row["status"] != "queue_open":
            await interaction.response.send_message("This queue is no longer open.", ephemeral=True)
            return

        if is_user_busy(interaction.user.id):
            await interaction.response.send_message("Você já está em outra queue/match ativa.", ephemeral=True)
            return

        count_row = fetchone("""
            SELECT COUNT(*) AS total
            FROM mm_match_players
            WHERE match_number = ? AND role_pref = 'spiker'
        """, (self.match_number,))
        spiker_count = count_row["total"] if count_row else 0

        if spiker_count >= MAX_SPIKERS:
            await interaction.response.send_message("A fila de spikers já está cheia.", ephemeral=True)
            return

        execute("""
            INSERT INTO mm_match_players (
                match_number, user_id, role_pref, team_side, captain, pick_order, joined_at
            )
            VALUES (?, ?, 'spiker', NULL, 0, NULL, ?)
        """, (self.match_number, interaction.user.id, now_str()))

        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(
        label="Leave Queue",
        style=discord.ButtonStyle.danger,
        custom_id="temp3"
    )
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.custom_id = f"mm_leave_queue_{self.match_number}"

        match_row = get_match_by_number(self.match_number)
        if not match_row or match_row["status"] != "queue_open":
            await interaction.response.send_message("This queue is no longer open.", ephemeral=True)
            return

        row = fetchone("""
            SELECT * FROM mm_match_players
            WHERE match_number = ? AND user_id = ?
        """, (self.match_number, interaction.user.id))

        if not row:
            await interaction.response.send_message("Você não está nessa fila.", ephemeral=True)
            return

        execute("""
            DELETE FROM mm_match_players
            WHERE match_number = ? AND user_id = ?
        """, (self.match_number, interaction.user.id))

        await interaction.response.defer()
        await self.refresh_message(interaction)


class CaptainPickSelect(discord.ui.Select):
    def __init__(self, cog: "MatchmakingCog", match_number: int, slot: int):
        self.cog = cog
        self.match_number = match_number
        self.slot = slot

        match_row = get_match_by_number(match_number)
        all_players = fetchall("""
            SELECT * FROM mm_match_players
            WHERE match_number = ?
            ORDER BY
                CASE role_pref WHEN 'setter' THEN 0 ELSE 1 END,
                id ASC
        """, (match_number,))

        selected_ids = {match_row["captain1_id"], match_row["captain2_id"]}
        selected_ids.discard(None)

        guild = cog.bot.get_guild(config.GUILD_ID)

        options = []
        for row in all_players:
            if row["user_id"] in selected_ids:
                continue

            member_name = get_member_label(guild, row["user_id"])
            role_name = "Setter" if row["role_pref"] == "setter" else "Wing Spiker"

            options.append(
                discord.SelectOption(
                    label=member_name,
                    value=str(row["user_id"]),
                    description=role_name[:100],
                )
            )

        super().__init__(
            placeholder=f"Select Captain {slot}",
            min_values=1,
            max_values=1,
            options=options[:25]
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_manage_matchmaking(interaction.user):
            await interaction.response.send_message("Apenas Match Organizer pode definir capitães.", ephemeral=True)
            return

        selected_user_id = int(self.values[0])

        column = "captain1_id" if self.slot == 1 else "captain2_id"
        execute(f"""
            UPDATE mm_matches
            SET {column} = ?
            WHERE match_number = ?
        """, (selected_user_id, self.match_number))

        match_row = get_match_by_number(self.match_number)

        # Update original message if possible
        try:
            await interaction.message.edit(view=None)
        except discord.HTTPException:
            pass

        if match_row and match_row["captain1_id"] and match_row["captain2_id"]:
            first_picker = random.choice([match_row["captain1_id"], match_row["captain2_id"]])

            execute("""
                UPDATE mm_matches
                SET first_picker_id = ?, status = 'draft'
                WHERE match_number = ?
            """, (first_picker, self.match_number))

            execute("""
                UPDATE mm_match_players
                SET team_side = 'A', captain = 1, pick_order = 0
                WHERE match_number = ? AND user_id = ?
            """, (self.match_number, match_row["captain1_id"]))

            execute("""
                UPDATE mm_match_players
                SET team_side = 'B', captain = 1, pick_order = 0
                WHERE match_number = ? AND user_id = ?
            """, (self.match_number, match_row["captain2_id"]))

            updated = get_match_by_number(self.match_number)
            queue_message = None

            if interaction.guild and updated and updated["queue_channel_id"] and updated["queue_message_id"]:
                channel = interaction.guild.get_channel(updated["queue_channel_id"])
                if isinstance(channel, discord.TextChannel):
                    try:
                        queue_message = await channel.fetch_message(updated["queue_message_id"])
                    except discord.HTTPException:
                        queue_message = None

            if queue_message and updated:
                await queue_message.edit(
                    embed=build_draft_embed(interaction.guild, updated),
                    view=DraftView(self.cog, self.match_number)
                )

        await interaction.response.send_message(f"Captain {self.slot} set successfully.", ephemeral=True)


class CaptainPickView(discord.ui.View):
    def __init__(self, cog: "MatchmakingCog", match_number: int, slot: int):
        super().__init__(timeout=120)
        self.add_item(CaptainPickSelect(cog, match_number, slot))


class CaptainSetupView(discord.ui.View):
    def __init__(self, cog: "MatchmakingCog", match_number: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_number = match_number

    @discord.ui.button(label="Set Captain 1", style=discord.ButtonStyle.primary)
    async def set_captain_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not can_manage_matchmaking(interaction.user):
            await interaction.response.send_message("Apenas Match Organizer pode definir capitães.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Choose Captain 1:",
            view=CaptainPickView(self.cog, self.match_number, 1),
            ephemeral=True
        )

    @discord.ui.button(label="Set Captain 2", style=discord.ButtonStyle.secondary)
    async def set_captain_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not can_manage_matchmaking(interaction.user):
            await interaction.response.send_message("Apenas Match Organizer pode definir capitães.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Choose Captain 2:",
            view=CaptainPickView(self.cog, self.match_number, 2),
            ephemeral=True
        )


class PickPlayerButton(discord.ui.Button):
    def __init__(self, cog: "MatchmakingCog", match_number: int, player_user_id: int, label_text: str, row_position: int):
        super().__init__(
            label=label_text[:80],
            style=discord.ButtonStyle.primary,
            row=row_position
        )
        self.cog = cog
        self.match_number = match_number
        self.player_user_id = player_user_id

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return

        match_row = get_match_by_number(self.match_number)
        if not match_row or match_row["status"] != "draft":
            await interaction.response.send_message("This draft is no longer active.", ephemeral=True)
            return

        captain_side = get_captain_side(self.match_number, interaction.user.id)
        if not captain_side:
            await interaction.response.send_message("Only the selected captains can pick players.", ephemeral=True)
            return

        current_turn_side = get_current_turn_side(match_row)
        if captain_side != current_turn_side:
            await interaction.response.send_message("It is not your turn to pick.", ephemeral=True)
            return

        player_row = fetchone("""
            SELECT * FROM mm_match_players
            WHERE match_number = ? AND user_id = ? AND team_side IS NULL
        """, (self.match_number, self.player_user_id))
        if not player_row:
            await interaction.response.send_message("This player is no longer available.", ephemeral=True)
            return

        max_role_count = 2 if player_row["role_pref"] == "setter" else 4
        current_role_count = count_team_role(self.match_number, captain_side, player_row["role_pref"])

        if current_role_count >= max_role_count:
            await interaction.response.send_message(
                f"Your team already has the maximum number of {player_row['role_pref']}s.",
                ephemeral=True
            )
            return

        pick_order = get_pick_count(self.match_number) + 1

        execute("""
            UPDATE mm_match_players
            SET team_side = ?, pick_order = ?
            WHERE match_number = ? AND user_id = ?
        """, (captain_side, pick_order, self.match_number, self.player_user_id))

        updated = get_match_by_number(self.match_number)
        remaining = get_available_players(self.match_number)

        if not remaining:
            execute("""
                UPDATE mm_matches
                SET status = 'ready_to_start'
                WHERE match_number = ?
            """, (self.match_number,))
            final_match = get_match_by_number(self.match_number)

            await interaction.response.edit_message(
                embed=build_ready_embed(interaction.guild, final_match),
                view=StartMatchView(self.cog, self.match_number)
            )
            return

        updated = get_match_by_number(self.match_number)
        await interaction.response.edit_message(
            embed=build_draft_embed(interaction.guild, updated),
            view=DraftView(self.cog, self.match_number)
        )


class DraftView(discord.ui.View):
    def __init__(self, cog: "MatchmakingCog", match_number: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_number = match_number

        available = get_available_players(match_number)
        guild = cog.bot.get_guild(config.GUILD_ID)

        for index, row in enumerate(available[:25]):
            member_name = get_member_label(guild, row["user_id"])
            label = f"{member_name} [{role_short(row['role_pref'])}]"
            self.add_item(
                PickPlayerButton(
                    cog=cog,
                    match_number=match_number,
                    player_user_id=row["user_id"],
                    label_text=label,
                    row_position=min(index // 5, 4)
                )
            )


class PrivateServerModal(discord.ui.Modal, title="Start Match"):
    private_server_link = discord.ui.TextInput(
        label="Private Server Link",
        style=discord.TextStyle.paragraph,
        required=True,
        placeholder="Paste the Volleyball 4.2 private server link here..."
    )

    def __init__(self, cog: "MatchmakingCog", match_number: int):
        super().__init__()
        self.cog = cog
        self.match_number = match_number

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_manage_matchmaking(interaction.user):
            await interaction.response.send_message("Apenas Match Organizer pode iniciar a partida.", ephemeral=True)
            return

        match_row = get_match_by_number(self.match_number)
        if not match_row or match_row["status"] != "ready_to_start":
            await interaction.response.send_message("This match is not ready to be started.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        category = guild.get_channel(MATCHMAKING_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Match Making category not found.", ephemeral=True)
            return

        team_a = get_team_players(self.match_number, "A")
        team_b = get_team_players(self.match_number, "B")

        overwrites_text = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        for row in team_a + team_b:
            member = guild.get_member(row["user_id"])
            if member:
                overwrites_text[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        text_channel = await guild.create_text_channel(
            name=f"mm-{self.match_number}",
            category=category,
            overwrites=overwrites_text,
            reason=f"Match Making #{self.match_number} started by {interaction.user}"
        )

        overwrites_team_a = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True),
            interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
        }

        overwrites_team_b = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, move_members=True),
            interaction.user: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
        }

        for row in team_a:
            member = guild.get_member(row["user_id"])
            if member:
                overwrites_team_a[member] = discord.PermissionOverwrite(view_channel=True, connect=True)

        for row in team_b:
            member = guild.get_member(row["user_id"])
            if member:
                overwrites_team_b[member] = discord.PermissionOverwrite(view_channel=True, connect=True)

        team_a_voice = await guild.create_voice_channel(
            name=f"MM #{self.match_number} • Team A",
            category=category,
            overwrites=overwrites_team_a,
            reason=f"Match Making #{self.match_number} Team A voice"
        )

        team_b_voice = await guild.create_voice_channel(
            name=f"MM #{self.match_number} • Team B",
            category=category,
            overwrites=overwrites_team_b,
            reason=f"Match Making #{self.match_number} Team B voice"
        )

        execute("""
            UPDATE mm_matches
            SET status = 'in_progress',
                private_server_link = ?,
                text_channel_id = ?,
                team_a_voice_id = ?,
                team_b_voice_id = ?,
                started_at = ?
            WHERE match_number = ?
        """, (
            str(self.private_server_link),
            text_channel.id,
            team_a_voice.id,
            team_b_voice.id,
            now_str(),
            self.match_number
        ))

        updated = get_match_by_number(self.match_number)

        await text_channel.send(embed=build_match_started_embed(guild, updated))
        await interaction.response.edit_message(
            embed=build_match_started_embed(guild, updated),
            view=None
        )


class StartMatchView(discord.ui.View):
    def __init__(self, cog: "MatchmakingCog", match_number: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_number = match_number

    @discord.ui.button(label="Start Match", style=discord.ButtonStyle.success)
    async def start_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not can_manage_matchmaking(interaction.user):
            await interaction.response.send_message("Apenas Match Organizer pode iniciar a partida.", ephemeral=True)
            return

        await interaction.response.send_modal(PrivateServerModal(self.cog, self.match_number))


# =========================
# MAIN COG
# =========================

TEAM_CHOICES = [
    app_commands.Choice(name="Team A", value="A"),
    app_commands.Choice(name="Team B", value="B"),
]


class MatchmakingCog(commands.Cog):
    mm = app_commands.Group(
        name="mm",
        description="Match Making commands",
        guild_ids=[config.GUILD_ID]
    )

    season = app_commands.Group(
        name="season",
        description="Season commands",
        guild_ids=[config.GUILD_ID]
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_matchmaking_tables()

    @season.command(name="start", description="Starts a new Match Making season")
    async def season_start(self, interaction: discord.Interaction, number: int):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_manage_season(interaction.user):
            await interaction.response.send_message("Apenas Staff/Admin pode iniciar seasons.", ephemeral=True)
            return

        active = get_active_season()
        if active:
            await interaction.response.send_message(
                f"Season {active['number']} is already active.",
                ephemeral=True
            )
            return

        existing = fetchone("SELECT * FROM mm_seasons WHERE number = ?", (number,))
        if existing:
            execute("""
                UPDATE mm_seasons
                SET is_active = 1, started_at = ?, ended_at = NULL
                WHERE number = ?
            """, (now_str(), number))
        else:
            execute("""
                INSERT INTO mm_seasons (number, is_active, started_at, ended_at)
                VALUES (?, 1, ?, NULL)
            """, (number, now_str()))

        await interaction.response.send_message(f"Season {number} started successfully.")

    @season.command(name="end", description="Ends the active Match Making season")
    async def season_end(self, interaction: discord.Interaction, number: int):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_manage_season(interaction.user):
            await interaction.response.send_message("Apenas Staff/Admin pode encerrar seasons.", ephemeral=True)
            return

        active = get_active_season()
        if not active or active["number"] != number:
            await interaction.response.send_message("This season is not the currently active season.", ephemeral=True)
            return

        active_match = fetchone("""
            SELECT * FROM mm_matches
            WHERE status IN ('queue_open', 'captains_pending', 'draft', 'ready_to_start', 'in_progress')
            LIMIT 1
        """)
        if active_match:
            await interaction.response.send_message(
                "Há uma match making ativa. Finalize ou limpe as partidas antes de encerrar a season.",
                ephemeral=True
            )
            return

        execute("""
            UPDATE mm_seasons
            SET is_active = 0, ended_at = ?
            WHERE number = ?
        """, (now_str(), number))

        await interaction.response.send_message(f"Season {number} ended successfully.")

    @season.command(name="stats", description="Shows season stats")
    async def season_stats(self, interaction: discord.Interaction, number: int):
        season_row = fetchone("SELECT * FROM mm_seasons WHERE number = ?", (number,))
        if not season_row:
            await interaction.response.send_message("Season not found.", ephemeral=True)
            return

        top_rows = fetchall("""
            SELECT *
            FROM mm_season_players
            WHERE season_number = ?
            ORDER BY (elo_gained - elo_lost) DESC, wins DESC, matches DESC
            LIMIT 10
        """, (number,))

        leaderboard_lines = []
        guild = interaction.guild
        for index, row in enumerate(top_rows, start=1):
            net_elo = row["elo_gained"] - row["elo_lost"]
            leaderboard_lines.append(
                f"`#{index}` {mention_or_name(guild, row['user_id'])} • Net `{net_elo}` • W-L `{row['wins']}-{row['losses']}` • Matches `{row['matches']}`"
            )

        total_matches_row = fetchone("""
            SELECT COUNT(*) AS total
            FROM mm_matches
            WHERE season_number = ? AND status = 'finished'
        """, (number,))
        total_matches = total_matches_row["total"] if total_matches_row else 0

        embed = discord.Embed(
            title=f"Season {number} Stats",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Status",
            value="Active" if season_row["is_active"] else "Closed",
            inline=True
        )
        embed.add_field(
            name="Started",
            value=season_row["started_at"] or "—",
            inline=True
        )
        embed.add_field(
            name="Ended",
            value=season_row["ended_at"] or "—",
            inline=True
        )
        embed.add_field(
            name="Finished Matches",
            value=str(total_matches),
            inline=False
        )
        embed.add_field(
            name="Top 10 Leaderboard",
            value=chr(10).join(leaderboard_lines) if leaderboard_lines else "No data yet.",
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    @mm.command(name="start", description="Starts a Match Making queue")
    async def mm_start(self, interaction: discord.Interaction, number: int):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_manage_matchmaking(interaction.user):
            await interaction.response.send_message("Apenas Match Organizer pode usar esse comando.", ephemeral=True)
            return

        season_row = get_active_season()
        if not season_row:
            await interaction.response.send_message("There is no active season. Use /season start first.", ephemeral=True)
            return

        existing = get_match_by_number(number)
        if existing:
            await interaction.response.send_message("This match number already exists.", ephemeral=True)
            return

        execute("""
            INSERT INTO mm_matches (
                match_number, season_number, status, created_by_id,
                queue_channel_id, queue_message_id, created_at
            )
            VALUES (?, ?, 'queue_open', ?, ?, NULL, ?)
        """, (
            number,
            season_row["number"],
            interaction.user.id,
            interaction.channel_id,
            now_str()
        ))

        match_row = get_match_by_number(number)
        view = JoinQueueView(self, number)
        view.refresh_labels()

        await interaction.response.send_message(
            embed=build_queue_embed(interaction.guild, match_row),
            view=view
        )

        sent_message = await interaction.original_response()
        execute("""
            UPDATE mm_matches
            SET queue_message_id = ?
            WHERE match_number = ?
        """, (sent_message.id, number))

    @mm.command(name="finish", description="Finishes an in-progress Match Making match")
    @app_commands.choices(winner_team=TEAM_CHOICES, loser_team=TEAM_CHOICES)
    async def mm_finish(
        self,
        interaction: discord.Interaction,
        number: int,
        winner_team: app_commands.Choice[str],
        loser_team: app_commands.Choice[str],
        wmvp: discord.Member,
        lmvp: discord.Member
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_manage_matchmaking(interaction.user):
            await interaction.response.send_message("Apenas Match Organizer pode finalizar a partida.", ephemeral=True)
            return

        if winner_team.value == loser_team.value:
            await interaction.response.send_message("Winner team and loser team must be different.", ephemeral=True)
            return

        match_row = get_match_by_number(number)
        if not match_row:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return

        if match_row["status"] != "in_progress":
            await interaction.response.send_message("This match is not currently in progress.", ephemeral=True)
            return

        wmvp_row = fetchone("""
            SELECT * FROM mm_match_players
            WHERE match_number = ? AND user_id = ? AND team_side = ?
        """, (number, wmvp.id, winner_team.value))

        lmvp_row = fetchone("""
            SELECT * FROM mm_match_players
            WHERE match_number = ? AND user_id = ? AND team_side = ?
        """, (number, lmvp.id, loser_team.value))

        if not wmvp_row:
            await interaction.response.send_message("WMVP must belong to the winner team.", ephemeral=True)
            return

        if not lmvp_row:
            await interaction.response.send_message("LMVP must belong to the loser team.", ephemeral=True)
            return

        await interaction.response.defer()

        players = get_match_players(number)
        season_number = match_row["season_number"]

        for row in players:
            if row["team_side"] == winner_team.value:
                delta = WIN_ELO + (WIN_MVP_BONUS if row["user_id"] == wmvp.id else 0)
                apply_match_result_to_player(
                    user_id=row["user_id"],
                    season_number=season_number,
                    delta=delta,
                    is_win=True,
                    is_win_mvp=(row["user_id"] == wmvp.id),
                    is_loss_mvp=False
                )
            else:
                delta = LOSS_MVP_ELO if row["user_id"] == lmvp.id else LOSS_ELO
                apply_match_result_to_player(
                    user_id=row["user_id"],
                    season_number=season_number,
                    delta=delta,
                    is_win=False,
                    is_win_mvp=False,
                    is_loss_mvp=(row["user_id"] == lmvp.id)
                )

        execute("""
            UPDATE mm_matches
            SET status = 'finished',
                winner_side = ?,
                loser_side = ?,
                wmvp_id = ?,
                lmvp_id = ?,
                finished_at = ?
            WHERE match_number = ?
        """, (
            winner_team.value,
            loser_team.value,
            wmvp.id,
            lmvp.id,
            now_str(),
            number
        ))

        updated = get_match_by_number(number)
        guild = interaction.guild

        if guild is not None:
            results_channel = guild.get_channel(MM_RESULTS_CHANNEL_ID)
            if isinstance(results_channel, discord.TextChannel):
                await results_channel.send(embed=build_result_embed(guild, updated))

            # Update queue message
            if updated["queue_channel_id"] and updated["queue_message_id"]:
                queue_channel = guild.get_channel(updated["queue_channel_id"])
                if isinstance(queue_channel, discord.TextChannel):
                    try:
                        queue_message = await queue_channel.fetch_message(updated["queue_message_id"])
                        await queue_message.edit(embed=build_result_embed(guild, updated), view=None)
                    except discord.HTTPException:
                        pass

            # Delete temporary channels
            for channel_id in [updated["text_channel_id"], updated["team_a_voice_id"], updated["team_b_voice_id"]]:
                if not channel_id:
                    continue
                channel = guild.get_channel(channel_id)
                if channel:
                    try:
                        await channel.delete(reason=f"Match Making #{number} finished")
                    except discord.HTTPException:
                        pass

        await interaction.followup.send(f"Match #{number} finished successfully.", ephemeral=True)

    @mm.command(name="elo", description="Shows your Match Making ELO")
    async def mm_elo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user

        ensure_mm_player(target.id)
        row = fetchone("SELECT * FROM mm_players WHERE user_id = ?", (target.id,))
        season_row = get_active_season()

        embed = discord.Embed(
            title=f"{target.display_name} • MM Profile",
            color=discord.Color.blurple()
        )
        embed.add_field(name="ELO", value=str(row["elo"]), inline=True)
        embed.add_field(name="Matches", value=str(row["matches"]), inline=True)
        embed.add_field(name="W-L", value=f"{row['wins']}-{row['losses']}", inline=True)
        embed.add_field(name="Win MVP", value=str(row["win_mvp"]), inline=True)
        embed.add_field(name="Loss MVP", value=str(row["loss_mvp"]), inline=True)
        embed.add_field(
            name="Total ELO",
            value=f"+{row['elo_gained_total']} / -{row['elo_lost_total']}",
            inline=True
        )

        if season_row:
            season_player = fetchone("""
                SELECT * FROM mm_season_players
                WHERE season_number = ? AND user_id = ?
            """, (season_row["number"], target.id))

            if season_player:
                embed.add_field(
                    name=f"Season {season_row['number']}",
                    value=(
                        f"Matches: `{season_player['matches']}`\n"
                        f"W-L: `{season_player['wins']}-{season_player['losses']}`\n"
                        f"ELO: `+{season_player['elo_gained']} / -{season_player['elo_lost']}`"
                    ),
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    @mm.command(name="leaderboard", description="Shows the Match Making leaderboard")
    async def mm_leaderboard(self, interaction: discord.Interaction, page: int = 1, season_number: int | None = None):
        if page < 1:
            await interaction.response.send_message("Page must be 1 or greater.", ephemeral=True)
            return

        per_page = 10
        offset = (page - 1) * per_page
        guild = interaction.guild

        if season_number is None:
            rows = fetchall(f"""
                SELECT *
                FROM mm_players
                ORDER BY elo DESC, wins DESC, matches DESC
                LIMIT {per_page} OFFSET {offset}
            """)

            title = "MM Global Leaderboard"
            lines = []
            start_rank = offset + 1

            for i, row in enumerate(rows, start=start_rank):
                lines.append(
                    f"`#{i}` {mention_or_name(guild, row['user_id'])} • ELO `{row['elo']}` • W-L `{row['wins']}-{row['losses']}` • M `{row['matches']}`"
                )
        else:
            rows = fetchall(f"""
                SELECT *
                FROM mm_season_players
                WHERE season_number = ?
                ORDER BY (elo_gained - elo_lost) DESC, wins DESC, matches DESC
                LIMIT {per_page} OFFSET {offset}
            """, (season_number,))

            title = f"MM Season {season_number} Leaderboard"
            lines = []
            start_rank = offset + 1

            for i, row in enumerate(rows, start=start_rank):
                net = row["elo_gained"] - row["elo_lost"]
                lines.append(
                    f"`#{i}` {mention_or_name(guild, row['user_id'])} • Net `{net}` • W-L `{row['wins']}-{row['losses']}` • M `{row['matches']}`"
                )

        embed = discord.Embed(
            title=title,
            description=chr(10).join(lines) if lines else "No data found for this page.",
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Page {page}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchmakingCog(bot))