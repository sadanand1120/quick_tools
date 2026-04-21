import argparse
import sys
from pathlib import Path

from .ply_viewer import serve_ply_viewer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quick-tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ply_viewer = subparsers.add_parser("ply-viewer", help="View a PLY file in the browser.")
    ply_viewer.add_argument("ply_path", type=Path, help="Path to the PLY file.")
    ply_viewer.add_argument("--local", action="store_true", help="Open directly with Open3D.")
    ply_viewer.add_argument("--port", type=int, default=8000, help="Port to serve on.")
    ply_viewer.add_argument("--point-size", type=float, help="Point size for the viewer.")
    ply_viewer.set_defaults(func=run_ply_viewer)

    return parser


def run_ply_viewer(args: argparse.Namespace) -> int:
    return serve_ply_viewer(
        args.ply_path,
        port=args.port,
        local=args.local,
        point_size=args.point_size,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
