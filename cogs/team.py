from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import execute, fetchone, fetchall
from utils.roblox import get_profile_data_from_member


ROLE_CHOICES = [
    app_commands.Choice(name="Player", value="player"),
    app_commands.Choice(name="Vice Captain", value="vice_captain"),
]


def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator


def has_role(member: discord.Member, role_id: int) -> bool:
    return any(role.id == role_id for role in member.roles)


def can_manage_team(member: discord.Member) -> bool:
    return has_role(member, config.CAPTAIN_ROLE_ID) or has_role(member, config.VICE_CAPTAIN_ROLE_ID)


def can_approve_transfer(member: discord.Member) -> bool:
    if is_admin(member):
        return True

    member_role_ids = {role.id for role in member.roles}
    return any(role_id in member_role_ids for role_id in config.STAFF_APPROVER_ROLE_IDS)


def in_transactions_channel(interaction: discord.Interaction) -> bool:
    return interaction.channel_id == config.TRANSACTIONS_CHANNEL_ID


def in_self_transactions_channel(interaction: discord.Interaction) -> bool:
    return interaction.channel_id == config.SELF_TRANSACTIONS_CHANNEL_ID


def get_management_team(member: discord.Member):
    team = fetchone(
        "SELECT * FROM teams WHERE captain_discord_id = ?",
        (member.id,)
    )
    if team:
        return team

    team = fetchone("""
        SELECT t.* FROM teams t
        JOIN roster r ON r.team_id = t.id
        WHERE r.discord_id = ? AND r.role_type = 'vice_captain'
    """, (member.id,))
    return team


def get_team_by_role(role_id: int):
    return fetchone("SELECT * FROM teams WHERE team_role_id = ?", (role_id,))


def get_player_current_team(discord_id: int):
    team = fetchone("""
        SELECT t.* FROM teams t
        JOIN roster r ON r.team_id = t.id
        WHERE r.discord_id = ?
    """, (discord_id,))
    if team:
        return team

    team = fetchone(
        "SELECT * FROM teams WHERE captain_discord_id = ?",
        (discord_id,)
    )
    return team


def profile_only_view(profile_url: str):
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Profile", style=discord.ButtonStyle.link, url=profile_url))
    return view


def build_release_embed(requester: discord.Member, player: discord.Member, team_name: str):
    embed = discord.Embed(
        title="Player Released",
        description=(
            f"*submitted by {requester.mention}*\n"
            f"{player.mention} has been released from **{team_name}**"
        ),
        color=discord.Color.dark_gray()
    )
    embed.set_footer(text="SAVL Services")
    return embed


def build_pending_transfer_embed(requester: discord.Member, player: discord.Member, team_name: str, requested_role: str, avatar_url: str | None):
    role_text = "Vice Captain" if requested_role == "vice_captain" else "Player"

    embed = discord.Embed(
        description=(
            f"Submitted by {requester.mention}\n\n"
            f"Transact {player.mention} to **{team_name}** as **{role_text}**"
        ),
        color=discord.Color.blurple()
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text="SAVL Services")
    return embed


def build_success_transfer_embed(requester: discord.Member, player: discord.Member, team_name: str, approver: discord.Member, avatar_url: str | None):
    embed = discord.Embed(
        title="Successful Transfer",
        description=(
            f"*requested by {requester.mention}*\n"
            f"{player.mention} was successfully transferred to **{team_name}**\n\n"
            f"Approved by {approver.mention}"
        ),
        color=discord.Color.green()
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text="SAVL Services")
    return embed


def build_denied_transfer_embed(requester: discord.Member, player: discord.Member, team_name: str, approver: discord.Member, reason: str, avatar_url: str | None):
    embed = discord.Embed(
        title="Unsuccessful Transfer",
        description=(
            f"*requested by {requester.mention}*\n"
            f"{player.mention}'s transaction to **{team_name}** was denied by {approver.mention}.\n\n"
            f"**Reason:**\n{reason}"
        ),
        color=discord.Color.red()
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text="SAVL Services")
    return embed


class DenyReasonModal(discord.ui.Modal, title="Deny Transfer"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
        placeholder="Type the reason for denying this transfer..."
    )

    def __init__(self, bot: commands.Bot, transfer_id: int, original_message: discord.Message):
        super().__init__()
        self.bot = bot
        self.transfer_id = transfer_id
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_approve_transfer(interaction.user):
            await interaction.response.send_message("Você não pode negar essa transferência.", ephemeral=True)
            return

        transfer = fetchone("SELECT * FROM transfers WHERE id = ?", (self.transfer_id,))
        if not transfer:
            await interaction.response.send_message("Transfer não encontrada.", ephemeral=True)
            return

        if transfer["status"] != "pending":
            await interaction.response.send_message("Essa transferência já foi concluída.", ephemeral=True)
            return

        team = fetchone("SELECT * FROM teams WHERE id = ?", (transfer["team_id"],))
        guild = interaction.guild
        if guild is None or team is None:
            await interaction.response.send_message("Erro ao localizar dados.", ephemeral=True)
            return

        requester = guild.get_member(transfer["requester_discord_id"])
        player = guild.get_member(transfer["player_discord_id"])
        if requester is None or player is None:
            await interaction.response.send_message("Não foi possível localizar requester/player no servidor.", ephemeral=True)
            return

        execute("""
            UPDATE transfers
            SET status = 'denied', reason = ?, handled_by = ?
            WHERE id = ?
        """, (str(self.reason), interaction.user.id, self.transfer_id))

        profile_data = await get_profile_data_from_member(player)

        embed = build_denied_transfer_embed(
            requester=requester,
            player=player,
            team_name=team["team_name"],
            approver=interaction.user,
            reason=str(self.reason),
            avatar_url=profile_data["avatar_url"]
        )

        await self.original_message.edit(
            embed=embed,
            view=profile_only_view(profile_data["profile_url"])
        )

        try:
            await requester.send(
                f"Sua solicitação para adicionar **{player.display_name}** ao time **{team['team_name']}** foi recusada.\nReason: {self.reason}"
            )
        except discord.Forbidden:
            pass

        await interaction.response.send_message("Transferência negada com sucesso.", ephemeral=True)


class TransferRequestView(discord.ui.View):
    def __init__(self, bot: commands.Bot, transfer_id: int, profile_url: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.transfer_id = transfer_id

        self.add_item(discord.ui.Button(label="Profile", style=discord.ButtonStyle.link, url=profile_url))

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_approve_transfer(interaction.user):
            await interaction.response.send_message("Apenas Staff/Admin pode aceitar essa transação.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)

        transfer = fetchone("SELECT * FROM transfers WHERE id = ?", (self.transfer_id,))
        if not transfer:
            await interaction.response.send_message("Transfer não encontrada.", ephemeral=True)
            return

        if transfer["status"] != "pending":
            await interaction.response.send_message("Essa transferência já foi concluída.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild não encontrada.", ephemeral=True)
            return

        team = fetchone("SELECT * FROM teams WHERE id = ?", (transfer["team_id"],))
        if team is None:
            await interaction.response.send_message("Time não encontrado.", ephemeral=True)
            return

        requester = guild.get_member(transfer["requester_discord_id"])
        player = guild.get_member(transfer["player_discord_id"])

        if requester is None or player is None:
            await interaction.response.send_message("Não foi possível localizar requester/player no servidor.", ephemeral=True)
            return

        existing_team = get_player_current_team(player.id)
        if existing_team:
            await interaction.response.send_message("Esse jogador já está registrado em um time.", ephemeral=True)
            return

        execute("""
            INSERT INTO roster (team_id, discord_id, role_type, added_by)
            VALUES (?, ?, ?, ?)
        """, (team["id"], player.id, transfer["requested_role_type"], interaction.user.id))

        execute("""
            UPDATE transfers
            SET status = 'accepted', handled_by = ?
            WHERE id = ?
        """, (interaction.user.id, self.transfer_id))

        team_role = guild.get_role(team["team_role_id"])
        vice_role = guild.get_role(config.VICE_CAPTAIN_ROLE_ID)
        player_role = guild.get_role(config.PLAYER_ROLE_ID) if config.PLAYER_ROLE_ID else None

        roles_to_add = []
        if team_role:
            roles_to_add.append(team_role)

        if transfer["requested_role_type"] == "vice_captain":
            if vice_role:
                roles_to_add.append(vice_role)
        else:
            if player_role:
                roles_to_add.append(player_role)

        if roles_to_add:
            await player.add_roles(*roles_to_add, reason=f"Transfer accepted by {interaction.user}")

        profile_data = await get_profile_data_from_member(player)

        embed = build_success_transfer_embed(
            requester=requester,
            player=player,
            team_name=team["team_name"],
            approver=interaction.user,
            avatar_url=profile_data["avatar_url"]
        )

        await interaction.message.edit(
            embed=embed,
            view=profile_only_view(profile_data["profile_url"])
        )

        await interaction.followup.send("Transferência aceita com sucesso.", ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            return

        if not can_approve_transfer(interaction.user):
            await interaction.response.send_message("Apenas Staff/Admin pode negar essa transação.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)

        modal = DenyReasonModal(self.bot, self.transfer_id, interaction.message)
        await interaction.response.send_modal(modal)

        await interaction.followup.send("Transferência negada com sucesso.", ephemeral=True)

def build_team_deleted_embed(requester: discord.Member, team_name: str, captain: discord.Member | None):
    embed = discord.Embed(
        title="Team Deleted",
        description=(
            f"*submitted by {requester.mention}*\n"
            f"**{team_name}** has been deleted from the system.\n\n"
            f"Captain removed: {captain.mention if captain else 'Not found'}"
        ),
        color=discord.Color.red()
    )
    embed.set_footer(text="SAVL Team System")
    return embed

class TeamCog(commands.Cog):
    team = app_commands.Group(
        name="team",
        description="Team commands",
        guild_ids=[config.GUILD_ID]
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @team.command(name="create", description="Registra um time no banco")    
    async def team_create(self, interaction: discord.Interaction, captain: discord.Member, role_team: discord.Role):
        if not isinstance(interaction.user, discord.Member):
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message("Apenas administração pode usar esse comando.", ephemeral=True)
            return

        existing_team = fetchone("SELECT * FROM teams WHERE team_role_id = ?", (role_team.id,))
        if existing_team:
            await interaction.response.send_message("Esse cargo de time já está registrado.", ephemeral=True)
            return

        existing_captain = fetchone("SELECT * FROM teams WHERE captain_discord_id = ?", (captain.id,))
        if existing_captain:
            await interaction.response.send_message("Esse capitão já está registrado em um time.", ephemeral=True)
            return

        execute("""
            INSERT INTO teams (team_name, team_role_id, captain_discord_id)
            VALUES (?, ?, ?)
        """, (role_team.name, role_team.id, captain.id))

        roles_to_add = [role_team]
        captain_role = interaction.guild.get_role(config.CAPTAIN_ROLE_ID)
        if captain_role:
            roles_to_add.append(captain_role)

        await captain.add_roles(*roles_to_add, reason="Registered as team captain")

        await interaction.response.send_message(
            f"Time **{role_team.name}** criado com sucesso.\nCapitão: {captain.mention}\nCargo do time: {role_team.mention}",
            ephemeral=False
        )

    @team.command(name="delete", description="Remove um time e seu capitão do banco")
    async def team_delete(self, interaction: discord.Interaction, team: discord.Role):
        if not isinstance(interaction.user, discord.Member):
            return

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "Apenas administração pode usar esse comando.",
                ephemeral=True
            )
            return

        team_row = get_team_by_role(team.id)
        if not team_row:
            await interaction.response.send_message(
                "Esse time não está registrado no banco.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild não encontrada.", ephemeral=True)
            return

        captain = guild.get_member(team_row["captain_discord_id"])

        # Remove todos os jogadores do roster desse time
        roster_rows = fetchall(
            "SELECT * FROM roster WHERE team_id = ?",
            (team_row["id"],)
        )

        vice_role = guild.get_role(config.VICE_CAPTAIN_ROLE_ID)
        player_role = guild.get_role(config.PLAYER_ROLE_ID) if config.PLAYER_ROLE_ID else None
        captain_role = guild.get_role(config.CAPTAIN_ROLE_ID)
        team_role = guild.get_role(team_row["team_role_id"])

        for row in roster_rows:
            member = guild.get_member(row["discord_id"])
            if member is None:
                continue

            roles_to_remove = []
            if team_role:
                roles_to_remove.append(team_role)

            if row["role_type"] == "vice_captain":
                if vice_role:
                    roles_to_remove.append(vice_role)
            else:
                if player_role:
                    roles_to_remove.append(player_role)

            if roles_to_remove:
                try:
                    await member.remove_roles(
                        *roles_to_remove,
                        reason=f"Team {team_row['team_name']} deleted by {interaction.user}"
                    )
                except discord.Forbidden:
                    pass

        # Remove cargo do capitão
        if captain is not None:
            captain_roles_to_remove = []
            if team_role:
                captain_roles_to_remove.append(team_role)
            if captain_role:
                captain_roles_to_remove.append(captain_role)

            if captain_roles_to_remove:
                try:
                    await captain.remove_roles(
                        *captain_roles_to_remove,
                        reason=f"Team {team_row['team_name']} deleted by {interaction.user}"
                    )
                except discord.Forbidden:
                    pass

        # Limpa banco
        execute("DELETE FROM roster WHERE team_id = ?", (team_row["id"],))
        execute("DELETE FROM transfers WHERE team_id = ?", (team_row["id"],))
        execute("DELETE FROM teams WHERE id = ?", (team_row["id"],))

        embed = build_team_deleted_embed(
            requester=interaction.user,
            team_name=team_row["team_name"],
            captain=captain
        )
        await interaction.response.send_message(embed=embed)        

    @team.command(name="info", description="Mostra as informações completas de um time")
    async def team_info(self, interaction: discord.Interaction, team: discord.Role):
        team_row = get_team_by_role(team.id)
        if not team_row:
            await interaction.response.send_message("Esse time não está registrado no banco.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild não encontrada.", ephemeral=True)
            return

        captain = guild.get_member(team_row["captain_discord_id"])
        roster = fetchall("""
            SELECT * FROM roster
            WHERE team_id = ?
            ORDER BY role_type DESC, discord_id ASC
        """, (team_row["id"],))

        vice_list = []
        player_list = []

        for row in roster:
            member = guild.get_member(row["discord_id"])
            if member is None:
                continue

            if row["role_type"] == "vice_captain":
                vice_list.append(member.mention)
            else:
                player_list.append(member.mention)

        embed = discord.Embed(
            title=f"{team_row['team_name']} - Team Info",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Captain",
            value=captain.mention if captain else "Não encontrado",
            inline=False
        )
        embed.add_field(
            name="Vice Captains",
            value="\n".join(vice_list) if vice_list else "Nenhum",
            inline=False
        )
        embed.add_field(
            name="Roster",
            value="\n".join(player_list) if player_list else "Nenhum",
            inline=False
        )
        embed.set_footer(text="SAVL Team System")

        await interaction.response.send_message(embed=embed)

    @team.command(name="add", description="Solicita a adição de um player ao time")
    @app_commands.choices(role=ROLE_CHOICES)
    async def team_add(self, interaction: discord.Interaction, player: discord.Member, role: app_commands.Choice[str]):
        if not isinstance(interaction.user, discord.Member):
            return

        if not in_transactions_channel(interaction):
            await interaction.response.send_message("Esse comando só pode ser usado no canal de transactions.", ephemeral=True)
            return

        if not can_manage_team(interaction.user):
            await interaction.response.send_message("Apenas captains e vice captains podem usar esse comando.", ephemeral=True)
            return

        team = get_management_team(interaction.user)
        if not team:
            await interaction.response.send_message("Você não está registrado como captain/vice captain de nenhum time.", ephemeral=True)
            return

        if player.bot:
            await interaction.response.send_message("Você não pode adicionar bots.", ephemeral=True)
            return

        existing_team = get_player_current_team(player.id)
        if existing_team:
            await interaction.response.send_message("Esse jogador já está registrado em um time.", ephemeral=True)
            return

        pending = fetchone("""
            SELECT * FROM transfers
            WHERE player_discord_id = ? AND status = 'pending'
        """, (player.id,))
        if pending:
            await interaction.response.send_message("Esse jogador já possui uma transferência pendente.", ephemeral=True)
            return

        profile_data = await get_profile_data_from_member(player)

        transfer_id = execute("""
            INSERT INTO transfers (
                team_id, requester_discord_id, player_discord_id, requested_role_type,
                roblox_username, roblox_user_id, channel_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            team["id"],
            interaction.user.id,
            player.id,
            role.value,
            profile_data["username"],
            profile_data["user_id"],
            interaction.channel_id
        ))

        embed = build_pending_transfer_embed(
            requester=interaction.user,
            player=player,
            team_name=team["team_name"],
            requested_role=role.value,
            avatar_url=profile_data["avatar_url"]
        )

        view = TransferRequestView(self.bot, transfer_id, profile_data["profile_url"])
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(embed=embed, view=view)

        msg = await interaction.original_response()
        execute(
            "UPDATE transfers SET message_id = ? WHERE id = ?",
            (msg.id, transfer_id)
        )

    @team.command(name="remove", description="Remove um jogador do time")
    async def team_remove(self, interaction: discord.Interaction, player: discord.Member):
        if not isinstance(interaction.user, discord.Member):
            return

        if not in_transactions_channel(interaction):
            await interaction.response.send_message("Esse comando só pode ser usado no canal de transactions.", ephemeral=True)
            return

        if not can_manage_team(interaction.user):
            await interaction.response.send_message("Apenas captains e vice captains podem usar esse comando.", ephemeral=True)
            return

        team = get_management_team(interaction.user)
        if not team:
            await interaction.response.send_message("Você não está registrado como captain/vice captain de nenhum time.", ephemeral=True)
            return

        if player.id == team["captain_discord_id"]:
            await interaction.response.send_message("Você não pode remover o capitão do time por esse comando.", ephemeral=True)
            return

        roster_row = fetchone("""
            SELECT * FROM roster
            WHERE team_id = ? AND discord_id = ?
        """, (team["id"], player.id))

        if not roster_row:
            await interaction.response.send_message("Esse jogador não está no seu time.", ephemeral=True)
            return

        execute(
            "DELETE FROM roster WHERE team_id = ? AND discord_id = ?",
            (team["id"], player.id)
        )

        guild = interaction.guild
        if guild is not None:
            roles_to_remove = []

            team_role = guild.get_role(team["team_role_id"])
            vice_role = guild.get_role(config.VICE_CAPTAIN_ROLE_ID)
            player_role = guild.get_role(config.PLAYER_ROLE_ID) if config.PLAYER_ROLE_ID else None

            if team_role:
                roles_to_remove.append(team_role)

            if roster_row["role_type"] == "vice_captain":
                if vice_role:
                    roles_to_remove.append(vice_role)
            else:
                if player_role:
                    roles_to_remove.append(player_role)

            if roles_to_remove:
                await player.remove_roles(*roles_to_remove, reason=f"Released by {interaction.user}")

        embed = build_release_embed(interaction.user, player, team["team_name"])
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(embed=embed)

    @team.command(name="leave", description="Sai do seu próprio time")
    async def team_leave(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return

        if not in_self_transactions_channel(interaction):
            await interaction.response.send_message(
                "Esse comando só pode ser usado no canal de self transactions.",
                ephemeral=True
            )
            return

        # Captain não pode usar
        captain_team = fetchone(
            "SELECT * FROM teams WHERE captain_discord_id = ?",
            (interaction.user.id,)
        )
        if captain_team:
            await interaction.response.send_message(
                "Capitães não podem usar esse comando.",
                ephemeral=True
            )
            return

        # Verifica se o usuário está em algum roster
        roster_row = fetchone("""
            SELECT r.*, t.team_name, t.team_role_id
            FROM roster r
            JOIN teams t ON t.id = r.team_id
            WHERE r.discord_id = ?
        """, (interaction.user.id,))

        if not roster_row:
            await interaction.response.send_message(
                "Você não está registrado em nenhum time.",
                ephemeral=True
            )
            return

        # Remove do banco
        execute(
            "DELETE FROM roster WHERE team_id = ? AND discord_id = ?",
            (roster_row["team_id"], interaction.user.id)
        )

        guild = interaction.guild
        if guild is not None:
            roles_to_remove = []

            team_role = guild.get_role(roster_row["team_role_id"])
            vice_role = guild.get_role(config.VICE_CAPTAIN_ROLE_ID)
            player_role = guild.get_role(config.PLAYER_ROLE_ID) if config.PLAYER_ROLE_ID else None

            if team_role:
                roles_to_remove.append(team_role)

            if roster_row["role_type"] == "vice_captain":
                if vice_role:
                    roles_to_remove.append(vice_role)
            else:
                if player_role:
                    roles_to_remove.append(player_role)

            if roles_to_remove:
                await interaction.user.remove_roles(
                    *roles_to_remove,
                    reason="Player left their own team"
                )

        embed = build_release_embed(
            requester=interaction.user,
            player=interaction.user,
            team_name=roster_row["team_name"]
        )

        await interaction.response.defer(ephemeral=True)
        await interaction.channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))