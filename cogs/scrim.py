import discord
from discord import app_commands, Object
from discord.ext import commands

import config

SCRIM_CHANNEL_ID = 1484037331534086206


class ScrimView(discord.ui.View):
    def __init__(self, user: discord.abc.User):
        super().__init__(timeout=None)

        self.add_item(
            discord.ui.Button(
                label="Message",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/users/{user.id}"
            )
        )


class Scrim(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="scrim", description="Create a scrim request")
    @app_commands.describe(scrim_type="Now or Schedule")
    @app_commands.choices(scrim_type=[
        app_commands.Choice(name="Now", value="Now"),
        app_commands.Choice(name="Schedule", value="Schedule"),
    ])
    async def scrim(self, interaction: discord.Interaction, scrim_type: app_commands.Choice[str]):
        if interaction.channel_id != SCRIM_CHANNEL_ID:
            await interaction.response.send_message(
                "You can only use this command in the scrim channel.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Scrim request",
            color=discord.Color.blurple()
        )
        embed.description = (
            f"from {interaction.user.mention}\n"
            f"Type: **{scrim_type.value}**"
        )
        embed.set_footer(text="SAVL Services")

        await interaction.response.send_message(
            embed=embed,
            view=ScrimView(interaction.user)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        Scrim(bot),
        guild=Object(id=config.GUILD_ID)
    )