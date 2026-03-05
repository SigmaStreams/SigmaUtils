import datetime as dt

import discord
from discord import app_commands

from ..config import ALLOWED_USER_IDS
from ..helpers import NO_PINGS, send_audit_embed


# Cooldown per staff member
SILENT_PING_COOLDOWN_SECONDS = 20

# staff_id -> last used timestamp
_LAST_USED: dict[int, dt.datetime] = {}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _check_cd(staff_id: int) -> tuple[bool, int]:
    last = _LAST_USED.get(staff_id)
    if not last:
        return False, 0
    elapsed = (_now() - last).total_seconds()
    if elapsed >= SILENT_PING_COOLDOWN_SECONDS:
        return False, 0
    return True, int(SILENT_PING_COOLDOWN_SECONDS - elapsed)


def _mark_used(staff_id: int) -> None:
    _LAST_USED[staff_id] = _now()


def setup(bot):
    @bot.tree.command(
        name="silent_ping",
        description="Staff-only: ping a user then delete the ping message.",
    )
    @app_commands.describe(
        user="User to ping.",
        channel="Channel to ping in (defaults to current channel).",
        delete_after="Seconds before deleting the ping message (default: 2).",
        reason="Optional staff-only reason (logged to audit).",
    )
    async def silent_ping(
        interaction: discord.Interaction,
        user: discord.Member,
        channel: discord.TextChannel | None = None,
        delete_after: app_commands.Range[int, 1, 30] | None = 2,
        reason: str | None = None,
    ):
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Run this in a server.", ephemeral=True)
            return

        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("Pick a text channel.", ephemeral=True)
            return

        on_cd, remaining = _check_cd(interaction.user.id)
        if on_cd:
            await interaction.response.send_message(
                f"Cooldown: try again in {remaining}s.",
                ephemeral=True,
            )
            return

        _mark_used(interaction.user.id)

        # Send the ping (only allow user mentions)
        try:
            ping_msg = await target.send(
                content=user.mention,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.Forbidden:
            await interaction.response.send_message("I can’t post in that channel (missing perms).", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message("Failed to send ping (Discord API error).", ephemeral=True)
            return

        # Acknowledge to staff immediately
        try:
            await interaction.response.send_message(
                f"Pinged {user.mention} in {target.mention} and will delete it in {delete_after or 2}s.",
                ephemeral=True,
                allowed_mentions=NO_PINGS,
            )
        except Exception:
            # If something weird happens, don't block deletion.
            pass

        # Delete after delay (needs Manage Messages in that channel)
        try:
            await ping_msg.delete(delay=int(delete_after or 2))
        except Exception:
            # If we can't delete, just leave it; staff already got confirmation.
            pass

        # Optional audit log
        try:
            audit = discord.Embed(
                title="Silent ping",
                description=(
                    f"Staff: {interaction.user} ({interaction.user.id})\n"
                    f"Target: {user} ({user.id})\n"
                    f"Channel: {target.mention}\n"
                    f"Delete after: {int(delete_after or 2)}s\n"
                    f"Reason: {reason.strip() if reason else '—'}"
                ),
            )
            await send_audit_embed(guild, audit)
        except Exception:
            pass
