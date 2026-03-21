import datetime as dt

import discord
from discord import app_commands

from ..config import ALLOWED_USER_IDS
from ..helpers import NO_PINGS

USER_PINGS_ONLY = discord.AllowedMentions(users=True, roles=False, everyone=False)

CREDS_FALLBACK_CHANNEL_ID = 1457844377010307114

ACCEPTED_EXPIRY_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%b %d %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
]

ACCEPTED_EXPIRY_HELP = (
    "Expiry must be a date. Accepted formats:\n"
    "- YYYY-MM-DD (recommended)\n"
    "- YYYY/MM/DD\n"
    "- YYYY.MM.DD\n"
    "- MM/DD/YYYY\n"
    "- MM-DD-YYYY\n"
    "- Mar 1 2026 / March 1 2026 / 1 Mar 2026\n\n"
    "Tip: Use YYYY-MM-DD to avoid ambiguity."
)


def parse_expiry(expiry_str: str) -> dt.date | None:
    s = expiry_str.strip()
    for fmt in ACCEPTED_EXPIRY_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


async def _get_fallback_channel(guild: discord.Guild) -> discord.TextChannel | None:
    ch = guild.get_channel(CREDS_FALLBACK_CHANNEL_ID)
    if isinstance(ch, discord.TextChannel):
        return ch
    try:
        fetched = await guild.fetch_channel(CREDS_FALLBACK_CHANNEL_ID)
        return fetched if isinstance(fetched, discord.TextChannel) else None
    except Exception:
        return None


def _build_extend_dm(expiry_iso: str) -> str:
    return (
        "Your subscription expiry has been updated.\n\n"
        f"New expiration date: **{expiry_iso}**"
    )


def _build_extend_fallback(user: discord.Member, expiry_iso: str) -> str:
    return (
        f"{user.mention} Your subscription expiry has been updated.\n\n"
        f"New expiration date: **{expiry_iso}**"
    )


def setup(bot):
    @bot.tree.command(
        name="extend_creds",
        description="Staff-only: DM a user their updated expiration date.",
    )
    @app_commands.describe(
        user="The member to notify",
        expiry="New expiration date (e.g. 2026-03-01, 03/01/2026, Mar 1 2026)",
    )
    async def extend_creds(
        interaction: discord.Interaction,
        user: discord.Member,
        expiry: str,
    ):
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Run this in a server, not DMs.", ephemeral=True)
            return

        parsed_expiry = parse_expiry(expiry)
        if parsed_expiry is None:
            await interaction.response.send_message(ACCEPTED_EXPIRY_HELP, ephemeral=True)
            return

        if parsed_expiry < dt.date.today():
            await interaction.response.send_message("Expiry date cannot be in the past.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        normalized_expiry = parsed_expiry.isoformat()
        dm_text = _build_extend_dm(normalized_expiry)

        dm_ok = True
        dm_error = None
        fallback_ok = False
        fallback_error = None

        try:
            await user.send(dm_text, allowed_mentions=NO_PINGS)
        except discord.Forbidden:
            dm_ok = False
            dm_error = "DMs are closed / blocked."
        except Exception as e:
            dm_ok = False
            dm_error = f"DM failed: {type(e).__name__}"

        if not dm_ok:
            fallback_channel = await _get_fallback_channel(guild)
            if fallback_channel is None:
                fallback_error = f"Fallback channel `{CREDS_FALLBACK_CHANNEL_ID}` not found."
            else:
                try:
                    await fallback_channel.send(
                        _build_extend_fallback(user, normalized_expiry),
                        allowed_mentions=USER_PINGS_ONLY,
                    )
                    fallback_ok = True
                except discord.Forbidden:
                    fallback_error = "Missing permission to post in the fallback channel."
                except Exception as e:
                    fallback_error = f"Fallback failed: {type(e).__name__}"

        if dm_ok:
            msg = "Expiration update sent by DM."
        elif fallback_ok:
            msg = "DM failed, so I posted the updated expiration date in the fallback channel."
        else:
            msg = "DM failed, and the fallback channel message also failed."

        if dm_error:
            msg += f"\nDM error: {dm_error}"
        if fallback_error:
            msg += f"\nFallback error: {fallback_error}"

        await interaction.followup.send(msg, ephemeral=True, allowed_mentions=NO_PINGS)
