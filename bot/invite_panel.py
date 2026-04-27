import discord

from .helpers import NO_PINGS
from .commands import invite as invite_command


PANEL_TITLE = "Need A Server Invite?"
PANEL_BODY = (
    "Use the button below to generate your personal invite.\n\n"
    "You may only have **one active invite** at a time. If you already have one, the bot will reuse it instead of creating a new link.\n\n"
    "Each invite lasts for **24 hours** and can be used as many times as needed while it is active."
)
PANEL_COLOR = 0x6CC5B0


class InvitePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Get Invite",
        style=discord.ButtonStyle.success,
        custom_id="invite_panel:get_invite",
    )
    async def get_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await invite_command.run_invite_flow(interaction, reason_prefix="invite panel")


async def post_invite_panel(channel: discord.TextChannel) -> discord.Message:
    embed = discord.Embed(
        title=PANEL_TITLE,
        description=PANEL_BODY,
        color=PANEL_COLOR,
    )
    embed.add_field(
        name="What this does",
        value=(
            "- Creates your invite if you don’t already have one\n"
            "- Reuses your current active invite if one already exists\n"
            "- Sends the link privately so it doesn’t clutter the channel"
        ),
        inline=False,
    )
    embed.set_footer(text="The button replies ephemerally with your invite link.")

    return await channel.send(
        embed=embed,
        view=InvitePanelView(),
        allowed_mentions=NO_PINGS,
    )