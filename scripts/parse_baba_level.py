#!/usr/bin/env python3
"""Read Baba Is You level files and print a usable text map.

This parser is intentionally read-only. It understands the common macOS Steam
layout plus the plain-text save/settings files under Application Support.
"""

from __future__ import annotations

import argparse
import collections
import re
import struct
import sys
import zlib
from pathlib import Path

from baba_config import load_config

SYMBOLS = {
    "empty": ".",
    "void": " ",
    "wall": "#",
    "baba": "B",
    "keke": "K",
    "rock": "R",
    "ice": "I",
    "fruit": "F",
    "grass": ",",
    "door": "D",
    "key": "Y",
    "flag": "G",
    "skull": "S",
    "brick": "M",
    "flower": "*",
    "text_baba": "b",
    "text_and": "&",
    "text_keke": "k",
    "text_rock": "r",
    "text_ice": "i",
    "text_fruit": "f",
    "text_wall": "w",
    "text_text": "T",
    "text_is": "=",
    "text_you": "y",
    "text_win": "W",
    "text_stop": "x",
    "text_push": "p",
    "text_float": "l",
    "text_tele": "t",
    "text_sink": "s",
    "text_open": "o",
    "text_shut": "h",
}


def read_ini_like(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = collections.defaultdict(dict)
    current = ""
    for raw_line in path.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            sections[current][key] = value
    return dict(sections)


def current_level(save_dir: Path) -> tuple[int, str, str]:
    settings = read_ini_like(save_dir / "SettingsC.txt")
    slot = int(settings.get("savegame", {}).get("slot", "1"))
    world = settings.get("savegame", {}).get("world", "baba")
    save_file = save_dir / f"{slot}ba.ba"
    save = read_ini_like(save_file)
    level = save.get(world, {}).get("Previous")
    if not level:
        raise SystemExit(f"Could not find Previous level in {save_file} [{world}]")
    return slot, world, level


def parse_currobjlist(level_data: str) -> tuple[dict[int, str], dict[str, str]]:
    sections: dict[str, dict[str, str]] = collections.defaultdict(dict)
    current = ""
    for raw_line in level_data.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            sections[current][key] = value

    items: dict[int, dict[str, str]] = collections.defaultdict(dict)
    for key, value in sections.get("currobjlist", {}).items():
        match = re.fullmatch(r"(\d+)([A-Za-z_]+)", key)
        if match:
            items[int(match.group(1))][match.group(2)] = value

    code_to_name: dict[int, str] = {0: "empty", 65535: "void"}
    name_to_symbol: dict[str, str] = {}
    for item in items.values():
        name = item.get("name")
        tile = item.get("tile")
        if not name or not tile:
            continue
        x_str, y_str = tile.split(",", 1)
        code_to_name[int(y_str) * 256 + int(x_str)] = name
        name_to_symbol[name] = SYMBOLS.get(name, name[:1].upper())
    return code_to_name, name_to_symbol


def parse_global_tiles(values_path: Path) -> tuple[dict[int, str], dict[str, str]]:
    if not values_path.exists():
        return {0: "empty", 65535: "void"}, {}

    text = values_path.read_text(errors="replace")
    code_to_name: dict[int, str] = {0: "empty", 65535: "void"}
    name_to_symbol: dict[str, str] = {}

    for match in re.finditer(r"object\d+\s*=\s*\{(.*?)\n\t\}", text, re.S):
        block = match.group(1)
        name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
        tile_match = re.search(r"tile\s*=\s*\{\s*(\d+)\s*,\s*(\d+)\s*\}", block)
        if not name_match or not tile_match:
            continue
        name = name_match.group(1)
        x = int(tile_match.group(1))
        y = int(tile_match.group(2))
        code_to_name[y * 256 + x] = name
        name_to_symbol[name] = SYMBOLS.get(name, name[:1].upper())

    return code_to_name, name_to_symbol


def parse_level_binary(level_path: Path) -> tuple[int, int, list[list[int]]]:
    data = level_path.read_bytes()
    layr = data.find(b"LAYR")
    if layr < 0:
        raise SystemExit(f"Missing LAYR chunk in {level_path}")

    # After "LAYR", the observed Baba level header stores:
    # u32 chunk_size, u16 layer_count, u16 width, u16 reserved, u16 height.
    width = struct.unpack_from("<H", data, layr + 4 + 6)[0]
    height = struct.unpack_from("<H", data, layr + 4 + 10)[0]
    cell_count = width * height

    layers: list[list[int]] = []
    for match in re.finditer(b"MAIN", data):
        pos = match.start() + 4
        compressed_len = struct.unpack_from("<I", data, pos)[0]
        compressed = data[pos + 4 : pos + 4 + compressed_len]
        raw = zlib.decompress(compressed)
        values = list(struct.unpack("<" + "H" * (len(raw) // 2), raw))
        if len(values) == cell_count:
            layers.append(values)

    if not layers:
        raise SystemExit(f"No MAIN map layers found in {level_path}")
    return width, height, layers


def parse_level_direction_layers(level_path: Path, cell_count: int) -> list[list[int]]:
    data = level_path.read_bytes()
    layers: list[list[int]] = []
    for match in re.finditer(b"DATA", data):
        start = match.start()
        zlib_start = -1
        for candidate in range(start + 4, min(start + 40, len(data) - 1)):
            if data[candidate] == 0x78:
                try:
                    compressed_len = struct.unpack_from("<I", data, candidate - 4)[0]
                except struct.error:
                    continue
                if compressed_len <= 0 or candidate + compressed_len > len(data):
                    continue
                try:
                    raw = zlib.decompress(data[candidate : candidate + compressed_len])
                except zlib.error:
                    continue
                if len(raw) == cell_count:
                    zlib_start = candidate
                    layers.append(list(raw))
                    break
        if zlib_start < 0:
            continue
    return layers


def word_for(name: str) -> str | None:
    return name.removeprefix("text_") if name.startswith("text_") else None


def collect_positions(
    width: int, height: int, layers: list[list[int]], code_to_name: dict[int, str]
) -> dict[str, list[tuple[int, int, int]]]:
    positions: dict[str, list[tuple[int, int, int]]] = collections.defaultdict(list)
    for layer_index, layer in enumerate(layers):
        for y in range(height):
            for x in range(width):
                name = code_to_name.get(layer[y * width + x], f"unknown_{layer[y * width + x]:03x}")
                if name not in {"empty", "void"}:
                    positions[name].append((x, y, layer_index))
    return dict(sorted(positions.items()))


def active_rules(
    width: int, height: int, layers: list[list[int]], code_to_name: dict[int, str]
) -> list[tuple[str, tuple[int, int], str, str, str]]:
    grid: list[list[list[str]]] = [[[] for _ in range(width)] for _ in range(height)]
    for layer in layers:
        for y in range(height):
            for x in range(width):
                name = code_to_name.get(layer[y * width + x])
                word = word_for(name or "")
                if word:
                    grid[y][x].append(word)

    def in_bounds(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height

    def words_at(x: int, y: int) -> list[str]:
        if not in_bounds(x, y):
            return []
        return grid[y][x]

    def extend_and_sequence(
        x: int,
        y: int,
        dx: int,
        dy: int,
    ) -> list[tuple[list[tuple[str, tuple[int, int]]], int]]:
        sequences: list[tuple[list[tuple[str, tuple[int, int]]], int]] = []
        states: list[tuple[list[tuple[str, tuple[int, int]]], int]] = []
        for word in words_at(x, y):
            if word not in {"is", "and"}:
                states.append(([(word, (x, y))], 1))

        while states:
            items, offset = states.pop()
            sequences.append((items, offset))
            and_x = x + offset * dx
            and_y = y + offset * dy
            next_x = x + (offset + 1) * dx
            next_y = y + (offset + 1) * dy
            if "and" not in words_at(and_x, and_y):
                continue
            for word in words_at(next_x, next_y):
                if word not in {"is", "and"}:
                    states.append(([*items, (word, (next_x, next_y))], offset + 2))
        return sequences

    rules: list[tuple[str, tuple[int, int], str, str, str]] = []
    seen_rules: set[tuple[str, tuple[int, int], str, str, str]] = set()
    for y in range(height):
        for x in range(width):
            for dx, dy, direction in ((1, 0, "H"), (0, 1, "V")):
                for subjects, offset in extend_and_sequence(x, y, dx, dy):
                    is_x = x + offset * dx
                    is_y = y + offset * dy
                    if "is" not in words_at(is_x, is_y):
                        continue
                    prop_x = x + (offset + 1) * dx
                    prop_y = y + (offset + 1) * dy
                    for props, _prop_offset in extend_and_sequence(prop_x, prop_y, dx, dy):
                        for first, first_coord in subjects:
                            for last, _last_coord in props:
                                rule = (direction, first_coord, first, "is", last)
                                if rule not in seen_rules:
                                    seen_rules.add(rule)
                                    rules.append(rule)
    return rules


def render_layer(
    width: int,
    height: int,
    layer: list[int],
    code_to_name: dict[int, str],
    name_to_symbol: dict[str, str],
) -> list[str]:
    rows = ["    " + "".join(str(i % 10) for i in range(width))]
    for y in range(height):
        chars = []
        for x in range(width):
            name = code_to_name.get(layer[y * width + x], "?")
            chars.append(name_to_symbol.get(name, SYMBOLS.get(name, "?")))
        rows.append(f"{y:02d}: " + "".join(chars))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--game-root", type=Path, help="Override configured Worlds directory")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--world", help="World folder, such as museum or baba")
    parser.add_argument("--level", help="Level id without extension, such as y128level")
    parser.add_argument("--all-layers", action="store_true", help="Print every map layer")
    parser.add_argument("--rules-only", action="store_true", help="Print level identity and initial active rules only")
    args = parser.parse_args()
    config = load_config(args.config)
    game_root = args.game_root or config.game_root
    save_dir = args.save_dir or config.save_dir

    if args.world and args.level:
        slot = None
        world = args.world
        level = args.level
    else:
        slot, world, level = current_level(save_dir)

    level_dir = game_root / world
    ld_path = level_dir / f"{level}.ld"
    l_path = level_dir / f"{level}.l"
    if not ld_path.exists() or not l_path.exists():
        raise SystemExit(f"Missing level files: {ld_path} / {l_path}")

    level_data = ld_path.read_text(errors="replace")
    general = read_ini_like(ld_path).get("general", {})
    code_to_name, name_to_symbol = parse_global_tiles(game_root.parent / "values.lua")
    level_code_to_name, level_name_to_symbol = parse_currobjlist(level_data)
    code_to_name.update(level_code_to_name)
    name_to_symbol.update(level_name_to_symbol)
    width, height, layers = parse_level_binary(l_path)
    direction_layers = parse_level_direction_layers(l_path, width * height)
    positions = collect_positions(width, height, layers, code_to_name)
    rules = active_rules(width, height, layers, code_to_name)
    move_bounds = f"x=1..{width - 2} y=1..{height - 2}"

    source = f"slot={slot} " if slot is not None else ""
    print(f"{source}world={world} level={level} name={general.get('name', '<unknown>')}")
    print(f"size={width}x{height} layers={len(layers)}")
    print(f"movement_bounds={move_bounds} (file coordinates; outer border is not walkable)")
    print()
    print("Initial active rules:" if args.rules_only else "Active rules:")
    for direction, (x, y), first, middle, last in rules:
        print(f"  {direction} ({x},{y}): {first} {middle} {last}")

    if args.rules_only:
        return 0

    print()
    layer_count = len(layers) if args.all_layers else 1
    for index, layer in enumerate(layers[:layer_count]):
        if layer_count > 1:
            print(f"Layer {index}:")
        print("\n".join(render_layer(width, height, layer, code_to_name, name_to_symbol)))
        print()

    print("Positions:")
    for name, coords in positions.items():
        pretty_coords = []
        for x, y, layer in coords:
            suffix = ""
            if not name.startswith("text_") and layer < len(direction_layers):
                direction = direction_layers[layer][y * width + x]
                suffix = f",dir={direction}"
            pretty_coords.append(f"({x},{y},L{layer}{suffix})")
        pretty = ", ".join(pretty_coords)
        print(f"  {name}: {pretty}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
