import asyncio
import hashlib
import logging
import pathlib
import random
import re
import signal
import subprocess
import sys
import types
import typing
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO

import discord
import matplotlib.pyplot as plt
from discord.ext import commands

if __name__ != "__main__":
    from bot import constants

# Import resource management utilities, but only on Unix
LOAD_COG = True

try:
    import resource
    USE_RESOURCE = True
except ModuleNotFoundError:
    if not constants.Client.debug:
        logging.getLogger(__name__).warning(
            "Could not get `resource` for the latex command. The cog will be disabled. "
            "If this is intentional, enable the `DEBUG` flag."
        )

        # Set this flag to prevent the cog from being added when resource is required.
        LOAD_COG = False

    USE_RESOURCE = False

# configure fonts and colors for matplotlib
plt.rcParams.update(
    {
        "font.size": 16,
        "mathtext.fontset": "cm",  # Computer Modern font set
        "mathtext.rm": "serif",
        "figure.facecolor": "36393F",  # matches Discord's dark mode background color
        "text.color": "white",
    }
)

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
    def render(text: str, filepath: pathlib.Path) -> BytesIO:
        """
        Return the rendered image if latex compiles without errors, otherwise raise a BadArgument Exception.

        Saves rendered image to cache.
        """
        fig = plt.figure()
        rendered_image = BytesIO()
        fig.text(0, 1, text, horizontalalignment="left", verticalalignment="top")

        try:
            plt.savefig(rendered_image, bbox_inches="tight", dpi=600)
        except ValueError as e:
            raise commands.BadArgument(str(e))

        rendered_image.seek(0)

        with open(filepath, "wb") as f:
            f.write(rendered_image.getbuffer())

        return rendered_image

    @staticmethod
    def _prepare_input(text: str) -> str:
        text = text.replace(r"\\", "$\n$")  # matplotlib uses \n for newlines, not \\

        if match := FORMATTED_CODE_REGEX.match(text):
            return match.group("code")
        else:
            return text

    @staticmethod
    def bound_render(
        render: typing.Callable[[], BytesIO],
        cpu_limit: int = 5,
        mem_limit: int = 400  # TODO: Figure out why this has to be so high # noqa: Flake please
    ) -> typing.Union[BytesIO, str]:
        """
        Calls Latex._render with safe usage limits.

        `cpu_limit` is the CPU execution time limit in seconds, default 5s.
        `mem_limit` is the memory limit in mb, default 10mb.

        Returns the result of _render, or a string if the process failed.
        """
        # Convert to bytes
        mem_limit *= 1E6

        class CPUError(Exception):
            pass

        # CPU limit error handler
        def cpu_handler(_signum: signal.Signals, _frame: typing.Optional[types.FrameType]) -> None:
            raise CPUError()
        signal.signal(signal.SIGXCPU, cpu_handler)

        # Ensure the hard limit will not exceed the current one.
        current_cpu = resource.getrlimit(resource.RLIMIT_CPU)
        current_mem = resource.getrlimit(resource.RLIMIT_AS)

        if current_cpu[1] != -1 and cpu_limit > current_cpu[1]:
            cpu_limit = current_cpu[1]
        if current_mem[1] != -1 and mem_limit > current_mem[1]:
            mem_limit = current_mem[1]

        # Update the limits
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, current_cpu[1]))
        resource.setrlimit(resource.RLIMIT_AS, (int(mem_limit), current_mem[1]))

        try:
            return render()
        except MemoryError:
            return "Your input exceeded the allowed memory limit."
        except CPUError:
            return "Your input exceeded the allowed CPU limit."

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

            if USE_RESOURCE:
                # Handle cases where the resource library is available
                process = subprocess.Popen(["python", __file__, text, image_path], stdout=subprocess.PIPE)
                while process.poll() is None:
                    await asyncio.sleep(2)

                if process.returncode != 0:
                    # The helper did not exit successfully.
                    embed = discord.Embed(
                        title=random.choice(constants.ERROR_REPLIES),
                        color=constants.Colours.soft_red,
                        description=process.stdout.read().decode()
                    )

                    await ctx.send(embed=embed)
                    return

                await ctx.send(file=discord.File(image_path, "latex.png"))

            else:
                # Handle cases where the resource library is not available
                with ThreadPoolExecutor() as pool:
                    result = await asyncio.get_running_loop().run_in_executor(pool, Latex.render, text, image_path)
                await ctx.send(file=discord.File(result, "latex.png"))


def setup(bot: commands.Bot) -> None:
    """Load the Latex Cog."""
    # Disable the cog if the resource library is not available, and the debug flag is not set.
    if LOAD_COG:
        bot.add_cog(Latex(bot))


if __name__ == "__main__":
    _text = sys.argv[1]
    _image_path = pathlib.Path(sys.argv[2])
    _function = partial(Latex.render, _text, _image_path)

    try:
        _result = Latex.bound_render(_function)

        if isinstance(_result, str):
            # If a resource limit was hit, let the parent process know
            sys.stdout.write(_result)
            exit(1)

        # Normal exit
        exit(0)

    except Exception as e:
        # Unhandled exception
        # TODO: Parse this error better # noqa: Why
        sys.stdout.write(e)
        exit(2)
