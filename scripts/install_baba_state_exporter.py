#!/usr/bin/env python3
"""Install or remove the Codex Baba Is You Lua state exporter."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from baba_config import PROJECT_ROOT, load_config


SOURCE_PATH = PROJECT_ROOT / "lua" / "codex_state_export.lua"
TARGET_NAME = "codex_state_export.lua"
MARKER = "codex-baba-state-export-v1"


def lua_string_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def render_source(export_path: Path) -> str:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    return f"CODEX_STATE_EXPORT_PATH = {lua_string_literal(str(export_path))}\n" + source


def backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return target.with_name(f"{target.name}.{stamp}.bak")


def install(target: Path, rendered: str, *, dry_run: bool, force: bool) -> int:
    target.parent.mkdir(parents=True, exist_ok=True) if not dry_run else None

    if target.exists():
        current = target.read_text(encoding="utf-8", errors="replace")
        if current == rendered:
            print(f"already_installed={target}")
            return 0
        if MARKER not in current and not force:
            raise SystemExit(
                f"{target} exists and does not look like a Codex exporter. "
                "Use --force to replace it."
            )
        backup = backup_path(target)
        print(f"backup={backup}")
        if not dry_run:
            shutil.copyfile(target, backup)

    print(f"install={target}")
    if not dry_run:
        target.write_text(rendered, encoding="utf-8")
    return 0


def uninstall(target: Path, *, dry_run: bool, force: bool) -> int:
    if not target.exists():
        print(f"not_installed={target}")
        return 0

    current = target.read_text(encoding="utf-8", errors="replace")
    if MARKER not in current and not force:
        raise SystemExit(
            f"{target} does not look like a Codex exporter. Use --force to remove it."
        )

    print(f"remove={target}")
    if not dry_run:
        target.unlink()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--game-root", type=Path, help="Override configured Worlds directory")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument(
        "--export-path",
        type=Path,
        help="State JSON path. Defaults to <save_dir>/codex_state.json",
    )
    parser.add_argument("--uninstall", action="store_true", help="Remove the installed exporter")
    parser.add_argument("--force", action="store_true", help="Replace/remove an existing target")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    config = load_config(args.config)
    game_root = args.game_root or config.game_root
    save_dir = args.save_dir or config.save_dir
    export_path = (args.export_path or (save_dir / "codex_state.json")).expanduser().resolve()

    data_dir = game_root.parent
    target = data_dir / "Lua" / TARGET_NAME

    print(f"data_dir={data_dir}")
    print(f"target={target}")
    print(f"export_path={export_path}")

    if args.uninstall:
        return uninstall(target, dry_run=args.dry_run, force=args.force)

    rendered = render_source(export_path)
    return install(target, rendered, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
