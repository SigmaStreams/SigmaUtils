import discord

from ..config import ALLOWED_USER_IDS
from ..helpers import NO_PINGS, send_audit_embed


PENDING_ROLE_ID = 1469116711612583946


def setup(bot):
    @bot.tree.command(
        name="remove_all_pending",
        description="Staff-only: remove the Pending role from everyone who has it.",
    )
    async def remove_all_pending(interaction: discord.Interaction):
        if interaction.user.id not in ALLOWED_USER_IDS:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Run this in a server, not DMs.", ephemeral=True)
            return

        me = guild.me
        if me is None:
            await interaction.response.send_message("Can't resolve bot member in this guild.", ephemeral=True)
            return

        role = guild.get_role(PENDING_ROLE_ID)
        if role is None:
            await interaction.response.send_message(
                f"I couldn't find the Pending role ({PENDING_ROLE_ID}) in this server.",
                ephemeral=True,
            )
            return

        if not me.guild_permissions.manage_roles:
            await interaction.response.send_message("I don't have Manage Roles permission.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        removed = 0
        failed: list[str] = []

        members = list(role.members)
        if not members:
            await interaction.followup.send("No one currently has the Pending role.", ephemeral=True, allowed_mentions=NO_PINGS)
            return

        for member in members:
            try:
                await member.remove_roles(role, reason=f"Bulk Pending removal by {interaction.user} ({interaction.user.id})")
                removed += 1
            except discord.Forbidden:
                failed.append(f"{member} ({member.id}) — forbidden")
            except discord.HTTPException as e:
                failed.append(f"{member} ({member.id}) — http error: {e.status}")

        embed = discord.Embed(
            title="Pending role cleanup complete",
            description=(
                f"Role: <@&{PENDING_ROLE_ID}> (`{PENDING_ROLE_ID}`)\n"
                f"Removed from: **{removed}** member(s)\n"
                f"Failures: **{len(failed)}**"
            ),
        )

        if failed:
            snippet = "\n".join(f"• {x}" for x in failed[:10])
            if len(failed) > 10:
                snippet += f"\n… and {len(failed) - 10} more"
            embed.add_field(name="Failures (top 10)", value=snippet[:1024], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=NO_PINGS)

        audit = discord.Embed(
            title="Pending role cleanup run",
            description=(
                f"Invoker: {interaction.user} ({interaction.user.id})\n"
                f"Role: <@&{PENDING_ROLE_ID}> (`{PENDING_ROLE_ID}`)\n"
                f"Removed from: {removed}\n"
                f"Failures: {len(failed)}"
            ),
        )
        await send_audit_embed(guild, audit)
