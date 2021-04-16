import asyncio
import hashlib
import logging
import pathlib
import random
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

import discord
from discord.ext import commands

from bot import constants
from bot.utils import latex

FORMATTED_CODE_REGEX = re.compile(
    r"(?P<delim>(?P<block>```)|``?)"        # code delimiter: 1-3 backticks; (?P=block) only matches if it's a block
    r"(?(block)(?:(?P<lang>[a-z]+)\n)?)"    # if we're in a block, match optional language (only letters plus newline)
    r"(?:[ \t]*\n)*"                        # any blank (empty or tabs/spaces only) lines before the code
    r"(?P<code>.*?)"                        # extract all code inside the markup
    r"\s*"                                  # any more whitespace before the end of the code markup
    r"(?P=delim)",                          # match the exact same delimiter from the start again
    re.DOTALL | re.IGNORECASE,              # "." also matches newlines, case insensitive
)

CACHE_DIRECTORY = pathlib.Path("_latex_cache")
CACHE_DIRECTORY.mkdir(exist_ok=True)


class Latex(commands.Cog):
    """Renders latex."""

    @staticmethod
    def _prepare_input(text: str) -> str:
        text = text.replace(r"\\", "$\n$")  # matplotlib uses \n for newlines, not \\

        if match := FORMATTED_CODE_REGEX.match(text):
            return match.group("code")
        else:
            return text

    @staticmethod
    def make_error_embed(text: str) -> discord.Embed:
        """Make a generic error embed, with a random title from the error replies, and the description `text`."""
        return discord.Embed(
            title=random.choice(constants.ERROR_REPLIES),
            color=constants.Colours.soft_red,
            description=text
        )

    @commands.command()
    @commands.max_concurrency(1, commands.BucketType.guild, wait=True)
    async def latex(self, ctx: commands.Context, *, text: str) -> None:
        """Renders the text in latex and sends the image."""
        text = self._prepare_input(text)
        query_hash = hashlib.md5(text.encode()).hexdigest()
        image_path = CACHE_DIRECTORY.joinpath(f"{query_hash}.png")
        async with ctx.typing():
            if image_path.exists():
                await ctx.send(file=discord.File(image_path))
                return

            if latex.USE_RESOURCE:
                # Handle cases where the resource library is available
                process = subprocess.Popen(["python", latex.__file__, text, image_path], stdout=subprocess.PIPE)
                while process.poll() is None:
                    await asyncio.sleep(2)

                if process.returncode == 1:
                    # The helper did not exit successfully.
                    await ctx.send(embed=Latex.make_error_embed(process.stdout.read().decode()))
                    return
                elif process.returncode == 2:
                    # Unknown exception
                    raise Exception(process.stdout.read().decode())

                await ctx.send(file=discord.File(image_path, "latex.png"))

            else:
                # Handle cases where the resource library is not available
                with ThreadPoolExecutor() as pool:
                    try:
                        result = await asyncio.get_running_loop().run_in_executor(
                            pool, latex.render, text, image_path
                        )
                    except ValueError as e:
                        await ctx.send(embed=Latex.make_error_embed(str(e)))
                await ctx.send(file=discord.File(result, "latex.png"))


def setup(bot: commands.Bot) -> None:
    """Load the Latex Cog."""
    # Disable the cog if the resource library is not available, and the debug flag is not set.
    if latex.USE_RESOURCE or constants.Client.debug:
        bot.add_cog(Latex(bot))
    else:
        logging.getLogger(__name__).warning(
            "Could not get `resource` for the latex command. The cog will be disabled. "
            "If this is intentional, enable the `DEBUG` flag."
        )
