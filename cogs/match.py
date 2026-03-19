from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import execute


def is_allowed(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    role_ids = {role.id for role in member.roles}
    return (
        config.REFEREE_ROLE_ID in role_ids
        or config.STREAMER_ROLE_ID in role_ids
    )


def parse_set_score(set_score: str):
    try:
        left, right = set_score.split("-")
        return int(left.strip()), int(right.strip())
    except Exception:
        return None


def count_series(*sets_: str | None):
    wins_a = 0
    wins_b = 0

    for s in sets_:
        if not s:
            continue
        parsed = parse_set_score(s)
        if not parsed:
            continue
        a, b = parsed
        if a > b:
            wins_a += 1
        elif b > a:
            wins_b += 1

    return wins_a, wins_b


class MatchCog(commands.Cog):
    match = app_commands.Group(
        name="match",
        description="Match commands",
        guild_ids=[config.GUILD_ID]
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @match.command(name="result", description="Posta o resultado de uma partida")
    async def match_result(
        self,
        interaction: discord.Interaction,
        stage: str,
        set1: str,
        set2: str,
        winner_team: discord.Role,
        loser_team: discord.Role,
        wmvp: discord.Member,
        lmvp: discord.Member,
        referee: discord.Member,
        media: str,
        set3: str | None = None,
        set4: str | None = None,
        set5: str | None = None,
    ):
        if not isinstance(interaction.user, discord.Member):
            return

        if not is_allowed(interaction.user):
            await interaction.response.send_message(
                "Apenas referee, streamer ou administração podem usar esse comando.",
                ephemeral=True
            )
            return

        winner_sets, loser_sets = count_series(set1, set2, set3, set4, set5)

        embed = discord.Embed(
            title="Match Result",
            description=f"**{winner_team.mention}** defeated **{loser_team.mention}**",
            color=discord.Color.gold()
        )

        embed.add_field(name="Stage", value=stage, inline=False)
        embed.add_field(name="Series", value=f"{winner_sets} - {loser_sets}", inline=False)

        sets_lines = [
            f"Set 1: {set1}",
            f"Set 2: {set2}",
        ]

        if set3:
            sets_lines.append(f"Set 3: {set3}")
        if set4:
            sets_lines.append(f"Set 4: {set4}")
        if set5:
            sets_lines.append(f"Set 5: {set5}")

        embed.add_field(name="Set Scores", value="\n".join(sets_lines), inline=False)

        embed.add_field(name="Winner MVP", value=wmvp.mention, inline=True)
        embed.add_field(name="Loser MVP", value=lmvp.mention, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        embed.add_field(
            name="Match Staff",
            value=f"*Referee:* {referee.mention}\n*Media:* {media}",
            inline=False
        )
        
        embed.set_footer(text="SAVL Services")

        execute("""
            INSERT INTO match_results (
                stage, set1, set2, set3, set4, set5,
                winner_team_role_id, loser_team_role_id,
                winner_mvp_discord_id, loser_mvp_discord_id,
                referee_discord_id, media_link, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stage, set1, set2, set3, set4, set5,
            winner_team.id, loser_team.id,
            wmvp.id, lmvp.id,
            referee.id, media, interaction.user.id
        ))

        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCog(bot))