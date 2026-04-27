import discord

from .helpers import NO_PINGS
from .commands import move_server


PANEL_TITLE = "Move Server Requests"
PANEL_BODY = (
    "Use the button below to request a server move.\n\n"
    "You might want to move servers due to timezone differences, viewing habits, "
    "or when you’re most active on Plex.\n\n"
    "Switching servers can help ensure scheduled maintenance windows don’t overlap "
    "with the times you usually watch content.\n\n"
    "You’ll pick your destination, then submit your email + reason.\n\n"
    "If you don’t receive a DM after staff handles it, check <#1458533908701380719> "
    "and/or open a ticket."
)

PANEL_COLOR = 0xA9C9FF
MAINTENANCE_WINDOWS_CHANNEL_ID = 1468495607801974887


async def _start_move_flow(interaction: discord.Interaction) -> None:
    """Same behavior as running /move_server."""
    guild = interaction.guild
    user = interaction.user

    if guild is None or not isinstance(user, discord.Member):
        await interaction.response.send_message("Run this in a server.", ephemeral=True)
        return

    on_cd, remaining = move_server._check_cooldown(user.id)  # type: ignore
    if on_cd:
        mins = max(1, remaining // 60)
        await interaction.response.send_message(
            f"You can submit another request in {mins} minute(s).",
            ephemeral=True,
        )
        return

    current_role_id = move_server._get_current_server_role(user)  # type: ignore
    if current_role_id is None:
        allowed = "\n".join(f"- {name}" for name in move_server.SERVER_ROLES.values())  # type: ignore
        await interaction.response.send_message(
            "You must have exactly one server role to use this:\n" + allowed,
            ephemeral=True,
        )
        return

    raw_dest_ids = move_server._allowed_destinations(current_role_id)  # type: ignore
    dest_ids = await move_server._filter_open_destinations(guild.id, raw_dest_ids)  # type: ignore
    if not dest_ids:
        await interaction.response.send_message("No destinations available.", ephemeral=True)
        return

    source_channel_id = interaction.channel.id if interaction.channel else 0
    from_name = move_server.SERVER_ROLES.get(current_role_id, str(current_role_id))  # type: ignore

    view = move_server.MoveServerDestinationView(  # type: ignore
        author_id=user.id,
        source_channel_id=source_channel_id,
        from_role_id=current_role_id,
        destination_role_ids=dest_ids,
    )

    await interaction.response.send_message(
        content=f"Current server: **{from_name}**\nPick where you want to move to:",
        view=view,
        ephemeral=True,
        allowed_mentions=NO_PINGS,
    )


class MovePanelView(discord.ui.View):
    """
    Persistent view so the button keeps working after restarts.
    Requirements:
      - timeout=None
      - custom_id on non-link buttons
    """

    def __init__(self, guild_id: int | None = None):
        super().__init__(timeout=None)

        if guild_id is not None:
            maintenance_url = f"https://discord.com/channels/{guild_id}/{MAINTENANCE_WINDOWS_CHANNEL_ID}"
            self.add_item(
                discord.ui.Button(
                    label="View Maintenance Windows",
                    style=discord.ButtonStyle.link,
                    url=maintenance_url,
                )
            )

    @discord.ui.button(
        label="Request a server move",
        style=discord.ButtonStyle.primary,
        custom_id="move_panel:open",
    )
    async def open_move(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _start_move_flow(interaction)