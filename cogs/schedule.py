from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from database import execute, fetchall, fetchone

BRT = ZoneInfo("America/Sao_Paulo")


def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator


def parse_next_match_datetime(time_brt: str) -> datetime | None:
    try:
        hour, minute = map(int, time_brt.split(":"))
    except ValueError:
        return None

    now = datetime.now(BRT)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if target <= now:
        target += timedelta(days=1)

    return target


class ScheduleCog(commands.Cog):
    schedule = app_commands.Group(
        name="schedule",
        description="Schedule commands",
        guild_ids=[config.GUILD_ID]
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.schedule_reminder_loop.start()

    def cog_unload(self):
        self.schedule_reminder_loop.cancel()

    @tasks.loop(minutes=1)
    async def schedule_reminder_loop(self):
        rows = fetchall("SELECT * FROM schedules WHERE reminded = 0")

        for row in rows:
            match_dt = datetime.fromisoformat(row["match_time_iso"]).astimezone(BRT)
            now = datetime.now(BRT)
            reminder_dt = match_dt - timedelta(minutes=15)

            if now >= match_dt:
                execute("UPDATE schedules SET reminded = 1 WHERE id = ?", (row["id"],))
                continue

            if now >= reminder_dt:
                guild = self.bot.get_guild(config.GUILD_ID)
                if guild is None:
                    continue

                team1_role = guild.get_role(row["team1_role_id"])
                team2_role = guild.get_role(row["team2_role_id"])

                members = set()
                if team1_role:
                    members.update([m for m in team1_role.members if not m.bot])
                if team2_role:
                    members.update([m for m in team2_role.members if not m.bot])

                for member in members:
                    try:
                        await member.send(
                            f"Reminder: **{row['team1_name']} vs {row['team2_name']}** começa em 15 minutos.\n"
                            f"Horário: {match_dt.strftime('%d/%m/%Y %H:%M')} BRT\n"
                            f"Match ID: {row['id']}"
                        )
                    except discord.Forbidden:
                        pass

                execute("UPDATE schedules SET reminded = 1 WHERE id = ?", (row["id"],))

    @schedule_reminder_loop.before_loop
    async def before_schedule_loop(self):
        await self.bot.wait_until_ready()

    @schedule.command(name="match", description="Agenda uma partida")
    async def schedule_match(
        self,
        interaction: discord.Interaction,
        team1: discord.Role,
        team2: discord.Role,
        time_brt: str
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message("Apenas administração pode usar esse comando.", ephemeral=True)
            return

        if team1.id == team2.id:
            await interaction.response.send_message("Os dois times não podem ser o mesmo.", ephemeral=True)
            return

        target_dt = parse_next_match_datetime(time_brt)
        if target_dt is None:
            await interaction.response.send_message("Formato de horário inválido. Use HH:MM, por exemplo 16:00", ephemeral=True)
            return

        schedule_id = execute("""
            INSERT INTO schedules (
                team1_role_id, team1_name,
                team2_role_id, team2_name,
                match_time_iso, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            team1.id, team1.name,
            team2.id, team2.name,
            target_dt.isoformat(),
            interaction.user.id
        ))

        embed = discord.Embed(
            title="Match Scheduled",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Match ID", value=str(schedule_id), inline=True)
        embed.add_field(name="Teams", value=f"{team1.mention} vs {team2.mention}", inline=False)
        embed.add_field(name="Time (BRT)", value=target_dt.strftime("%d/%m/%Y %H:%M"), inline=False)
        embed.set_footer(text="15 minutes reminder enabled")

        await interaction.response.send_message(embed=embed)

    @schedule.command(name="list", description="Lista partidas agendadas")
    async def schedule_list(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message("Apenas administração pode usar esse comando.", ephemeral=True)
            return

        rows = fetchall("""
            SELECT * FROM schedules
            ORDER BY match_time_iso ASC
        """)

        if not rows:
            await interaction.response.send_message("Não há partidas agendadas.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Scheduled Matches",
            color=discord.Color.blue()
        )

        lines = []
        for row in rows:
            dt = datetime.fromisoformat(row["match_time_iso"]).astimezone(BRT)
            lines.append(
                f"**ID {row['id']}** — {row['team1_name']} vs {row['team2_name']} — {dt.strftime('%d/%m/%Y %H:%M')} BRT"
            )

        embed.description = "\n".join(lines[:20])
        await interaction.response.send_message(embed=embed)

    @schedule.command(name="remove", description="Remove uma partida agendada")
    async def schedule_remove(self, interaction: discord.Interaction, match_id: int):
        if not isinstance(interaction.user, discord.Member):
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message("Apenas administração pode usar esse comando.", ephemeral=True)
            return

        row = fetchone("SELECT * FROM schedules WHERE id = ?", (match_id,))
        if not row:
            await interaction.response.send_message("Esse Match ID não existe.", ephemeral=True)
            return

        execute("DELETE FROM schedules WHERE id = ?", (match_id,))

        await interaction.response.send_message(
            f"Partida **ID {match_id}** removida com sucesso.\n"
            f"{row['team1_name']} vs {row['team2_name']}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ScheduleCog(bot))