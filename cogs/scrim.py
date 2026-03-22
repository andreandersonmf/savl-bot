import discord
from discord import app_commands
from discord.ext import commands

SCRIM_CHANNEL_ID = 1484037331534086206

async def setup(bot):
    await bot.add_cog(Scrim(bot))

class ScrimView(discord.ui.View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="Message", style=discord.ButtonStyle.secondary, emoji="✉️")
    async def message_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"Message {self.user.mention} in DM.",
            ephemeral=True
        )


class Scrim(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="scrim", description="Create a scrim request")
    @app_commands.describe(type="Now or Schedule")
    @app_commands.choices(type=[
        app_commands.Choice(name="Now", value="Now"),
        app_commands.Choice(name="Schedule", value="Schedule"),
    ])
    async def scrim(self, interaction: discord.Interaction, type: app_commands.Choice[str]):

        # 🔒 Canal restrito
        if interaction.channel_id != SCRIM_CHANNEL_ID:
            await interaction.response.send_message(
                "You can only use this command in the scrim channel.",
                ephemeral=True
            )
            return

        user = interaction.user

        embed = discord.Embed(
            title="Scrim request",
            color=discord.Color.dark_blue()
        )

        embed.description = (
            f"from {user.mention}\n"
            f"Region: **{type.value}**"
        )

        embed.set_footer(text="SAVL Services")

        view = ScrimView(user)

        await interaction.response.send_message(embed=embed, view=view)