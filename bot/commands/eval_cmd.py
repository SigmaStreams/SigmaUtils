import asyncio
import contextlib
import io
import textwrap
import traceback

import discord
from discord.ext import commands


def _cleanup_code(content: str) -> str:
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        return "\n".join(lines[1:-1])
    return content.strip("` \n")


def _format_output(text: str) -> str:
    if not text:
        text = "<no output>"

    if len(text) > 1900:
        text = text[:1900] + "\n..."

    return f"```py\n{text}\n```"


def setup(bot):
    @bot.command(name="eval", hidden=True)
    @commands.is_owner()
    async def eval_command(ctx: commands.Context, *, code: str):
        env = {
            "asyncio": asyncio,
            "bot": bot,
            "ctx": ctx,
            "discord": discord,
            "commands": commands,
            "__import__": __import__,
        }
        env.update(globals())

        body = _cleanup_code(code)
        stdout = io.StringIO()
        wrapped = "async def __eval_fn__():\n" + textwrap.indent(body, "    ")

        try:
            exec(wrapped, env)
        except Exception:
            await ctx.send(_format_output(traceback.format_exc()))
            return

        func = env["__eval_fn__"]

        try:
            with contextlib.redirect_stdout(stdout):
                result = await func()
        except Exception:
            output = stdout.getvalue()
            await ctx.send(_format_output(f"{output}{traceback.format_exc()}"))
            return

        output = stdout.getvalue()
        if result is not None:
            output = f"{output}{result}"

        await ctx.send(_format_output(output))

    @eval_command.error
    async def eval_command_error(ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.NotOwner):
            await ctx.send("You are not authorized to use this command.")
            return
        raise error
