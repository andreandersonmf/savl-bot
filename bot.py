import discord

from discord.ext import commands
from discord import Object

import config
from database import init_db

EXTENSIONS = [
    "cogs.team",
    "cogs.match",
    "cogs.schedule",
]

class SAVLBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):
        init_db()

        for ext in EXTENSIONS:
            await self.load_extension(ext)

        guild_obj = Object(id=config.GUILD_ID)
        await self.tree.sync(guild=guild_obj)

    async def on_ready(self):
        print(f"Logado como {self.user} (ID: {self.user.id})")


bot = SAVLBot()
bot.run(config.DISCORD_TOKEN)