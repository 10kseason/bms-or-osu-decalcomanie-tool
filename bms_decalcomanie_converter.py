from __future__ import annotations

import argparse
import math
import random
import re
import sys
import wave
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Iterable


CHART_LINE_RE = re.compile(rb"^#([0-9]{3})([0-9A-Za-z]{2}):(.*)$")
PLAYER_RE = re.compile(rb"^#PLAYER\b", re.IGNORECASE)
KEY_EXTENSION_RE = re.compile(rb"^#(?:[1-9]|10)K\b", re.IGNORECASE)

DEFAULT_EXTENSIONS = {".bms", ".bme", ".bml", ".pms", ".osu"}
BMS_EXTENSIONS = {".bms", ".bme", ".bml", ".pms"}
OSU_EXTENSIONS = {".osu"}

VISIBLE_MIRROR = {
    b"11": b"25",
    b"12": b"24",
    b"13": b"23",
    b"14": b"22",
    b"15": b"21",
}

LONGNOTE_MIRROR = {
    b"51": b"65",
    b"52": b"64",
    b"53": b"63",
    b"54": b"62",
    b"55": b"61",
}

INVISIBLE_MIRROR = {
    b"31": b"45",
    b"32": b"44",
    b"33": b"43",
    b"34": b"42",
    b"35": b"41",
}

RANDOM_VISIBLE_CHANNELS = [b"11", b"12", b"13", b"14", b"15", b"21", b"22", b"23", b"24", b"25"]
RANDOM_LONGNOTE_CHANNELS = [b"51", b"52", b"53", b"54", b"55", b"61", b"62", b"63", b"64", b"65"]


@dataclass
class ConvertOptions:
    output_dir: Path | None = None
    set_player_double: bool = True
    mirror_long_notes: bool = True
    mirror_invisible: bool = False
    overwrite: bool = False


@dataclass
class ConvertResult:
    source: Path
    output: Path | None
    mirrored_lines: int = 0
    collision_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.output is not None and not self.warnings


@dataclass
class RandomNoteOptions:
    output_dir: Path | None = None
    title: str = "Random Notes"
    bpm: float = 120.0
    beat_interval: Fraction | str | float = Fraction(1, 4)
    measures: int = 16
    generation_count: int | None = None
    min_notes_per_beat: int = 0
    max_notes_per_beat: int = 10
    empty_single_weight: float = 25.0
    empty_long_start_weight: float = 50.0
    empty_rest_weight: float = 25.0
    holding_long_end_weight: float = 25.0
    holding_keep_weight: float = 75.0
    lanes: int = 10
    note_object_id: str = "01"
    wav_filename: str = "_random_note_silence.wav"
    seed: int | None = None
    overwrite: bool = False


@dataclass
class RandomNoteResult:
    output: Path
    visible_notes: int = 0
    long_note_starts: int = 0
    long_note_ends: int = 0
    silence_wav: Path | None = None
    silence_wav_created: bool = False


@dataclass
class RandomNotePattern:
    visible_grid: list[list[bool]]
    long_grid: list[list[bool]]
    resolution: int
    total_ticks: int
    visible_notes: int = 0
    long_note_starts: int = 0
    long_note_ends: int = 0


def newline_of(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    return b""


def body_without_newline(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith(b"\n"):
        return line[:-1]
    return line


def is_zero_pair(pair: bytes) -> bool:
    return len(pair) == 2 and pair.upper() == b"00"


def split_pairs(data: bytes) -> list[bytes]:
    data = data.strip()
    if len(data) % 2 != 0:
        raise ValueError("object data length is not even")
    pairs = [data[i : i + 2] for i in range(0, len(data), 2)]
    return pairs


def merge_note_data(base: bytes | None, incoming: bytes) -> tuple[bytes, int]:
    if base is None:
        return incoming.strip(), 0

    base_pairs = split_pairs(base)
    incoming_pairs = split_pairs(incoming)
    if not base_pairs:
        return incoming.strip(), 0
    if not incoming_pairs:
        return base.strip(), 0

    merged_len = math.lcm(len(base_pairs), len(incoming_pairs))
    merged = [b"00"] * merged_len
    collisions = 0

    for index, pair in enumerate(base_pairs):
        if is_zero_pair(pair):
            continue
        merged[index * (merged_len // len(base_pairs))] = pair

    for index, pair in enumerate(incoming_pairs):
        if is_zero_pair(pair):
            continue
        target_index = index * (merged_len // len(incoming_pairs))
        if not is_zero_pair(merged[target_index]) and merged[target_index] != pair:
            collisions += 1
            continue
        merged[target_index] = pair

    return b"".join(merged), collisions


def mirror_map(options: ConvertOptions) -> dict[bytes, bytes]:
    mapping = dict(VISIBLE_MIRROR)
    if options.mirror_long_notes:
        mapping.update(LONGNOTE_MIRROR)
    if options.mirror_invisible:
        mapping.update(INVISIBLE_MIRROR)
    return mapping


def unique_output_path(source: Path, output_dir: Path | None, overwrite: bool) -> Path:
    target_dir = output_dir if output_dir else source.parent
    target = target_dir / f"{source.stem}_10k_decal{source.suffix}"
    if overwrite or not target.exists():
        return target

    for index in range(2, 1000):
        candidate = target_dir / f"{source.stem}_10k_decal_{index}{source.suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"could not find a free output name for {source.name}")


def parse_chart_line(line: bytes) -> tuple[bytes, bytes, bytes] | None:
    match = CHART_LINE_RE.match(body_without_newline(line))
    if not match:
        return None
    measure, channel, data = match.groups()
    return measure, channel.upper(), data.strip()


def build_chart_line(measure: bytes, channel: bytes, data: bytes, newline: bytes) -> bytes:
    return b"#" + measure + channel + b":" + data + newline


def parse_beat_interval(value: Fraction | str | float | int) -> Fraction:
    if isinstance(value, Fraction):
        interval = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("beat interval is empty")
        interval = Fraction(stripped)
    else:
        interval = Fraction(str(value))
    if interval <= 0:
        raise ValueError("beat interval must be greater than 0")
    return interval


def bms_number(value: float) -> str:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("BPM must be greater than 0")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def bms_key_extension_line(lane_count: int, newline: bytes = b"\r\n") -> bytes | None:
    if 4 <= lane_count <= 8 or lane_count == 10:
        return f"#{lane_count}K".encode("ascii") + newline
    return None


def validate_weight(value: float, label: str) -> float:
    weight = float(value)
    if not math.isfinite(weight) or weight < 0:
        raise ValueError(f"{label} weight must be 0 or greater")
    return weight


def choose_weighted(rng: random.Random, weighted_actions: list[tuple[str, float]], label: str) -> str:
    total = sum(weight for _action, weight in weighted_actions)
    if total <= 0:
        raise ValueError(f"{label} weights must include at least one positive value")

    pick = rng.random() * total
    cumulative = 0.0
    fallback = weighted_actions[-1][0]
    for action, weight in weighted_actions:
        if weight <= 0:
            continue
        fallback = action
        cumulative += weight
        if pick < cumulative:
            return action
    return fallback


def random_measure_resolution(beat_interval: Fraction | str | float | int) -> int:
    interval = parse_beat_interval(beat_interval)
    positions_per_measure = Fraction(4, 1) / interval
    if positions_per_measure.denominator != 1:
        raise ValueError("beat interval must divide a 4-beat measure exactly")
    resolution = positions_per_measure.numerator
    if resolution < 1:
        raise ValueError("beat interval must be 4 beats or shorter")
    return resolution


def validate_note_object_id(note_object_id: str) -> bytes:
    token = note_object_id.strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{2}", token) or token == "00":
        raise ValueError("note object id must be a non-zero 2-character BMS object id, such as 01")
    return token.encode("ascii")


def validate_wav_filename(wav_filename: str) -> str:
    name = wav_filename.strip()
    if not name:
        raise ValueError("wav filename is empty")
    if Path(name).name != name:
        raise ValueError("wav filename must be a file name, not a path")
    return name


def validate_min_notes_per_beat(value: int, lane_count: int) -> int:
    minimum = int(value)
    if minimum < 0 or minimum > lane_count:
        raise ValueError("minimum notes per beat must be between 0 and key count")
    return minimum


def validate_max_notes_per_beat(value: int, lane_count: int) -> int:
    maximum = int(value)
    if maximum < 0:
        raise ValueError("maximum notes per beat must be 0 or greater")
    return min(maximum, lane_count)


def choose_forced_non_rest_lanes(rng: random.Random, empty_lanes: list[int], minimum: int) -> set[int]:
    if minimum <= 0 or not empty_lanes:
        return set()
    return set(rng.sample(empty_lanes, min(minimum, len(empty_lanes))))


def choose_forced_rest_lanes(rng: random.Random, empty_lanes: list[int], maximum: int) -> set[int]:
    forced_count = len(empty_lanes) - maximum
    if forced_count <= 0:
        return set()
    return set(rng.sample(empty_lanes, forced_count))


def apply_forced_long_note_ends(
    rng: random.Random,
    lane_count: int,
    minimum: int,
    holding_lanes: list[int],
    keep_lanes: set[int],
) -> set[int]:
    if minimum <= 0 or not keep_lanes:
        return set()
    available_next = lane_count - (len(holding_lanes) + len(keep_lanes))
    needed_end_count = minimum - available_next
    if needed_end_count <= 0:
        return set()
    return set(rng.sample(sorted(keep_lanes), min(needed_end_count, len(keep_lanes))))


def choose_forced_long_note_start_conversions(
    rng: random.Random,
    lane_count: int,
    minimum: int,
    keep_lanes: set[int],
    start_lanes: set[int],
) -> set[int]:
    if minimum <= 0 or not start_lanes:
        return set()
    max_holding_next = lane_count - minimum
    overflow = len(keep_lanes) + len(start_lanes) - max_holding_next
    if overflow <= 0:
        return set()
    return set(rng.sample(sorted(start_lanes), min(overflow, len(start_lanes))))


def choose_forced_empty_action(
    rng: random.Random,
    single_weight: float,
    start_weight: float,
    is_last_tick: bool,
) -> str:
    if is_last_tick:
        return "single"
    forced_actions = [("single", single_weight), ("start", start_weight)]
    if single_weight + start_weight <= 0:
        return "single"
    return choose_weighted(rng, forced_actions, "forced empty")


def make_random_note_pattern(options: RandomNoteOptions) -> RandomNotePattern:
    measures = int(options.measures)
    if measures < 1 or measures > 999:
        raise ValueError("measure count must be between 1 and 999")
    if options.lanes < 1 or options.lanes > len(RANDOM_VISIBLE_CHANNELS):
        raise ValueError("lane count must be between 1 and 10")
    minimum_notes = validate_min_notes_per_beat(options.min_notes_per_beat, options.lanes)
    maximum_notes = validate_max_notes_per_beat(options.max_notes_per_beat, options.lanes)
    if minimum_notes > maximum_notes:
        raise ValueError("minimum notes per beat cannot be greater than maximum notes per beat")

    resolution = random_measure_resolution(options.beat_interval)
    if options.generation_count is None:
        total_ticks = measures * resolution
    else:
        total_ticks = int(options.generation_count)
        if total_ticks < 1:
            raise ValueError("generation count must be 1 or greater")
    measure_count = math.ceil(total_ticks / resolution)
    if measure_count > 999:
        raise ValueError("generated chart would exceed 999 BMS measures")

    single_weight = validate_weight(options.empty_single_weight, "single-note")
    start_weight = validate_weight(options.empty_long_start_weight, "long-note start")
    rest_weight = validate_weight(options.empty_rest_weight, "empty")
    end_weight = validate_weight(options.holding_long_end_weight, "long-note end")
    keep_weight = validate_weight(options.holding_keep_weight, "long-note keep")

    empty_actions = [
        ("single", single_weight),
        ("start", start_weight),
        ("rest", rest_weight),
    ]
    holding_actions = [
        ("end", end_weight),
        ("keep", keep_weight),
    ]
    rng = random.Random(options.seed)

    visible_grid = [[False] * total_ticks for _lane in range(options.lanes)]
    long_grid = [[False] * total_ticks for _lane in range(options.lanes)]
    holding = [False] * options.lanes
    visible_notes = 0
    long_note_starts = 0
    long_note_ends = 0

    for tick in range(total_ticks):
        is_last_tick = tick == total_ticks - 1
        holding_lanes = [lane for lane in range(options.lanes) if holding[lane]]
        empty_lanes = [lane for lane in range(options.lanes) if not holding[lane]]
        end_lanes: set[int] = set()
        keep_lanes: set[int] = set()

        for lane in holding_lanes:
            action = "end" if is_last_tick else choose_weighted(rng, holding_actions, "holding")
            if action == "end":
                end_lanes.add(lane)
            else:
                keep_lanes.add(lane)

        forced_end_lanes = apply_forced_long_note_ends(
            rng,
            options.lanes,
            minimum_notes,
            holding_lanes,
            keep_lanes,
        )
        end_lanes.update(forced_end_lanes)
        keep_lanes.difference_update(forced_end_lanes)

        for lane in sorted(end_lanes):
            long_grid[lane][tick] = True
            holding[lane] = False
            long_note_ends += 1

        forced_rest_lanes = choose_forced_rest_lanes(rng, empty_lanes, maximum_notes)
        non_rest_candidate_lanes = [lane for lane in empty_lanes if lane not in forced_rest_lanes]
        forced_non_rest_lanes = choose_forced_non_rest_lanes(rng, non_rest_candidate_lanes, minimum_notes)
        single_lanes: set[int] = set()
        start_lanes: set[int] = set()

        for lane in empty_lanes:
            if lane in forced_rest_lanes:
                action = "rest"
            elif lane in forced_non_rest_lanes:
                action = choose_forced_empty_action(rng, single_weight, start_weight, is_last_tick)
            elif is_last_tick:
                final_empty_actions = [("single", single_weight), ("rest", rest_weight)]
                final_total = single_weight + rest_weight
                action = choose_weighted(rng, final_empty_actions, "final empty") if final_total > 0 else "rest"
            else:
                action = choose_weighted(rng, empty_actions, "empty")

            if action == "single":
                single_lanes.add(lane)
            elif action == "start":
                start_lanes.add(lane)

        forced_single_lanes = choose_forced_long_note_start_conversions(
            rng,
            options.lanes,
            minimum_notes,
            keep_lanes,
            start_lanes,
        )
        single_lanes.update(forced_single_lanes)
        start_lanes.difference_update(forced_single_lanes)

        for lane in sorted(single_lanes):
            visible_grid[lane][tick] = True
            visible_notes += 1
        for lane in sorted(start_lanes):
            long_grid[lane][tick] = True
            holding[lane] = True
            long_note_starts += 1

    return RandomNotePattern(
        visible_grid=visible_grid,
        long_grid=long_grid,
        resolution=resolution,
        total_ticks=total_ticks,
        visible_notes=visible_notes,
        long_note_starts=long_note_starts,
        long_note_ends=long_note_ends,
    )


def make_random_bms_bytes(options: RandomNoteOptions) -> tuple[bytes, int, int, int]:
    note_id = validate_note_object_id(options.note_object_id)
    wav_filename = validate_wav_filename(options.wav_filename)
    pattern = make_random_note_pattern(options)
    measure_count = math.ceil(pattern.total_ticks / pattern.resolution)

    lines: list[bytes] = [
        b"#PLAYER " + (b"3" if options.lanes > 5 else b"1") + b"\r\n",
        f"#TITLE {options.title.strip() or 'Random Notes'}\r\n".encode("utf-8"),
        b"#ARTIST BMS Decalcomanie Tool\r\n",
        f"#BPM {bms_number(float(options.bpm))}\r\n".encode("ascii"),
        b"#PLAYLEVEL 1\r\n",
        b"#RANK 2\r\n",
        b"#TOTAL 100\r\n",
        b"#LNTYPE 1\r\n",
        b"#WAV" + note_id + b" " + wav_filename.encode("utf-8") + b"\r\n",
        b"\r\n",
    ]
    key_extension = bms_key_extension_line(options.lanes)
    if key_extension is not None:
        lines.insert(1, key_extension)

    for measure_index in range(measure_count):
        measure = f"{measure_index + 1:03d}".encode("ascii")
        start = measure_index * pattern.resolution
        end = start + pattern.resolution

        for lane in range(options.lanes):
            if not any(pattern.visible_grid[lane][start : min(end, pattern.total_ticks)]):
                continue
            data = b"".join(
                note_id if tick < pattern.total_ticks and pattern.visible_grid[lane][tick] else b"00"
                for tick in range(start, end)
            )
            lines.append(build_chart_line(measure, RANDOM_VISIBLE_CHANNELS[lane], data, b"\r\n"))

        for lane in range(options.lanes):
            if not any(pattern.long_grid[lane][start : min(end, pattern.total_ticks)]):
                continue
            data = b"".join(
                note_id if tick < pattern.total_ticks and pattern.long_grid[lane][tick] else b"00"
                for tick in range(start, end)
            )
            lines.append(build_chart_line(measure, RANDOM_LONGNOTE_CHANNELS[lane], data, b"\r\n"))

    return b"".join(lines), pattern.visible_notes, pattern.long_note_starts, pattern.long_note_ends


def osu_time_for_tick(tick: int, bpm: float, beat_interval: Fraction | str | float | int) -> int:
    interval = parse_beat_interval(beat_interval)
    milliseconds_per_beat = 60000.0 / float(bpm)
    return int(round(tick * float(interval) * milliseconds_per_beat))


def build_random_osu_hitobject_lines(
    pattern: RandomNotePattern,
    options: RandomNoteOptions,
    time_offset_ms: int = 0,
) -> tuple[list[tuple[int, int, bytes]], int]:
    bpm = float(options.bpm)
    beat_interval = parse_beat_interval(options.beat_interval)
    hit_objects: list[tuple[int, int, bytes]] = []
    holding_starts: list[int | None] = [None] * options.lanes

    for tick in range(pattern.total_ticks):
        for lane in range(options.lanes):
            x = osu_x_for_column(lane, options.lanes).decode("ascii")
            time_ms = osu_time_for_tick(tick, bpm, beat_interval) + time_offset_ms
            if pattern.visible_grid[lane][tick]:
                hit_objects.append((time_ms, lane, f"{x},192,{time_ms},1,0,0:0:0:0:\r\n".encode("ascii")))

            if not pattern.long_grid[lane][tick]:
                continue
            if holding_starts[lane] is None:
                holding_starts[lane] = time_ms
            else:
                start_time = holding_starts[lane]
                hit_objects.append((start_time, lane, f"{x},192,{start_time},128,0,{time_ms}:0:0:0:0:\r\n".encode("ascii")))
                holding_starts[lane] = None

    chart_end_ms = osu_time_for_tick(pattern.total_ticks, bpm, beat_interval) + time_offset_ms
    return sorted(hit_objects), chart_end_ms


def make_random_osu_bytes(options: RandomNoteOptions) -> tuple[bytes, int, int, int, float]:
    bpm = float(options.bpm)
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("BPM must be greater than 0")
    wav_filename = validate_wav_filename(options.wav_filename)
    pattern = make_random_note_pattern(options)
    beat_interval = parse_beat_interval(options.beat_interval)
    beat_length = 60000.0 / bpm
    beat_length_text = f"{beat_length:.8f}".rstrip("0").rstrip(".")
    chart_end_ms = osu_time_for_tick(pattern.total_ticks, bpm, beat_interval)

    title = options.title.strip() or "Random Notes"
    lines: list[bytes] = [
        b"osu file format v14\r\n",
        b"\r\n",
        b"[General]\r\n",
        f"AudioFilename: {wav_filename}\r\n".encode("utf-8"),
        b"Mode: 3\r\n",
        b"SampleSet: Normal\r\n",
        b"\r\n",
        b"[Metadata]\r\n",
        f"Title:{title}\r\n".encode("utf-8"),
        f"TitleUnicode:{title}\r\n".encode("utf-8"),
        b"Artist:BMS Decalcomanie Tool\r\n",
        b"ArtistUnicode:BMS Decalcomanie Tool\r\n",
        b"Creator:BMS Decalcomanie Tool\r\n",
        f"Version:Random {options.lanes}K\r\n".encode("ascii"),
        b"\r\n",
        b"[Difficulty]\r\n",
        b"HPDrainRate:5\r\n",
        f"CircleSize:{options.lanes}\r\n".encode("ascii"),
        b"OverallDifficulty:5\r\n",
        b"ApproachRate:5\r\n",
        b"SliderMultiplier:1\r\n",
        b"SliderTickRate:1\r\n",
        b"\r\n",
        b"[TimingPoints]\r\n",
        f"0,{beat_length_text},4,1,0,100,1,0\r\n".encode("ascii"),
        b"\r\n",
        b"[HitObjects]\r\n",
    ]

    hit_objects, _chart_end_ms = build_random_osu_hitobject_lines(pattern, options)
    for _time_ms, _lane, hit_object in hit_objects:
        lines.append(hit_object)

    return (
        b"".join(lines),
        pattern.visible_notes,
        pattern.long_note_starts,
        pattern.long_note_ends,
        max(1.0, chart_end_ms / 1000.0 + 1.0),
    )


def make_random_osu_clipboard_bytes(options: RandomNoteOptions, time_offset_ms: int = 0) -> tuple[bytes, int, int, int]:
    bpm = float(options.bpm)
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("BPM must be greater than 0")
    offset = int(time_offset_ms)
    if offset < 0:
        raise ValueError("osu clipboard start time must be 0 or greater")
    pattern = make_random_note_pattern(options)
    hit_objects, _chart_end_ms = build_random_osu_hitobject_lines(pattern, options, offset)
    if not hit_objects:
        raise ValueError("random generation produced no osu hit objects")
    return (
        b"".join(hit_object for _time_ms, _lane, hit_object in hit_objects),
        pattern.visible_notes,
        pattern.long_note_starts,
        pattern.long_note_ends,
    )


def osu_hitobject_time(line: bytes) -> int | None:
    parts = body_without_newline(line).split(b",", 4)
    if len(parts) < 3:
        return None
    try:
        return int(parts[2].strip())
    except ValueError:
        return None


def osu_file_mode_and_keys(raw: bytes) -> tuple[int | None, int | None, bool]:
    section = b""
    mode: int | None = None
    circle_size: int | None = None
    has_hitobjects = False
    for line in raw.splitlines(keepends=True):
        body = body_without_newline(line).strip()
        if body.startswith(b"[") and body.endswith(b"]"):
            section = body.lower()
            if section == b"[hitobjects]":
                has_hitobjects = True
            continue
        if section == b"[general]":
            value = parse_osu_scalar(line, b"Mode")
            if value is not None:
                try:
                    mode = int(value)
                except ValueError:
                    pass
        elif section == b"[difficulty]":
            value = parse_osu_scalar(line, b"CircleSize")
            if value is not None:
                try:
                    circle_size = int(float(value))
                except ValueError:
                    pass
    return mode, circle_size, has_hitobjects


def insert_osu_hitobjects(raw: bytes, hitobjects: bytes, expected_keys: int) -> tuple[bytes, int]:
    mode, circle_size, has_hitobjects = osu_file_mode_and_keys(raw)
    if mode != 3:
        raise ValueError("target .osu file is not osu!mania Mode:3")
    if circle_size != expected_keys:
        raise ValueError(f"target .osu CircleSize:{circle_size} does not match key count {expected_keys}")
    if not has_hitobjects:
        raise ValueError("target .osu file has no [HitObjects] section")

    new_lines = [line + b"\r\n" for line in hitobjects.splitlines() if line.strip()]
    if not new_lines:
        raise ValueError("no generated hit objects to insert")

    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    prefix: list[bytes] = []
    existing_hitobjects: list[bytes] = []
    suffix: list[bytes] = []
    section = b""
    hitobjects_seen = False
    suffix_started = False

    for line in raw.splitlines(keepends=True):
        body = body_without_newline(line)
        stripped = body.strip()
        if stripped.startswith(b"[") and stripped.endswith(b"]"):
            section = stripped.lower()
            if section == b"[hitobjects]":
                hitobjects_seen = True
                prefix.append(body + newline)
                continue
            if hitobjects_seen:
                suffix_started = True
                suffix.append(line)
                continue

        if section == b"[hitobjects]" and stripped and not stripped.startswith(b"//"):
            existing_hitobjects.append(body + b"\r\n")
            continue

        if suffix_started:
            suffix.append(line)
        elif not hitobjects_seen:
            prefix.append(line)
        else:
            prefix.append(line)

    all_hitobjects = existing_hitobjects + new_lines
    sortable = [(osu_hitobject_time(line), index, line) for index, line in enumerate(all_hitobjects)]
    sortable.sort(key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0, item[1]))
    sorted_hitobjects = [line for _time, _index, line in sortable]
    return b"".join(prefix + sorted_hitobjects + suffix), len(new_lines)


def apply_random_osu_section_file(target: Path, options: RandomNoteOptions, start_time_ms: int) -> tuple[int, int, int, int, Path | None]:
    target = target.resolve()
    if target.suffix.lower() not in OSU_EXTENSIONS:
        raise ValueError("target for random osu insert must be a .osu file")
    if not target.exists():
        raise FileNotFoundError(f"target .osu file does not exist: {target}")

    clipboard_bytes, visible_notes, long_starts, long_ends = make_random_osu_clipboard_bytes(options, start_time_ms)
    raw = target.read_bytes()
    updated, inserted = insert_osu_hitobjects(raw, clipboard_bytes, options.lanes)

    backup = target.with_suffix(target.suffix + ".bak")
    backup_written: Path | None = None
    if not backup.exists():
        backup.write_bytes(raw)
        backup_written = backup
    target.write_bytes(updated)
    return inserted, visible_notes, long_starts, long_ends, backup_written


def write_silent_wav(path: Path, duration_seconds: float = 0.05) -> None:
    sample_rate = 44100
    sample_count = max(1, int(sample_rate * duration_seconds))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * sample_count)


def generate_random_bms_file(output: Path, options: RandomNoteOptions) -> RandomNoteResult:
    output = output.resolve()
    if output.suffix.lower() not in BMS_EXTENSIONS:
        raise ValueError("random generator output must be a .bms/.bme/.bml/.pms file")
    if output.exists() and not options.overwrite:
        raise FileExistsError(f"output already exists: {output}")

    raw, visible_notes, long_note_starts, long_note_ends = make_random_bms_bytes(options)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)

    wav_filename = validate_wav_filename(options.wav_filename)
    silence_wav = output.parent / wav_filename
    silence_wav_created = False
    if not silence_wav.exists():
        write_silent_wav(silence_wav)
        silence_wav_created = True

    return RandomNoteResult(
        output=output,
        visible_notes=visible_notes,
        long_note_starts=long_note_starts,
        long_note_ends=long_note_ends,
        silence_wav=silence_wav,
        silence_wav_created=silence_wav_created,
    )


def generate_random_osu_file(output: Path, options: RandomNoteOptions) -> RandomNoteResult:
    output = output.resolve()
    if output.suffix.lower() not in OSU_EXTENSIONS:
        raise ValueError("random osu generator output must be a .osu file")
    if output.exists() and not options.overwrite:
        raise FileExistsError(f"output already exists: {output}")

    raw, visible_notes, long_note_starts, long_note_ends, audio_duration_seconds = make_random_osu_bytes(options)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)

    wav_filename = validate_wav_filename(options.wav_filename)
    silence_wav = output.parent / wav_filename
    silence_wav_created = False
    if not silence_wav.exists():
        write_silent_wav(silence_wav, audio_duration_seconds)
        silence_wav_created = True

    return RandomNoteResult(
        output=output,
        visible_notes=visible_notes,
        long_note_starts=long_note_starts,
        long_note_ends=long_note_ends,
        silence_wav=silence_wav,
        silence_wav_created=silence_wav_created,
    )


def generate_random_chart_file(output: Path, options: RandomNoteOptions) -> RandomNoteResult:
    suffix = output.suffix.lower()
    if suffix in BMS_EXTENSIONS:
        return generate_random_bms_file(output, options)
    if suffix in OSU_EXTENSIONS:
        return generate_random_osu_file(output, options)
    raise ValueError("random generator output must be a .bms/.bme/.bml/.pms or .osu file")


def osu_column_from_x(x_value: int, key_count: int) -> int:
    column = int((x_value * key_count) / 512)
    return max(0, min(key_count - 1, column))


def osu_x_for_column(column: int, key_count: int) -> bytes:
    return str(int((column + 0.5) * 512 / key_count)).encode("ascii")


def parse_osu_scalar(line: bytes, key: bytes) -> bytes | None:
    body = body_without_newline(line).strip()
    prefix = key + b":"
    if body.lower().startswith(prefix.lower()):
        return body[len(prefix) :].strip()
    return None


def convert_osu_hitobject_line(line: bytes) -> tuple[list[bytes], bool]:
    newline = newline_of(line)
    body = body_without_newline(line)
    parts = body.split(b",", 5)
    if len(parts) < 5:
        return [line], False

    try:
        source_x = int(parts[0].strip())
    except ValueError:
        return [line], False

    source_column = osu_column_from_x(source_x, 5)
    left_column = source_column
    right_column = 9 - source_column
    rest = b",".join(parts[1:])

    left_line = osu_x_for_column(left_column, 10) + b"," + rest + newline
    right_line = osu_x_for_column(right_column, 10) + b"," + rest + newline
    return [left_line, right_line], True


def convert_osu_bytes(raw: bytes, options: ConvertOptions) -> tuple[bytes, int, int, list[str]]:
    lines = raw.splitlines(keepends=True)
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    section = b""
    mode: int | None = None
    circle_size: int | None = None
    has_hitobjects = False

    for line in lines:
        body = body_without_newline(line).strip()
        if body.startswith(b"[") and body.endswith(b"]"):
            section = body.lower()
            if section == b"[hitobjects]":
                has_hitobjects = True
            continue

        if section == b"[general]":
            value = parse_osu_scalar(line, b"Mode")
            if value is not None:
                try:
                    mode = int(value)
                except ValueError:
                    pass
        elif section == b"[difficulty]":
            value = parse_osu_scalar(line, b"CircleSize")
            if value is not None:
                try:
                    circle_size = int(float(value))
                except ValueError:
                    pass

    if mode != 3:
        raise ValueError(".osu file is not osu!mania Mode:3")
    if circle_size != 5:
        raise ValueError(".osu file must be osu!mania CircleSize:5")
    if not has_hitobjects:
        raise ValueError(".osu file has no [HitObjects] section")

    section = b""
    result: list[bytes] = []
    mirrored_objects = 0
    hitobject_converted = False
    version_updated = False
    circle_size_updated = False
    warnings: list[str] = []

    for line in lines:
        body = body_without_newline(line)
        stripped = body.strip()
        if stripped.startswith(b"[") and stripped.endswith(b"]"):
            section = stripped.lower()
            result.append(line)
            continue

        if section == b"[metadata]":
            value = parse_osu_scalar(line, b"Version")
            if value is not None and not version_updated:
                suffix = b" [10K Decal]"
                if suffix.lower() not in value.lower():
                    result.append(b"Version:" + value + suffix + newline_of(line))
                else:
                    result.append(line)
                version_updated = True
                continue

        if section == b"[difficulty]":
            value = parse_osu_scalar(line, b"CircleSize")
            if value is not None:
                result.append(b"CircleSize:10" + newline_of(line))
                circle_size_updated = True
                continue

        if section == b"[hitobjects]" and stripped and not stripped.startswith(b"//"):
            converted_lines, converted = convert_osu_hitobject_line(line)
            result.extend(converted_lines)
            if converted:
                mirrored_objects += 1
                hitobject_converted = True
            else:
                warnings.append("skipped malformed osu hit object line")
            continue

        result.append(line)

    if not circle_size_updated:
        raise ValueError(".osu file has no CircleSize line")
    if not hitobject_converted:
        raise ValueError(".osu file has no convertible hit objects")
    if not raw.endswith((b"\n", b"\r\n")) and result and result[-1].endswith((b"\n", b"\r\n")):
        result[-1] = body_without_newline(result[-1])
    if not result:
        result.append(newline)

    return b"".join(result), mirrored_objects, 0, warnings


def make_osu_editor_clipboard_bytes(raw: bytes) -> tuple[bytes, int, list[str]]:
    lines = raw.splitlines(keepends=True)
    section = b""
    mode: int | None = None
    circle_size: int | None = None
    has_hitobjects = False

    for line in lines:
        body = body_without_newline(line).strip()
        if body.startswith(b"[") and body.endswith(b"]"):
            section = body.lower()
            if section == b"[hitobjects]":
                has_hitobjects = True
            continue

        if section == b"[general]":
            value = parse_osu_scalar(line, b"Mode")
            if value is not None:
                try:
                    mode = int(value)
                except ValueError:
                    pass
        elif section == b"[difficulty]":
            value = parse_osu_scalar(line, b"CircleSize")
            if value is not None:
                try:
                    circle_size = int(float(value))
                except ValueError:
                    pass

    if mode != 3:
        raise ValueError(".osu file is not osu!mania Mode:3")
    if circle_size != 5:
        raise ValueError(".osu file must be osu!mania CircleSize:5")
    if not has_hitobjects:
        raise ValueError(".osu file has no [HitObjects] section")

    section = b""
    clipboard_lines: list[bytes] = []
    mirrored_objects = 0
    warnings: list[str] = []

    for line in lines:
        body = body_without_newline(line)
        stripped = body.strip()
        if stripped.startswith(b"[") and stripped.endswith(b"]"):
            section = stripped.lower()
            continue

        if section == b"[hitobjects]" and stripped and not stripped.startswith(b"//"):
            converted_lines, converted = convert_osu_hitobject_line(line)
            if converted:
                clipboard_lines.extend(body_without_newline(converted_line) + b"\r\n" for converted_line in converted_lines)
                mirrored_objects += 1
            else:
                warnings.append("skipped malformed osu hit object line")

    if not clipboard_lines:
        raise ValueError(".osu file has no convertible hit objects")
    return b"".join(clipboard_lines), mirrored_objects, warnings


def convert_bytes(raw: bytes, options: ConvertOptions) -> tuple[bytes, int, int, list[str]]:
    lines = raw.splitlines(keepends=True)
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    mapping = mirror_map(options)
    mirror_targets = set(mapping.values())
    additions: dict[tuple[bytes, bytes], bytes] = {}
    existing_targets: dict[tuple[bytes, bytes], bytes] = {}
    source_positions: dict[tuple[bytes, bytes], int] = {}
    warnings: list[str] = []
    collision_count = 0
    mirrored_lines = 0

    for line_index, line in enumerate(lines):
        parsed = parse_chart_line(line)
        if parsed is None:
            continue
        measure, channel, data = parsed
        if len(data) % 2 != 0:
            warnings.append(f"skipped #{measure.decode()}{channel.decode()}: odd object-data length")
            continue
        if channel in mapping:
            target_key = (measure, mapping[channel])
            additions[target_key], collisions = merge_note_data(additions.get(target_key), data)
            collision_count += collisions
            source_positions.setdefault(target_key, line_index)
            mirrored_lines += 1
        elif channel in mirror_targets:
            target_key = (measure, channel)
            existing_targets[target_key], collisions = merge_note_data(existing_targets.get(target_key), data)
            collision_count += collisions

    final_targets: dict[tuple[bytes, bytes], bytes] = {}
    for key, data in existing_targets.items():
        final_targets[key] = data
    for key, data in additions.items():
        final_targets[key], collisions = merge_note_data(final_targets.get(key), data)
        collision_count += collisions

    emitted_targets: set[tuple[bytes, bytes]] = set()
    result: list[bytes] = []
    player_seen = False
    has_player = any(PLAYER_RE.match(body_without_newline(line)) for line in lines)
    has_key_extension = any(KEY_EXTENSION_RE.match(body_without_newline(line).strip()) for line in lines)
    key_extension_emitted = False
    key_extension_line = bms_key_extension_line(10, newline)

    if options.set_player_double and not has_player:
        result.append(b"#PLAYER 3" + newline)
    if key_extension_line is not None and not has_player and not has_key_extension:
        result.append(key_extension_line)

    for line in lines:
        body = body_without_newline(line)
        parsed = parse_chart_line(line)

        if PLAYER_RE.match(body):
            player_newline = newline_of(line)
            result.append((b"#PLAYER 3" if options.set_player_double else body) + player_newline)
            player_seen = True
            if key_extension_line is not None and not has_key_extension and not key_extension_emitted:
                result.append(bms_key_extension_line(10, player_newline or newline) or key_extension_line)
                key_extension_emitted = True
            continue

        if KEY_EXTENSION_RE.match(body.strip()):
            if key_extension_line is not None and not key_extension_emitted:
                result.append(bms_key_extension_line(10, newline_of(line) or newline) or key_extension_line)
                key_extension_emitted = True
            continue

        if parsed is not None:
            measure, channel, _data = parsed
            target_key = (measure, channel)
            if target_key in final_targets:
                if target_key not in emitted_targets:
                    result.append(build_chart_line(measure, channel, final_targets[target_key], newline_of(line) or newline))
                    emitted_targets.add(target_key)
                continue

        result.append(line)

    pending_keys = [key for key in final_targets if key not in emitted_targets]
    if pending_keys:
        if result and not result[-1].endswith((b"\n", b"\r\n")):
            result[-1] += newline
        for measure, channel in sorted(pending_keys):
            result.append(build_chart_line(measure, channel, final_targets[(measure, channel)], newline))

    if options.set_player_double and player_seen is False:
        pass

    return b"".join(result), mirrored_lines, collision_count, warnings


def convert_file(source: Path, options: ConvertOptions) -> ConvertResult:
    source = source.resolve()
    if not source.exists():
        return ConvertResult(source=source, output=None, warnings=["source file does not exist"])
    suffix = source.suffix.lower()
    if suffix not in DEFAULT_EXTENSIONS:
        return ConvertResult(source=source, output=None, warnings=["not a supported BMS/osu file"])

    output_path = unique_output_path(source, options.output_dir, options.overwrite)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    raw = source.read_bytes()
    if suffix in BMS_EXTENSIONS:
        converted, mirrored_lines, collisions, warnings = convert_bytes(raw, options)
    elif suffix in OSU_EXTENSIONS:
        converted, mirrored_lines, collisions, warnings = convert_osu_bytes(raw, options)
    else:
        return ConvertResult(source=source, output=None, warnings=["not a supported BMS/osu file"])
    output_path.write_bytes(converted)

    return ConvertResult(
        source=source,
        output=output_path,
        mirrored_lines=mirrored_lines,
        collision_count=collisions,
        warnings=warnings,
    )


def iter_chart_files(paths: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            for item in sorted(path.rglob("*")):
                if item.is_file() and item.suffix.lower() in DEFAULT_EXTENSIONS:
                    found.append(item)
        elif path.is_file() and path.suffix.lower() in DEFAULT_EXTENSIONS:
            found.append(path)
    return found


def iter_bms_files(paths: Iterable[Path]) -> list[Path]:
    return iter_chart_files(paths)


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("BMS/osu 5K to 10K Decalcomanie Tool")
    root.geometry("840x580")
    root.minsize(760, 500)

    selected_files: list[Path] = []
    output_dir_var = tk.StringVar(value="")
    set_player_var = tk.BooleanVar(value=True)
    mirror_ln_var = tk.BooleanVar(value=True)
    mirror_hidden_var = tk.BooleanVar(value=False)

    def refresh_list() -> None:
        listbox.delete(0, tk.END)
        for file_path in selected_files:
            listbox.insert(tk.END, str(file_path))

    def add_paths(paths: Iterable[str]) -> None:
        existing = {path.resolve() for path in selected_files}
        for raw_path in paths:
            path = Path(raw_path)
            candidates = iter_chart_files([path])
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved not in existing:
                    selected_files.append(resolved)
                    existing.add(resolved)
        refresh_list()

    def add_files() -> None:
        paths = filedialog.askopenfilenames(
            title="Choose BMS or osu!mania files",
            filetypes=[
                ("BMS/osu files", "*.bms *.bme *.bml *.pms *.osu"),
                ("BMS files", "*.bms *.bme *.bml *.pms"),
                ("osu!mania files", "*.osu"),
                ("All files", "*.*"),
            ],
        )
        add_paths(paths)

    def add_folder() -> None:
        folder = filedialog.askdirectory(title="Choose a folder containing BMS or osu files")
        if folder:
            add_paths([folder])

    def choose_output() -> None:
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            output_dir_var.set(folder)

    def remove_selected() -> None:
        indexes = list(listbox.curselection())
        for index in reversed(indexes):
            selected_files.pop(index)
        refresh_list()

    def clear_files() -> None:
        selected_files.clear()
        refresh_list()

    def append_log(text: str) -> None:
        log_box.configure(state="normal")
        log_box.insert(tk.END, text + "\n")
        log_box.see(tk.END)
        log_box.configure(state="disabled")
        root.update_idletasks()

    def convert_selected() -> None:
        if not selected_files:
            messagebox.showwarning("No files", "Add one or more .bms/.bme/.bml/.pms/.osu files first.")
            return

        output_dir = Path(output_dir_var.get()).resolve() if output_dir_var.get().strip() else None
        options = ConvertOptions(
            output_dir=output_dir,
            set_player_double=set_player_var.get(),
            mirror_long_notes=mirror_ln_var.get(),
            mirror_invisible=mirror_hidden_var.get(),
            overwrite=False,
        )

        append_log("Starting conversion...")
        ok_count = 0
        warn_count = 0
        for source in selected_files:
            try:
                result = convert_file(source, options)
            except Exception as exc:  # noqa: BLE001 - GUI should report and continue.
                append_log(f"FAIL  {source}: {exc}")
                warn_count += 1
                continue

            if result.output is None:
                append_log(f"SKIP  {source}: {'; '.join(result.warnings)}")
                warn_count += 1
                continue

            ok_count += 1
            append_log(
                f"OK    {source.name} -> {result.output} "
                f"(mirrored {result.mirrored_lines} lines, collisions {result.collision_count})"
            )
            for warning in result.warnings:
                append_log(f"WARN  {source.name}: {warning}")
                warn_count += 1

        append_log(f"Done. Converted {ok_count} file(s), warnings {warn_count}.")
        if ok_count:
            messagebox.showinfo("Conversion complete", f"Converted {ok_count} file(s).")

    def copy_osu_editor_clipboard_selected() -> None:
        osu_files = [source for source in selected_files if source.suffix.lower() in OSU_EXTENSIONS]
        if not osu_files:
            messagebox.showwarning("No osu files", "Add one or more .osu files first.")
            return

        append_log("Creating osu editor clipboard paste data...")
        chunks: list[bytes] = []
        ok_count = 0
        warn_count = 0
        mirrored_count = 0
        failure_messages: list[str] = []
        for source in osu_files:
            try:
                clipboard_bytes, mirrored_objects, warnings = make_osu_editor_clipboard_bytes(source.read_bytes())
            except Exception as exc:  # noqa: BLE001 - GUI should report and continue.
                append_log(f"FAIL  clipboard {source}: {exc}")
                failure_messages.append(f"{source.name}: {exc}")
                warn_count += 1
                continue

            chunks.append(clipboard_bytes)
            ok_count += 1
            mirrored_count += mirrored_objects
            append_log(f"OK    clipboard {source.name} (mirrored {mirrored_objects} hit objects)")
            for warning in warnings:
                append_log(f"WARN  {source.name}: {warning}")
                warn_count += 1

        if not chunks:
            detail = failure_messages[0] if failure_messages else "No convertible osu hit objects were found."
            messagebox.showerror("Clipboard failed", f"No osu editor paste data was created.\n\n{detail}")
            return

        clipboard_text = b"".join(chunks).decode("utf-8", errors="replace")
        root.clipboard_clear()
        root.clipboard_append(clipboard_text)
        root.update()
        append_log(f"Copied osu editor paste data from {ok_count} file(s), mirrored {mirrored_count} hit objects, warnings {warn_count}.")
        messagebox.showinfo("Clipboard ready", f"Copied {mirrored_count} mirrored hit object(s) for osu editor paste.")

    def open_random_generator() -> None:
        window = tk.Toplevel(root)
        window.title("Random Chart Generator")
        window.geometry("620x680")
        window.minsize(580, 640)

        title_var = tk.StringVar(value="Random Notes")
        bpm_var = tk.StringVar(value="120")
        beat_interval_var = tk.StringVar(value="0.25")
        key_count_var = tk.StringVar(value="10")
        generation_count_var = tk.StringVar(value="256")
        min_notes_var = tk.StringVar(value="0")
        max_notes_var = tk.StringVar(value="10")
        single_var = tk.StringVar(value="25")
        start_var = tk.StringVar(value="50")
        rest_var = tk.StringVar(value="25")
        end_var = tk.StringVar(value="25")
        keep_var = tk.StringVar(value="75")
        seed_var = tk.StringVar(value="")
        start_time_var = tk.StringVar(value="0")
        output_var = tk.StringVar(value="")
        target_osu_var = tk.StringVar(value="")

        content = ttk.Frame(window, padding=12)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)

        def add_entry(row: int, label: str, variable: tk.StringVar) -> None:
            ttk.Label(content, text=label).grid(row=row, column=0, sticky=tk.W, pady=3)
            ttk.Entry(content, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, pady=3, padx=(8, 0))

        add_entry(0, "Title", title_var)
        add_entry(1, "BPM", bpm_var)
        add_entry(2, "Beat interval", beat_interval_var)
        add_entry(3, "Key count", key_count_var)
        add_entry(4, "Generation count", generation_count_var)
        add_entry(5, "Minimum notes/beat", min_notes_var)
        add_entry(6, "Maximum notes/beat", max_notes_var)
        add_entry(7, "1a empty: single note weight", single_var)
        add_entry(8, "2a empty: long-note start weight", start_var)
        add_entry(9, "3a empty: no note weight", rest_var)
        add_entry(10, "1b holding: long-note end weight", end_var)
        add_entry(11, "2b holding: keep holding weight", keep_var)
        add_entry(12, "Seed (optional)", seed_var)
        add_entry(13, "Clipboard/file start time (ms)", start_time_var)

        output_row = ttk.Frame(content)
        output_row.grid(row=14, column=0, columnspan=2, sticky=tk.EW, pady=(10, 3))
        output_row.columnconfigure(1, weight=1)
        ttk.Label(output_row, text="Output chart").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(output_row, textvariable=output_var).grid(row=0, column=1, sticky=tk.EW, padx=(8, 8))

        def browse_random_output() -> None:
            path = filedialog.asksaveasfilename(
                parent=window,
                title="Save random chart",
                defaultextension=".bms",
                filetypes=[
                    ("BMS/osu files", "*.bms *.bme *.bml *.pms *.osu"),
                    ("BMS files", "*.bms *.bme *.bml *.pms"),
                    ("osu!mania files", "*.osu"),
                    ("All files", "*.*"),
                ],
            )
            if path:
                output_var.set(path)

        ttk.Button(output_row, text="Browse", command=browse_random_output).grid(row=0, column=2)

        target_osu_row = ttk.Frame(content)
        target_osu_row.grid(row=15, column=0, columnspan=2, sticky=tk.EW, pady=3)
        target_osu_row.columnconfigure(1, weight=1)
        ttk.Label(target_osu_row, text="Target osu file").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(target_osu_row, textvariable=target_osu_var).grid(row=0, column=1, sticky=tk.EW, padx=(8, 8))

        def browse_target_osu() -> None:
            path = filedialog.askopenfilename(
                parent=window,
                title="Choose target osu!mania file",
                filetypes=[
                    ("osu!mania files", "*.osu"),
                    ("All files", "*.*"),
                ],
            )
            if path:
                target_osu_var.set(path)

        ttk.Button(target_osu_row, text="Browse", command=browse_target_osu).grid(row=0, column=2)

        def random_start_time_ms() -> int:
            start_time_ms = int(start_time_var.get())
            if start_time_ms < 0:
                raise ValueError("clipboard/file start time must be 0 or greater")
            return start_time_ms

        def build_random_options(overwrite: bool = False) -> RandomNoteOptions:
            seed_text = seed_var.get().strip()
            return RandomNoteOptions(
                title=title_var.get().strip() or "Random Notes",
                bpm=float(bpm_var.get()),
                beat_interval=beat_interval_var.get(),
                generation_count=int(generation_count_var.get()),
                lanes=int(key_count_var.get()),
                min_notes_per_beat=int(min_notes_var.get()),
                max_notes_per_beat=int(max_notes_var.get()),
                empty_single_weight=float(single_var.get()),
                empty_long_start_weight=float(start_var.get()),
                empty_rest_weight=float(rest_var.get()),
                holding_long_end_weight=float(end_var.get()),
                holding_keep_weight=float(keep_var.get()),
                seed=int(seed_text) if seed_text else None,
                overwrite=overwrite,
            )

        def generate_random() -> None:
            output_text = output_var.get().strip()
            if not output_text:
                browse_random_output()
                output_text = output_var.get().strip()
            if not output_text:
                return

            output_path = Path(output_text)
            overwrite = False
            if output_path.exists():
                overwrite = messagebox.askyesno(
                    "Overwrite file?",
                    f"{output_path} already exists.\nOverwrite it?",
                    parent=window,
                )
                if not overwrite:
                    return

            try:
                options = build_random_options(overwrite)
                result = generate_random_chart_file(output_path, options)
            except Exception as exc:  # noqa: BLE001 - GUI should report validation errors.
                messagebox.showerror("Random generation failed", str(exc), parent=window)
                return

            append_log(
                f"OK    random chart -> {result.output} "
                f"(single {result.visible_notes}, LN {result.long_note_starts}/{result.long_note_ends})"
            )
            if result.silence_wav_created and result.silence_wav is not None:
                append_log(f"OK    wrote silent WAV -> {result.silence_wav}")
            messagebox.showinfo("Random generation complete", f"Created {result.output}", parent=window)

        def generate_random_clipboard() -> None:
            try:
                options = build_random_options(False)
                start_time_ms = random_start_time_ms()
                clipboard_bytes, visible_notes, long_starts, long_ends = make_random_osu_clipboard_bytes(options, start_time_ms)
            except Exception as exc:  # noqa: BLE001 - GUI should report validation errors.
                messagebox.showerror("Random clipboard failed", str(exc), parent=window)
                return

            clipboard_text = clipboard_bytes.decode("utf-8", errors="replace")
            window.clipboard_clear()
            window.clipboard_append(clipboard_text)
            window.update()
            append_log(
                f"OK    random clipboard -> osu HitObject rows "
                f"(start {start_time_ms} ms, single {visible_notes}, LN {long_starts}/{long_ends})"
            )
            messagebox.showinfo(
                "Random clipboard ready",
                f"Copied {visible_notes} single note(s) and {long_starts} long note(s) starting at {start_time_ms} ms.",
                parent=window,
            )

        def apply_random_to_osu_file() -> None:
            target_text = target_osu_var.get().strip()
            if not target_text:
                browse_target_osu()
                target_text = target_osu_var.get().strip()
            if not target_text:
                return

            try:
                options = build_random_options(False)
                start_time_ms = random_start_time_ms()
                inserted, visible_notes, long_starts, long_ends, backup = apply_random_osu_section_file(
                    Path(target_text),
                    options,
                    start_time_ms,
                )
            except Exception as exc:  # noqa: BLE001 - GUI should report validation errors.
                messagebox.showerror("Random osu insert failed", str(exc), parent=window)
                return

            append_log(
                f"OK    random osu insert -> {target_text} "
                f"(start {start_time_ms} ms, inserted {inserted}, single {visible_notes}, LN {long_starts}/{long_ends})"
            )
            if backup is not None:
                append_log(f"OK    backup -> {backup}")
            messagebox.showinfo(
                "Random osu insert complete",
                f"Inserted {inserted} generated hit object(s) into the target .osu file.",
                parent=window,
            )

        ttk.Label(
            content,
            text="Creates files, copies HitObject rows, or inserts generated rows into an existing osu!mania file.",
        ).grid(row=16, column=0, columnspan=2, sticky=tk.W, pady=(8, 8))
        ttk.Button(content, text="Generate random chart", command=generate_random).grid(
            row=17,
            column=0,
            columnspan=2,
            sticky=tk.EW,
        )
        ttk.Button(content, text="Generate random clipboard", command=generate_random_clipboard).grid(
            row=18,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(8, 0),
        )
        ttk.Button(content, text="Apply random section to osu file", command=apply_random_to_osu_file).grid(
            row=19,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(8, 0),
        )

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)

    top_buttons = ttk.Frame(frame)
    top_buttons.pack(fill=tk.X)
    ttk.Button(top_buttons, text="Add files", command=add_files).pack(side=tk.LEFT)
    ttk.Button(top_buttons, text="Add folder", command=add_folder).pack(side=tk.LEFT, padx=(8, 0))
    ttk.Button(top_buttons, text="Remove selected", command=remove_selected).pack(side=tk.LEFT, padx=(8, 0))
    ttk.Button(top_buttons, text="Clear", command=clear_files).pack(side=tk.LEFT, padx=(8, 0))

    listbox = tk.Listbox(frame, selectmode=tk.EXTENDED, height=10)
    listbox.pack(fill=tk.BOTH, expand=True, pady=(10, 10))

    output_frame = ttk.Frame(frame)
    output_frame.pack(fill=tk.X)
    ttk.Label(output_frame, text="Output folder").pack(side=tk.LEFT)
    ttk.Entry(output_frame, textvariable=output_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
    ttk.Button(output_frame, text="Browse", command=choose_output).pack(side=tk.LEFT)

    options_frame = ttk.LabelFrame(frame, text="Options", padding=8)
    options_frame.pack(fill=tk.X, pady=(10, 10))
    ttk.Checkbutton(options_frame, text="BMS: set #PLAYER 3 for double-play 10K", variable=set_player_var).pack(anchor=tk.W)
    ttk.Checkbutton(options_frame, text="BMS: mirror long-note channels 51-55 to 65-61", variable=mirror_ln_var).pack(anchor=tk.W)
    ttk.Checkbutton(options_frame, text="BMS: mirror invisible channels 31-35 to 45-41", variable=mirror_hidden_var).pack(anchor=tk.W)

    ttk.Button(frame, text="Convert to 10K decalcomanie", command=convert_selected).pack(fill=tk.X)
    ttk.Button(frame, text="Copy selected osu decal notes to clipboard", command=copy_osu_editor_clipboard_selected).pack(fill=tk.X, pady=(8, 0))
    ttk.Button(frame, text="Open random chart generator", command=open_random_generator).pack(fill=tk.X, pady=(8, 0))

    log_box = tk.Text(frame, height=8, state="disabled", wrap=tk.WORD)
    log_box.pack(fill=tk.BOTH, expand=False, pady=(10, 0))
    append_log("Add BMS or osu!mania 5K files, then click Convert. Empty output folder writes beside each source.")

    root.mainloop()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert 5K BMS/osu!mania files into mirrored 10K decalcomanie charts.")
    parser.add_argument("paths", nargs="*", type=Path, help="BMS/osu files or folders to convert. Empty launches the GUI.")
    parser.add_argument("-o", "--output-dir", type=Path, help="Directory for converted files.")
    parser.add_argument("--no-player-3", action="store_true", help="Do not set #PLAYER 3.")
    parser.add_argument("--no-ln", action="store_true", help="Do not mirror long-note channels 51-55.")
    parser.add_argument("--mirror-invisible", action="store_true", help="Also mirror invisible channels 31-35.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite the default output file if it exists.")
    random_group = parser.add_argument_group("random chart generator")
    random_group.add_argument("--random-output", type=Path, help="Create a new random BMS or osu!mania file instead of converting.")
    random_group.add_argument("--random-title", default="Random Notes", help="Title for --random-output.")
    random_group.add_argument("--bpm", type=float, default=120.0, help="BPM for --random-output.")
    random_group.add_argument("--beat-interval", default="0.25", help="Beat spacing for random notes, such as 1, 0.5, 0.25, or 1/8.")
    random_group.add_argument("--keys", type=int, default=10, help="Key count for random output, from 1 to 10.")
    random_group.add_argument("--generate-count", "--note-count", dest="generate_count", type=int, help="How many beat-interval positions to generate.")
    random_group.add_argument("--min-notes-per-beat", type=int, default=0, help="Minimum generated notes per beat position.")
    random_group.add_argument("--max-notes-per-beat", type=int, default=10, help="Maximum empty lanes allowed to roll non-3a per beat position.")
    random_group.add_argument("--measures", type=int, default=16, help="Fallback measure count when --generate-count is omitted.")
    random_group.add_argument("--weight-single", type=float, default=25.0, help="1a: empty lane single-note weight.")
    random_group.add_argument("--weight-ln-start", type=float, default=50.0, help="2a: empty lane long-note start weight.")
    random_group.add_argument("--weight-empty", type=float, default=25.0, help="3a: empty lane no-note weight.")
    random_group.add_argument("--weight-ln-end", type=float, default=25.0, help="1b: holding lane long-note end weight.")
    random_group.add_argument("--weight-ln-keep", type=float, default=75.0, help="2b: holding lane keep-holding weight.")
    random_group.add_argument("--seed", type=int, help="Optional random seed for repeatable output.")
    random_group.add_argument("--random-overwrite", action="store_true", help="Allow --random-output to overwrite an existing file.")
    return parser


def run_random_cli(args: argparse.Namespace) -> int:
    if args.paths:
        print("--random-output does not use input paths.", file=sys.stderr)
        return 1

    options = RandomNoteOptions(
        title=args.random_title,
        bpm=args.bpm,
        beat_interval=args.beat_interval,
        measures=args.measures,
        generation_count=args.generate_count,
        lanes=args.keys,
        min_notes_per_beat=args.min_notes_per_beat,
        max_notes_per_beat=args.max_notes_per_beat,
        empty_single_weight=args.weight_single,
        empty_long_start_weight=args.weight_ln_start,
        empty_rest_weight=args.weight_empty,
        holding_long_end_weight=args.weight_ln_end,
        holding_keep_weight=args.weight_ln_keep,
        seed=args.seed,
        overwrite=args.random_overwrite,
    )
    try:
        result = generate_random_chart_file(args.random_output, options)
    except Exception as exc:  # noqa: BLE001 - CLI should report validation errors.
        print(f"FAIL random generation: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK random chart -> {result.output} "
        f"(single {result.visible_notes}, LN {result.long_note_starts}/{result.long_note_ends})"
    )
    if result.silence_wav_created and result.silence_wav is not None:
        print(f"OK silent WAV -> {result.silence_wav}")
    return 0


def run_cli(args: argparse.Namespace) -> int:
    options = ConvertOptions(
        output_dir=args.output_dir,
        set_player_double=not args.no_player_3,
        mirror_long_notes=not args.no_ln,
        mirror_invisible=args.mirror_invisible,
        overwrite=args.overwrite,
    )
    files = iter_chart_files(args.paths)
    if not files:
        print("No BMS/osu files found.", file=sys.stderr)
        return 1

    exit_code = 0
    for file_path in files:
        try:
            result = convert_file(file_path, options)
        except Exception as exc:  # noqa: BLE001 - CLI should continue for batch input.
            print(f"FAIL {file_path}: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        if result.output is None:
            print(f"SKIP {file_path}: {'; '.join(result.warnings)}", file=sys.stderr)
            exit_code = 1
            continue

        print(
            f"OK {file_path} -> {result.output} "
            f"(mirrored {result.mirrored_lines}, collisions {result.collision_count})"
        )
        for warning in result.warnings:
            print(f"WARN {file_path.name}: {warning}", file=sys.stderr)
            exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.random_output is not None:
        return run_random_cli(args)
    if not args.paths:
        launch_gui()
        return 0
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
