import datetime as dt

import discord
from discord import app_commands

from ..config import ALLOWED_USER_IDS
from ..helpers import NO_PINGS, send_audit_embed
from ..invite_tracking import snapshot_invites_to_db
from ..db import connect


# Always create invites to this "landing" channel
INVITE_TARGET_CHANNEL_ID = 1457896130653458542

DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60  # 24h
DEFAULT_MAX_USES = 0  # 0 = unlimited uses


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


async def _get_target_channel(guild: discord.Guild) -> discord.abc.GuildChannel | None:
    ch = guild.get_channel(INVITE_TARGET_CHANNEL_ID)
    if ch is None:
        try:
            ch = await guild.fetch_channel(INVITE_TARGET_CHANNEL_ID)
        except Exception:
            return None
    if isinstance(ch, discord.abc.GuildChannel):
        return ch
    return None


def _invite_is_active(inv: discord.Invite) -> bool:
    # Deleted/revoked invites won't appear in guild.invites(), so this helper
    # only needs to validate age/uses for currently existing invites.
    if inv.max_uses and (inv.uses or 0) >= inv.max_uses:
        return False

    if inv.max_age and inv.created_at:
        created = inv.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        expires_at = created + dt.timedelta(seconds=inv.max_age)
        if _now() >= expires_at:
            return False

    return True


def _invite_expires_at(inv: discord.Invite) -> dt.datetime | None:
    if not inv.max_age or not inv.created_at:
        return None
    created = inv.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=dt.timezone.utc)
    return created + dt.timedelta(seconds=inv.max_age)


async def _find_existing_active_invite(guild: discord.Guild, owner_id: int) -> discord.Invite | None:
    """
    Return the owner's current active invite if one exists.
    We treat inviter_id in invite_baseline as the effective owner of the invite.
    """
    try:
        invites = await guild.invites()
    except Exception:
        return None

    live_by_code = {inv.code: inv for inv in invites}

    async with connect() as db:
        rows = await db.execute_fetchall(
            """
            SELECT code, created_at, updated_at
            FROM invite_baseline
            WHERE guild_id = ? AND inviter_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (guild.id, owner_id),
        )

    for code, _, _ in rows:
        inv = live_by_code.get(code)
        if inv is None:
            continue
        if not _invite_is_active(inv):
            continue
        return inv

    return None


async def _store_invite_owner(*, guild_id: int, code: str, owner_id: int, created_at: str | None, uses: int) -> None:
    now = _now_iso()
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO invite_baseline (guild_id, code, uses, inviter_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, code) DO UPDATE SET
              uses=excluded.uses,
              inviter_id=excluded.inviter_id,
              created_at=COALESCE(invite_baseline.created_at, excluded.created_at),
              updated_at=excluded.updated_at
            """,
            (guild_id, code, uses, owner_id, created_at, now),
        )
        await db.commit()


async def _maybe_dm_on_behalf_recipient(
    *,
    recipient: discord.Member,
    requester: discord.abc.User,
    invite_url: str,
    expires_at: dt.datetime | None,
    reused_existing: bool,
) -> str:
    """
    Returns: 'sent' | 'failed'
    """
    try:
        if expires_at is not None:
            expiry_text = f"It expires <t:{int(expires_at.timestamp())}:R>."
        else:
            expiry_text = "It does not have a set expiration."

        intro = (
            f"You’re receiving this message because **{requester}** requested a Discord invite on your behalf.\n\n"
        )

        if reused_existing:
            body = (
                "You already had an active invite, so I’m sending you your current link again.\n\n"
                f"{expiry_text}\n\n"
                f"Invite link:\n{invite_url}"
            )
        else:
            body = (
                "A new invite was created for you.\n\n"
                f"{expiry_text}\n\n"
                f"Invite link:\n{invite_url}"
            )

        await recipient.send(intro + body, allowed_mentions=NO_PINGS)
        return "sent"
    except Exception:
        return "failed"


async def run_invite_flow(
    interaction: discord.Interaction,
    user: discord.Member | None = None,
    *,
    reason_prefix: str = "/invite",
) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("Run this in a server, not DMs.", ephemeral=True)
        return

    me = guild.me
    if me is None:
        await interaction.response.send_message("Can't resolve bot member in this guild.", ephemeral=True)
        return

    owner = interaction.user
    if user is not None:
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message(
                "You are not authorized to create invites on behalf of another user.",
                ephemeral=True,
            )
            return
        owner = user

    target = await _get_target_channel(guild)
    if target is None:
        await interaction.response.send_message(
            f"I can't find the invite target channel `{INVITE_TARGET_CHANNEL_ID}` in this server.",
            ephemeral=True,
        )
        return

    if not target.permissions_for(me).create_instant_invite:
        await interaction.response.send_message(
            f"I don’t have permission to create invites in <#{INVITE_TARGET_CHANNEL_ID}>.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        await snapshot_invites_to_db(guild)
    except Exception:
        pass

    existing_inv = await _find_existing_active_invite(guild, owner.id)
    dm_status = None

    if existing_inv is not None:
        expires_at = _invite_expires_at(existing_inv)

        if owner.id != interaction.user.id:
            dm_status = await _maybe_dm_on_behalf_recipient(
                recipient=owner,
                requester=interaction.user,
                invite_url=existing_inv.url,
                expires_at=expires_at,
                reused_existing=True,
            )

        if owner.id == interaction.user.id:
            if expires_at is not None:
                msg = (
                    "You already have an active invite. Only one active invite is allowed at a time.\n\n"
                    f"Your current invite (goes to <#{INVITE_TARGET_CHANNEL_ID}>, expires <t:{int(expires_at.timestamp())}:R>):\n"
                    f"{existing_inv.url}"
                )
            else:
                msg = (
                    "You already have an active invite. Only one active invite is allowed at a time.\n\n"
                    f"Your current invite (goes to <#{INVITE_TARGET_CHANNEL_ID}>):\n"
                    f"{existing_inv.url}"
                )
        else:
            if expires_at is not None:
                msg = (
                    f"{owner.mention} already has an active invite, so I didn’t create a new one.\n\n"
                    f"Current invite (goes to <#{INVITE_TARGET_CHANNEL_ID}>, expires <t:{int(expires_at.timestamp())}:R>):\n"
                    f"{existing_inv.url}"
                )
            else:
                msg = (
                    f"{owner.mention} already has an active invite, so I didn’t create a new one.\n\n"
                    f"Current invite (goes to <#{INVITE_TARGET_CHANNEL_ID}>):\n"
                    f"{existing_inv.url}"
                )

            if dm_status == "sent":
                msg += f"\n\nI also DMed {owner.mention} so they know why they received this invite."
            elif dm_status == "failed":
                msg += f"\n\nI couldn’t DM {owner.mention} (their DMs may be closed, or they may have the bot blocked)."

        await interaction.followup.send(
            msg,
            ephemeral=True,
            allowed_mentions=NO_PINGS,
        )

        if owner.id == interaction.user.id:
            desc = (
                f"Owner: {owner} ({owner.id})\n"
                f"Target channel: <#{INVITE_TARGET_CHANNEL_ID}> ({INVITE_TARGET_CHANNEL_ID})\n"
                f"Existing code reused: `{existing_inv.code}`\n"
                f"Expires: {f'<t:{int(expires_at.timestamp())}:R>' if expires_at else 'no expiry'}"
            )
        else:
            desc = (
                f"Requested by: {interaction.user} ({interaction.user.id})\n"
                f"Owner: {owner} ({owner.id})\n"
                f"Target channel: <#{INVITE_TARGET_CHANNEL_ID}> ({INVITE_TARGET_CHANNEL_ID})\n"
                f"Existing code reused: `{existing_inv.code}`\n"
                f"Expires: {f'<t:{int(expires_at.timestamp())}:R>' if expires_at else 'no expiry'}\n"
                f"Recipient DM: {dm_status or 'not attempted'}"
            )

        embed = discord.Embed(
            title="Invite reused",
            description=desc,
        )
        await send_audit_embed(guild, embed)
        return

    try:
        reason = (
            f"Invite created via {reason_prefix} by {interaction.user} ({interaction.user.id})"
            if owner.id == interaction.user.id
            else f"Invite created via {reason_prefix} by {interaction.user} ({interaction.user.id}) on behalf of {owner} ({owner.id})"
        )

        inv = await target.create_invite(
            max_age=DEFAULT_MAX_AGE_SECONDS,
            max_uses=DEFAULT_MAX_USES,
            unique=True,
            reason=reason,
        )
    except discord.Forbidden:
        await interaction.followup.send("Invite creation failed (missing permissions).", ephemeral=True)
        return
    except discord.HTTPException:
        await interaction.followup.send("Invite creation failed (Discord API error). Try again.", ephemeral=True)
        return

    try:
        await snapshot_invites_to_db(guild)
    except Exception:
        pass

    try:
        created_at = inv.created_at.isoformat() if inv.created_at else None
        uses = inv.uses or 0
        await _store_invite_owner(
            guild_id=guild.id,
            code=inv.code,
            owner_id=owner.id,
            created_at=created_at,
            uses=uses,
        )
    except Exception:
        pass

    expires_at = _now() + dt.timedelta(seconds=DEFAULT_MAX_AGE_SECONDS)

    if owner.id != interaction.user.id:
        dm_status = await _maybe_dm_on_behalf_recipient(
            recipient=owner,
            requester=interaction.user,
            invite_url=inv.url,
            expires_at=expires_at,
            reused_existing=False,
        )

    if owner.id == interaction.user.id:
        msg = (
            f"Here’s your invite link (goes to <#{INVITE_TARGET_CHANNEL_ID}>, expires <t:{int(expires_at.timestamp())}:R>):\n"
            f"{inv.url}"
        )
    else:
        msg = (
            f"Here’s an invite link for {owner.mention} "
            f"(goes to <#{INVITE_TARGET_CHANNEL_ID}>, expires <t:{int(expires_at.timestamp())}:R>):\n"
            f"{inv.url}"
        )
        if dm_status == "sent":
            msg += f"\n\nI also DMed {owner.mention} to let them know why they received this invite."
        elif dm_status == "failed":
            msg += (
                f"\n\nI couldn’t DM {owner.mention} "
                f"(their DMs may be closed, or they may have the bot blocked)."
            )

    await interaction.followup.send(
        msg,
        ephemeral=True,
        allowed_mentions=NO_PINGS,
    )

    if owner.id == interaction.user.id:
        desc = (
            f"Owner: {owner} ({owner.id})\n"
            f"Target channel: <#{INVITE_TARGET_CHANNEL_ID}> ({INVITE_TARGET_CHANNEL_ID})\n"
            f"Code: `{inv.code}`\n"
            f"Max age: {DEFAULT_MAX_AGE_SECONDS}s\n"
            f"Max uses: unlimited\n"
            f"Expires: <t:{int(expires_at.timestamp())}:R>"
        )
    else:
        desc = (
            f"Requested by: {interaction.user} ({interaction.user.id})\n"
            f"Owner: {owner} ({owner.id})\n"
            f"Target channel: <#{INVITE_TARGET_CHANNEL_ID}> ({INVITE_TARGET_CHANNEL_ID})\n"
            f"Code: `{inv.code}`\n"
            f"Max age: {DEFAULT_MAX_AGE_SECONDS}s\n"
            f"Max uses: unlimited\n"
            f"Expires: <t:{int(expires_at.timestamp())}:R>\n"
            f"Recipient DM: {dm_status or 'not attempted'}"
        )

    embed = discord.Embed(
        title="Invite created",
        description=desc,
    )
    await send_audit_embed(guild, embed)


def setup(bot):
    @bot.tree.command(
        name="invite",
        description="Create a 24h invite (unlimited uses) to the public landing channel.",
    )
    @app_commands.describe(
        user="Optional: create the invite on behalf of another user (staff only).",
    )
    async def invite(interaction: discord.Interaction, user: discord.Member | None = None):
        await run_invite_flow(interaction, user, reason_prefix="/invite")
