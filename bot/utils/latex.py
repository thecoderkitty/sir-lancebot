import pathlib
import signal
import sys
import types
import typing
from functools import partial
from io import BytesIO

import matplotlib
import matplotlib.pyplot as plt

# Import resource management utilities, but only on Unix
USE_RESOURCE = True
try:
    import resource
except ModuleNotFoundError:
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


def render(text: str, filepath: pathlib.Path) -> BytesIO:
    """
    Return the rendered image if latex compiles without errors, otherwise raise a BadArgument Exception.

    Saves rendered image to cache.
    """
    matplotlib.use("agg")
    fig = plt.figure()
    rendered_image = BytesIO()
    fig.text(0, 1, text, horizontalalignment="left", verticalalignment="top")

    plt.savefig(rendered_image, bbox_inches="tight", dpi=600)

    rendered_image.seek(0)

    with open(filepath, "wb") as f:
        f.write(rendered_image.getbuffer())

    return rendered_image


def bound_render(
    renderer: typing.Callable[[], BytesIO],
    cpu_limit: int = 5,
    mem_limit: int = 10
) -> typing.Union[BytesIO, str]:
    """
    Calls Latex._render with safe usage limits.

    `cpu_limit` is the CPU execution time limit in seconds, default 5s.
    `mem_limit` is the memory limit in mb, default 10mb.

    Returns the result of _render, or a string if the process failed.
    """
    # Convert to bytes
    mem_limit *= 1_000_000

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
        return renderer()
    except MemoryError:
        return "Your input exceeded the allowed memory limit."
    except CPUError:
        return "Your input exceeded the allowed CPU limit."


if __name__ == "__main__":
    # This is only invoked during runtime when running the latex command through a process.
    _text = sys.argv[1]
    _image_path = pathlib.Path(sys.argv[2])
    _function = partial(render, _text, _image_path)

    try:
        _result = bound_render(_function)

        if isinstance(_result, str):
            # If a resource limit was hit, let the parent process know
            sys.stdout.write(_result)
            exit(1)

        # Normal exit
        exit(0)

    except ValueError as e:
        sys.stdout.write(str(e))
        exit(1)

    except Exception as e:
        # Unhandled exception
        # TODO: Parse this error better # noqa: Why
        sys.stdout.write(str(e))
        exit(2)
