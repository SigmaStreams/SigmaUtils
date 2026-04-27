import discord
from discord import app_commands

from ..config import ALLOWED_USER_IDS
from ..helpers import NO_PINGS
from .. import move_request_panel
from ..views import CheckStatusPanelView


PANEL_TYPE_CHECK_STATUS = "check_status"
PANEL_TYPE_MOVE_SERVER = "move_server"


def _panel_choices() -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name="Purge status check", value=PANEL_TYPE_CHECK_STATUS),
        app_commands.Choice(name="Move server request", value=PANEL_TYPE_MOVE_SERVER),
    ]


async def _post_check_status_panel(channel: discord.TextChannel, guild: discord.Guild) -> discord.Message:
    embed = discord.Embed(
        title="Purge Status Check",
        description=(
            "Click **Check my status** to privately see if you’re at risk of being purged.\n"
            "If something looks wrong, use **Open a ticket** to contact staff."
        ),
    )

    return await channel.send(
        embed=embed,
        view=CheckStatusPanelView(guild_id=guild.id),
        allowed_mentions=NO_PINGS,
    )


async def _post_move_server_panel(channel: discord.TextChannel, guild: discord.Guild) -> discord.Message:
    embed = discord.Embed(
        title=move_request_panel.PANEL_TITLE,
        description=move_request_panel.PANEL_BODY,
        color=move_request_panel.PANEL_COLOR,
    )

    return await channel.send(
        embed=embed,
        view=move_request_panel.MovePanelView(guild.id),
        allowed_mentions=NO_PINGS,
    )


def setup(bot):
    @bot.tree.command(
        name="panel",
        description="Staff-only: post a selected panel in a text channel.",
    )
    @app_commands.describe(
        panel_type="Which panel to post.",
        channel="Channel to post the panel in (defaults to current channel).",
    )
    @app_commands.choices(panel_type=_panel_choices())
    async def panel(
        interaction: discord.Interaction,
        panel_type: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
    ):
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Run this in a server, not DMs.", ephemeral=True)
            return

        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("Pick a text channel to post the panel in.", ephemeral=True)
            return

        try:
            if panel_type.value == PANEL_TYPE_CHECK_STATUS:
                msg = await _post_check_status_panel(target, guild)
            elif panel_type.value == PANEL_TYPE_MOVE_SERVER:
                msg = await _post_move_server_panel(target, guild)
            else:
                await interaction.response.send_message("Unknown panel type.", ephemeral=True)
                return
        except discord.Forbidden:
            await interaction.response.send_message("I can’t post in that channel (missing perms).", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message("Failed to post the panel (Discord API error).", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Posted {panel_type.name.lower()} panel: {msg.jump_url}",
            ephemeral=True,
            allowed_mentions=NO_PINGS,
        )
