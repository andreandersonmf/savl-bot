import discord
from discord.ext import commands
from discord import Object

import config
from database import init_db

EXTENSIONS = [
    "cogs.team",
    "cogs.match",
    "cogs.schedule",
    "cogs.scrim",
]


class SAVLBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.guilds = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):
        init_db()

        guild_obj = Object(id=config.GUILD_ID)

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                print(f"[OK] Loaded extension: {ext}")
            except Exception as e:
                print(f"[ERROR] Failed to load extension {ext}: {e}")

        try:
            synced = await self.tree.sync(guild=guild_obj)
            print(f"[OK] Synced {len(synced)} command(s) to guild {config.GUILD_ID}")
            for cmd in synced:
                print(f" - /{cmd.name}")
        except Exception as e:
            print(f"[ERROR] Failed to sync commands: {e}")

    async def on_ready(self):
        print(f"Logado como {self.user} (ID: {self.user.id})")


bot = SAVLBot()
bot.run(config.DISCORD_TOKEN)