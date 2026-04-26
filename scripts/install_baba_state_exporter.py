#!/usr/bin/env python3
"""Install or remove the Codex Baba Is You Lua state exporter."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from baba_config import (
    PROJECT_ROOT,
    STATE_EXPORTER_MARKER,
    STATE_EXPORTER_TARGET_NAME,
    load_config,
    refresh_config_status,
)
from parse_baba_level import current_level


SOURCE_PATH = PROJECT_ROOT / "lua" / "codex_state_export.lua"
TARGET_NAME = STATE_EXPORTER_TARGET_NAME
MARKER = STATE_EXPORTER_MARKER
PROBE_SOURCE_PATH = PROJECT_ROOT / "lua" / "codex_state_probe.lua"
PROBE_TARGET_NAME = "codex_state_probe.lua"
PROBE_MARKER = "codex-baba-state-probe-v1"
LOADER_BEGIN = "-- BEGIN CODEX BABA STATE EXPORTER LOADER"
LOADER_END = "-- END CODEX BABA STATE EXPORTER LOADER"
COMMAND_LOADER_BEGIN = "-- BEGIN CODEX BABA STATE EXPORTER COMMAND LOADER"
COMMAND_LOADER_END = "-- END CODEX BABA STATE EXPORTER COMMAND LOADER"


def lua_string_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def render_source(source_path: Path) -> str:
    return source_path.read_text(encoding="utf-8")


def render_loader() -> str:
    return "\n".join(
        [
            LOADER_BEGIN,
            "do",
            f"\tlocal exporter = {lua_string_literal('Data/Lua/' + TARGET_NAME)}",
            "\tdofile(exporter)",
            "end",
            LOADER_END,
        ]
    )


def render_command_loader() -> str:
    return "\n".join(
        [
            "\t" + COMMAND_LOADER_BEGIN,
            "\tif CODEX_STATE_EXPORTER_COMMAND_LOADED ~= true then",
            "\t\tCODEX_STATE_EXPORTER_COMMAND_LOADED = true",
            f"\t\tlocal exporter = {lua_string_literal('Data/Lua/' + TARGET_NAME)}",
            "\t\tdofile(exporter)",
            "\tend",
            "\t" + COMMAND_LOADER_END,
        ]
    )


def backup_path(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return target.with_name(f"{target.name}.{stamp}.bak")


def install(target: Path, rendered: str, *, dry_run: bool, force: bool, marker: str) -> int:
    target.parent.mkdir(parents=True, exist_ok=True) if not dry_run else None

    if target.exists():
        current = target.read_text(encoding="utf-8", errors="replace")
        if current == rendered:
            print(f"already_installed={target}")
            return 0
        if marker not in current and not force:
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


def uninstall(target: Path, *, dry_run: bool, force: bool, marker: str) -> int:
    if not target.exists():
        print(f"not_installed={target}")
        return 0

    current = target.read_text(encoding="utf-8", errors="replace")
    if marker not in current and not force:
        raise SystemExit(
            f"{target} does not look like a Codex exporter. Use --force to remove it."
        )

    print(f"remove={target}")
    if not dry_run:
        target.unlink()
    return 0


def remove_marked_block(text: str, begin: str, end_marker: str) -> tuple[str, bool]:
    start = text.find(begin)
    end = text.find(end_marker)
    if start < 0 or end < 0 or end < start:
        return text, False
    end += len(end_marker)
    if end < len(text) and text[end] == "\n":
        end += 1
    if start > 0 and text[start - 1] == "\n":
        start -= 1
    return text[:start].rstrip() + "\n" + text[end:].lstrip("\n"), True


def install_loader(data_dir: Path, *, dry_run: bool) -> int:
    target = data_dir / "modsupport.lua"
    current = target.read_text(encoding="utf-8", errors="replace")
    without_loader, had_loader = remove_marked_block(current, LOADER_BEGIN, LOADER_END)
    block = render_loader()
    updated = without_loader.rstrip() + "\n\n" + block + "\n"

    if current == updated:
        print(f"loader_already_installed={target}")
        return 0

    backup = backup_path(target)
    action = "update_loader" if had_loader else "install_loader"
    print(f"loader_backup={backup}")
    print(f"{action}={target}")
    if not dry_run:
        shutil.copyfile(target, backup)
        target.write_text(updated, encoding="utf-8")
    return 0


def uninstall_loader(data_dir: Path, *, dry_run: bool) -> int:
    target = data_dir / "modsupport.lua"
    current = target.read_text(encoding="utf-8", errors="replace")
    updated, had_loader = remove_marked_block(current, LOADER_BEGIN, LOADER_END)
    if not had_loader:
        print(f"loader_not_installed={target}")
        return 0

    backup = backup_path(target)
    print(f"loader_backup={backup}")
    print(f"remove_loader={target}")
    if not dry_run:
        shutil.copyfile(target, backup)
        target.write_text(updated, encoding="utf-8")
    return 0


def install_command_loader(
    data_dir: Path,
    *,
    dry_run: bool,
) -> int:
    target = data_dir / "syntax.lua"
    current = target.read_text(encoding="utf-8", errors="replace")
    without_loader, had_loader = remove_marked_block(
        current,
        COMMAND_LOADER_BEGIN,
        COMMAND_LOADER_END,
    )
    needle = "function command(key,player_)\n"
    if needle not in without_loader:
        raise SystemExit(f"Could not find command() in {target}")
    updated = without_loader.replace(
        needle,
        needle + render_command_loader() + "\n",
        1,
    )

    if current == updated:
        print(f"command_loader_already_installed={target}")
        return 0

    backup = backup_path(target)
    action = "update_command_loader" if had_loader else "install_command_loader"
    print(f"command_loader_backup={backup}")
    print(f"{action}={target}")
    if not dry_run:
        shutil.copyfile(target, backup)
        target.write_text(updated, encoding="utf-8")
    return 0


def uninstall_command_loader(data_dir: Path, *, dry_run: bool) -> int:
    target = data_dir / "syntax.lua"
    current = target.read_text(encoding="utf-8", errors="replace")
    updated, had_loader = remove_marked_block(
        current,
        COMMAND_LOADER_BEGIN,
        COMMAND_LOADER_END,
    )
    if not had_loader:
        print(f"command_loader_not_installed={target}")
        return 0

    backup = backup_path(target)
    print(f"command_loader_backup={backup}")
    print(f"remove_command_loader={target}")
    if not dry_run:
        shutil.copyfile(target, backup)
        target.write_text(updated, encoding="utf-8")
    return 0


def default_world(save_dir: Path) -> str:
    try:
        _slot, world, _level = current_level(save_dir)
        return world
    except SystemExit:
        return "baba"


def target_paths(data_dir: Path, *, scope: str, world: str, target_name: str) -> list[Path]:
    targets: list[Path] = []
    if scope in {"global", "both"}:
        targets.append(data_dir / "Lua" / target_name)
    if scope in {"world", "both"}:
        targets.append(data_dir / "Worlds" / world / "Lua" / target_name)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--game-root", type=Path, help="Override configured Worlds directory")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Install/remove the minimal Data/Lua canary probe instead of the full exporter.",
    )
    parser.add_argument(
        "--scope",
        choices=["global", "world", "both"],
        help=(
            "Install/remove target. Defaults to global for install and both "
            "for uninstall so older installs are cleaned up."
        ),
    )
    parser.add_argument("--world", help="World folder for --scope world/both. Defaults to current save world.")
    parser.add_argument(
        "--patch-loader",
        action="store_true",
        help="Also patch Data/modsupport.lua. Normally unnecessary because Baba already loads Data/Lua.",
    )
    parser.add_argument(
        "--patch-command-loader",
        action="store_true",
        help="Also patch Data/syntax.lua command(). Normally unnecessary and higher risk.",
    )
    parser.add_argument("--uninstall", action="store_true", help="Remove the installed exporter")
    parser.add_argument("--force", action="store_true", help="Replace/remove an existing target")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    if args.probe and (args.patch_loader or args.patch_command_loader):
        raise SystemExit("--probe never patches modsupport.lua or syntax.lua")

    config = load_config(args.config, refresh_status=not args.dry_run)
    game_root = args.game_root or config.game_root
    save_dir = args.save_dir or config.save_dir
    data_dir = game_root.parent
    world = args.world or default_world(save_dir)
    scope = args.scope or ("both" if args.uninstall else "global")
    source_path = PROBE_SOURCE_PATH if args.probe else SOURCE_PATH
    target_name = PROBE_TARGET_NAME if args.probe else TARGET_NAME
    marker = PROBE_MARKER if args.probe else MARKER
    targets = target_paths(data_dir, scope=scope, world=world, target_name=target_name)

    print(f"data_dir={data_dir}")
    print(f"artifact={'probe' if args.probe else 'exporter'}")
    print(f"scope={scope}")
    print(f"world={world}")
    print(f"state_storage=world:[codex_probe]" if args.probe else "state_storage=save:[codex_state]")
    print(f"patch_loader={args.patch_loader}")
    print(f"patch_command_loader={args.patch_command_loader}")

    result = 0
    if args.uninstall:
        for target in targets:
            print(f"target={target}")
            result |= uninstall(target, dry_run=args.dry_run, force=args.force, marker=marker)
        if not args.probe:
            probe_target = data_dir / "Lua" / PROBE_TARGET_NAME
            print(f"target={probe_target}")
            result |= uninstall(probe_target, dry_run=args.dry_run, force=args.force, marker=PROBE_MARKER)
            result |= uninstall_loader(data_dir, dry_run=args.dry_run)
            result |= uninstall_command_loader(data_dir, dry_run=args.dry_run)
        if not args.dry_run:
            refreshed = refresh_config_status(config.config_path)
            print(f"game_files_found={refreshed['game_files_found']}")
            print(f"state_exporter_installed={refreshed['state_exporter_installed']}")
        return result

    rendered = render_source(source_path)
    for target in targets:
        print(f"target={target}")
        result |= install(target, rendered, dry_run=args.dry_run, force=args.force, marker=marker)
    if args.patch_loader:
        result |= install_loader(data_dir, dry_run=args.dry_run)
    if args.patch_command_loader:
        result |= install_command_loader(data_dir, dry_run=args.dry_run)
    if not args.dry_run:
        refreshed = refresh_config_status(config.config_path)
        print(f"game_files_found={refreshed['game_files_found']}")
        print(f"state_exporter_installed={refreshed['state_exporter_installed']}")
    return result


if __name__ == "__main__":
    sys.exit(main())
