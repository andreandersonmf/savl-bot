import discord

def build_rules_embed():
    embed = discord.Embed(
        title="📜 SAVL Official Rules",
        description=(
            "Welcome to the South America Volleyball League.\n"
            "Please read all rules carefully. By participating in SAVL, "
            "you agree to follow them at all times."
        ),
        color=discord.Color.dark_red()
    )

    embed.add_field(
        name="1. Respect",
        value=(
            "Treat all members with respect.\n"
            "No toxicity, harassment or discrimination."
        ),
        inline=False
    )

    embed.add_field(
        name="2. Fair Play",
        value=(
            "No cheating or exploiting.\n"
            "All matches must be played fairly."
        ),
        inline=False
    )

    embed.add_field(
        name="3. Staff Authority",
        value="Staff decisions must be respected.",
        inline=False
    )

    embed.add_field(
        name="4. Team Responsibility",
        value="Captains must manage teams properly.",
        inline=False
    )

    embed.add_field(
        name="5. Penalties",
        value="Warnings, suspensions or bans may apply.",
        inline=False
    )

    embed.set_thumbnail(url="attachment://savl-logo.jpg")
    embed.set_image(url="attachment://rules-banner.png")
    embed.set_footer(text="SAVL • South America Volleyball League")

    return embed