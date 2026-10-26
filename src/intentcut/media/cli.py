"""Command-line adapter for the local video renderer."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from intentcut.media.models import MediaError
from intentcut.media.render import VerticalVideoRenderer


class RenderCLI:
    """Parse CLI arguments and translate renderer results into messages and status."""

    def __init__(self, renderer: VerticalVideoRenderer | None = None) -> None:
        self._renderer = renderer if renderer is not None else VerticalVideoRenderer()

    def run(self, arguments: Sequence[str] | None = None) -> int:
        """Use process arguments by default; return 0 on success and 1 on failure."""
        args = self._create_parser().parse_args(arguments)
        try:
            result = self._renderer.render(args.inputs, args.output)
        except (MediaError, OSError) as exc:
            print(f"intentcut-render: {exc}", file=sys.stderr)
            return 1
        print(
            f"Rendered {result.input_count} clips to {result.output_path} "
            f"({result.metadata.duration:.3f}s, 720x1280, 30 FPS)"
        )
        return 0

    @staticmethod
    def _create_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Render ordered clips to vertical MP4."
        )
        parser.add_argument(
            "inputs", nargs="+", type=Path, help="Input videos, in order"
        )
        parser.add_argument(
            "-o", "--output", required=True, type=Path, help="New .mp4 path"
        )
        return parser


def main() -> int:
    """Console-script entry point kept for installed ``intentcut-render`` commands."""
    return RenderCLI().run()


if __name__ == "__main__":
    raise SystemExit(main())
