from __future__ import annotations

import argparse
import math
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import bms_decalcomanie_converter as base


APP_NAME = "Generator v1"


@dataclass
class GeneratorV1Options(base.RandomNoteOptions):
    source_bms: Path | None = None
    stair_pattern_chance: float = 12.5
    chord_pattern_chance: float = 0.0
    jack_pattern_chance: float = 0.0
    long_note_pattern_chance: float = 0.0
    other_key_pattern_chance: float = 0.0
    density_balance: bool = True
    density_window: int = 16
    target_density: float | None = None
    density_tolerance: float = 25.0
    density_strength: float = 100.0


@dataclass
class GeneratorV1Pattern(base.RandomNotePattern):
    stair_patterns: int = 0
    chord_patterns: int = 0
    jack_patterns: int = 0
    long_note_patterns: int = 0
    other_key_patterns: int = 0
    sparse_adjustments: int = 0
    dense_adjustments: int = 0


@dataclass
class GeneratorV1Result(base.RandomNoteResult):
    stair_patterns: int = 0
    chord_patterns: int = 0
    jack_patterns: int = 0
    long_note_patterns: int = 0
    other_key_patterns: int = 0
    sparse_adjustments: int = 0
    dense_adjustments: int = 0


@dataclass
class SourceBmsBgm:
    wav_lines: list[bytes]
    used_wav_ids: set[bytes]
    measure_groups: list[list[bytes]]
    reposition_measure_count: int


SOURCE_WAV_RE = re.compile(rb"^#WAV([0-9A-Za-z]{2})\s+(.+)$", re.IGNORECASE)
WAV_ID_CHARS = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def validate_percent(value: float, label: str) -> float:
    percent = float(value)
    if not math.isfinite(percent) or percent < 0 or percent > 100:
        raise ValueError(f"{label} must be between 0 and 100")
    return percent


def all_bms_object_ids() -> list[bytes]:
    return [
        bytes((left, right))
        for left in WAV_ID_CHARS
        for right in WAV_ID_CHARS
        if bytes((left, right)) != b"00"
    ]


def select_generator_note_id(requested_id: str, used_wav_ids: set[bytes]) -> bytes:
    requested = base.validate_note_object_id(requested_id)
    used_upper = {token.upper() for token in used_wav_ids}
    if requested not in used_upper:
        return requested
    for candidate in all_bms_object_ids():
        if candidate not in used_upper:
            return candidate
    raise ValueError("source BMS uses every WAV id; no free id remains for generated notes")


def is_bms_keysound_channel(channel: bytes) -> bool:
    if len(channel) != 2:
        return False
    return channel[:1] in {b"1", b"2", b"3", b"4", b"5", b"6"} and channel[1:2] in b"123456789"


def parse_source_bms_bgm(source_bms: Path) -> SourceBmsBgm:
    source = source_bms.resolve()
    if source.suffix.lower() not in base.BMS_EXTENSIONS:
        raise ValueError("source BMS for BGM must be a .bms/.bme/.bml/.pms file")
    if not source.exists():
        raise FileNotFoundError(f"source BMS for BGM does not exist: {source}")

    wav_lines: list[bytes] = []
    used_wav_ids: set[bytes] = set()
    bgm_by_measure: dict[int, list[bytes]] = {}
    last_keysound_measure: int | None = None

    for line in source.read_bytes().splitlines(keepends=True):
        body = base.body_without_newline(line).strip()
        wav_match = SOURCE_WAV_RE.match(body)
        if wav_match:
            wav_id = wav_match.group(1).upper()
            wav_lines.append(body + b"\r\n")
            used_wav_ids.add(wav_id)
            continue

        chart_line = base.parse_chart_line(line)
        if chart_line is None:
            continue
        measure, channel, data = chart_line
        measure_number = int(measure)
        if channel != b"01" and not is_bms_keysound_channel(channel):
            continue
        pairs = base.split_pairs(data)
        nonzero_pairs = [pair.upper() for pair in pairs if not base.is_zero_pair(pair)]
        if not nonzero_pairs:
            continue
        used_wav_ids.update(nonzero_pairs)
        if channel == b"01":
            bgm_by_measure.setdefault(measure_number, []).append(data)
        else:
            last_keysound_measure = max(last_keysound_measure or measure_number, measure_number)

    if not wav_lines:
        raise ValueError("source BMS for BGM has no #WAV definitions")
    if not bgm_by_measure:
        raise ValueError("source BMS for BGM has no #xxx01 background sound lines")

    first_measure = min(bgm_by_measure)
    last_measure = max(bgm_by_measure)
    measure_groups = [bgm_by_measure.get(measure, []) for measure in range(first_measure, last_measure + 1)]
    end_measure = last_keysound_measure if last_keysound_measure is not None else last_measure
    reposition_measure_count = max(1, end_measure - first_measure + 1)
    return SourceBmsBgm(
        wav_lines=wav_lines,
        used_wav_ids=used_wav_ids,
        measure_groups=measure_groups,
        reposition_measure_count=reposition_measure_count,
    )


def source_bgm_lines_for_measure(source_bgm: SourceBmsBgm, measure_index: int) -> list[bytes]:
    if not source_bgm.measure_groups:
        return []
    measure = f"{measure_index + 1:03d}".encode("ascii")
    source_group = source_bgm.measure_groups[measure_index % len(source_bgm.measure_groups)]
    return [base.build_chart_line(measure, b"01", data, b"\r\n") for data in source_group]


def validate_density_options(options: GeneratorV1Options) -> tuple[int, float, float, float | None]:
    window = int(options.density_window)
    if window < 1:
        raise ValueError("density window must be 1 or greater")
    tolerance = validate_percent(options.density_tolerance, "density tolerance")
    strength = validate_percent(options.density_strength, "density strength")
    target = None if options.target_density is None else float(options.target_density)
    if target is not None:
        if not math.isfinite(target):
            raise ValueError("target density must be a finite number")
        if target <= 0:
            target = None
        elif target > options.lanes:
            target = float(options.lanes)
    return window, tolerance, strength, target


def automatic_target_density(options: GeneratorV1Options, stair_chance: float) -> float:
    single_weight = base.validate_weight(options.empty_single_weight, "single-note")
    start_weight = base.validate_weight(options.empty_long_start_weight, "long-note start")
    rest_weight = base.validate_weight(options.empty_rest_weight, "empty")
    total = single_weight + start_weight + rest_weight
    if total <= 0:
        return max(0.25, min(float(options.lanes), 1.0))

    note_ratio = (single_weight + start_weight) / total
    target = options.lanes * note_ratio * 0.5
    target += min(1.0, stair_chance / 100.0)
    return max(0.25, min(float(options.lanes), target))


def recent_density(visible_grid: list[list[bool]], long_grid: list[list[bool]], tick: int, window: int) -> float:
    if tick <= 0:
        return 0.0
    start = max(0, tick - window)
    note_count = 0
    for index in range(start, tick):
        note_count += sum(1 for lane in range(len(visible_grid)) if visible_grid[lane][index])
        note_count += sum(1 for lane in range(len(long_grid)) if long_grid[lane][index])
    return note_count / (tick - start)


def density_state(recent: float, target: float, tolerance_percent: float, strength_percent: float) -> tuple[str, float]:
    tolerance = target * (tolerance_percent / 100.0)
    if recent < target - tolerance:
        raw = (target - tolerance - recent) / max(target, 1.0)
        return "sparse", min(1.0, raw * (strength_percent / 100.0))
    if recent > target + tolerance:
        raw = (recent - target - tolerance) / max(target, 1.0)
        return "dense", min(1.0, raw * (strength_percent / 100.0))
    return "stable", 0.0


def adjusted_empty_actions(
    single_weight: float,
    start_weight: float,
    rest_weight: float,
    state: str,
    intensity: float,
) -> list[tuple[str, float]]:
    if state == "stable" or intensity <= 0:
        return [("single", single_weight), ("start", start_weight), ("rest", rest_weight)]

    total = max(single_weight + start_weight + rest_weight, 1.0)
    note_total = single_weight + start_weight
    pressure = total * intensity

    if state == "sparse":
        if note_total > 0:
            single_add = pressure * (single_weight / note_total)
            start_add = pressure * (start_weight / note_total)
        else:
            single_add = pressure
            start_add = 0.0
        return [
            ("single", single_weight * (1.0 + intensity) + single_add),
            ("start", start_weight * (1.0 + intensity * 0.5) + start_add),
            ("rest", rest_weight * max(0.05, 1.0 - intensity)),
        ]

    return [
        ("single", single_weight * max(0.02, 1.0 - intensity)),
        ("start", start_weight * max(0.02, 1.0 - intensity)),
        ("rest", rest_weight * (1.0 + intensity) + pressure),
    ]


def adjusted_holding_actions(end_weight: float, keep_weight: float, state: str, intensity: float) -> list[tuple[str, float]]:
    if state == "stable" or intensity <= 0:
        return [("end", end_weight), ("keep", keep_weight)]

    total = max(end_weight + keep_weight, 1.0)
    pressure = total * intensity
    if state == "sparse":
        return [
            ("end", end_weight * (1.0 + intensity) + pressure),
            ("keep", keep_weight * max(0.05, 1.0 - intensity)),
        ]

    return [
        ("end", end_weight * max(0.02, 1.0 - intensity)),
        ("keep", keep_weight * (1.0 + intensity) + pressure),
    ]


def adjusted_stair_chance(stair_chance: float, state: str, intensity: float) -> float:
    if state == "dense":
        return stair_chance * max(0.0, 1.0 - intensity)
    if state == "sparse" and stair_chance > 0:
        return min(100.0, stair_chance * (1.0 + intensity))
    return stair_chance


def adjusted_pattern_chance(pattern_chance: float, state: str, intensity: float) -> float:
    return adjusted_stair_chance(pattern_chance, state, intensity)


def validate_generator_min_notes_per_beat(value: int, lane_count: int) -> int:
    minimum = int(value)
    if minimum < 0 or minimum > lane_count:
        raise ValueError("minimum notes per beat must be between 0 and key count")
    return minimum


def validate_generator_max_notes_per_beat(value: int, lane_count: int) -> int:
    maximum = int(value)
    if maximum < 0:
        raise ValueError("maximum notes per beat must be 0 or greater")
    return min(maximum, lane_count)


def choose_generator_forced_non_rest_lanes(rng: random.Random, empty_lanes: list[int], minimum: int) -> set[int]:
    if minimum <= 0 or not empty_lanes:
        return set()
    return set(rng.sample(empty_lanes, min(minimum, len(empty_lanes))))


def choose_generator_forced_rest_lanes(rng: random.Random, empty_lanes: list[int], maximum: int) -> set[int]:
    forced_count = len(empty_lanes) - maximum
    if forced_count <= 0:
        return set()
    return set(rng.sample(empty_lanes, forced_count))


def apply_generator_forced_long_note_ends(
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


def choose_generator_forced_long_note_start_conversions(
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


def choose_generator_forced_empty_action(
    rng: random.Random,
    weighted_actions: list[tuple[str, float]],
    is_last_tick: bool,
) -> str:
    if is_last_tick:
        return "single"
    non_rest_actions = [(action, weight) for action, weight in weighted_actions if action != "rest"]
    if sum(weight for _action, weight in non_rest_actions) <= 0:
        return "single"
    return base.choose_weighted(rng, non_rest_actions, "forced empty")


def note_count_at_tick(visible_grid: list[list[bool]], long_grid: list[list[bool]], tick: int) -> int:
    return sum(1 for lane in range(len(visible_grid)) if visible_grid[lane][tick] or long_grid[lane][tick])


def fill_min_notes_at_tick(
    rng: random.Random,
    visible_grid: list[list[bool]],
    long_grid: list[list[bool]],
    tick: int,
    minimum: int,
    blocked_lanes: set[int] | None = None,
) -> int:
    if minimum <= 0:
        return 0
    blocked_lanes = blocked_lanes or set()
    current = note_count_at_tick(visible_grid, long_grid, tick)
    needed = minimum - current
    if needed <= 0:
        return 0
    empty_lanes = [
        lane
        for lane in range(len(visible_grid))
        if lane not in blocked_lanes and not visible_grid[lane][tick] and not long_grid[lane][tick]
    ]
    if not empty_lanes:
        return 0
    placed = 0
    for lane in rng.sample(empty_lanes, min(needed, len(empty_lanes))):
        visible_grid[lane][tick] = True
        placed += 1
    return placed


def double_stair_lane_pairs(lanes: int, descending: bool) -> list[tuple[int, int]]:
    pairs = [(lane, lane + 1) for lane in range(0, lanes - 1, 2)]
    if descending:
        pairs.reverse()
    return pairs


def choose_chord_lanes(rng: random.Random, lane_count: int, size: int) -> list[int]:
    size = max(1, min(size, lane_count))
    return sorted(rng.sample(range(lane_count), size))


def limit_lanes_for_maximum(rng: random.Random, lanes: list[int] | tuple[int, ...], maximum: int) -> list[int]:
    unique_lanes = sorted(set(lanes))
    if maximum <= 0:
        return []
    if len(unique_lanes) <= maximum:
        return unique_lanes
    return sorted(rng.sample(unique_lanes, maximum))


def choose_density_chord_size(rng: random.Random, lane_count: int) -> int:
    candidates = [size for size in (2, 3, 4) if size <= lane_count]
    if not candidates:
        return 1
    return rng.choice(candidates)


def mirrored_lane_pairs(lanes: int) -> list[tuple[int, int]]:
    return [(lane, lanes - 1 - lane) for lane in range(lanes // 2)]


def choose_other_key_lanes(rng: random.Random, lane_count: int) -> list[int]:
    if lane_count <= 1:
        return [0]
    style = rng.choice(["bracket", "symmetrical", "inner"])
    if style == "bracket":
        return [0, lane_count - 1]
    pairs = mirrored_lane_pairs(lane_count)
    if not pairs:
        return [0]
    pair = rng.choice(pairs)
    if style == "inner" and len(pairs) > 1:
        pair = rng.choice(pairs[1:])
    return sorted(pair)


def choose_long_note_lanes(rng: random.Random, lane_count: int) -> list[int]:
    if lane_count <= 1:
        return [0]
    style = rng.choice(["shield", "reverse_shield", "inverse"])
    if style == "shield":
        return [rng.randrange(lane_count)]
    if style == "reverse_shield":
        start = rng.randrange(max(1, lane_count - 1))
        return [start, start + 1]
    lanes = list(range(0, lane_count, 2))
    if rng.choice([False, True]):
        lanes = list(range(1, lane_count, 2)) or lanes
    return lanes


def limit_long_note_lanes_for_minimum(
    rng: random.Random,
    lanes: list[int],
    lane_count: int,
    minimum: int,
) -> list[int]:
    if minimum <= 0:
        return lanes
    max_holding_lanes = lane_count - minimum
    if max_holding_lanes <= 0:
        return []
    if len(lanes) <= max_holding_lanes:
        return lanes
    return sorted(rng.sample(lanes, max_holding_lanes))


def place_visible_notes(visible_grid: list[list[bool]], lanes: list[int], tick: int) -> int:
    placed = 0
    seen: set[int] = set()
    for lane in lanes:
        if lane in seen:
            continue
        seen.add(lane)
        if not visible_grid[lane][tick]:
            visible_grid[lane][tick] = True
            placed += 1
    return placed


def place_long_notes(long_grid: list[list[bool]], lanes: list[int], start_tick: int, end_tick: int) -> tuple[int, int]:
    starts = 0
    ends = 0
    seen: set[int] = set()
    for lane in lanes:
        if lane in seen:
            continue
        seen.add(lane)
        if not long_grid[lane][start_tick]:
            long_grid[lane][start_tick] = True
            starts += 1
        if not long_grid[lane][end_tick]:
            long_grid[lane][end_tick] = True
            ends += 1
    return starts, ends


def make_generator_v1_note_pattern(options: GeneratorV1Options) -> GeneratorV1Pattern:
    measures = int(options.measures)
    if measures < 1 or measures > 999:
        raise ValueError("measure count must be between 1 and 999")
    if options.lanes < 1 or options.lanes > len(base.RANDOM_VISIBLE_CHANNELS):
        raise ValueError("lane count must be between 1 and 10")
    minimum_notes = validate_generator_min_notes_per_beat(options.min_notes_per_beat, options.lanes)
    maximum_notes = validate_generator_max_notes_per_beat(options.max_notes_per_beat, options.lanes)
    if minimum_notes > maximum_notes:
        raise ValueError("minimum notes per beat cannot be greater than maximum notes per beat")

    resolution = base.random_measure_resolution(options.beat_interval)
    if options.generation_count is None:
        total_ticks = measures * resolution
    else:
        total_ticks = int(options.generation_count)
        if total_ticks < 1:
            raise ValueError("generation count must be 1 or greater")
    measure_count = math.ceil(total_ticks / resolution)
    if measure_count > 999:
        raise ValueError("generated chart would exceed 999 BMS measures")

    single_weight = base.validate_weight(options.empty_single_weight, "single-note")
    start_weight = base.validate_weight(options.empty_long_start_weight, "long-note start")
    rest_weight = base.validate_weight(options.empty_rest_weight, "empty")
    end_weight = base.validate_weight(options.holding_long_end_weight, "long-note end")
    keep_weight = base.validate_weight(options.holding_keep_weight, "long-note keep")
    stair_chance = validate_percent(options.stair_pattern_chance, "stair pattern chance")
    chord_chance = validate_percent(options.chord_pattern_chance, "chord pattern chance")
    jack_chance = validate_percent(options.jack_pattern_chance, "jack pattern chance")
    long_note_pattern_chance = validate_percent(options.long_note_pattern_chance, "long-note pattern chance")
    other_key_chance = validate_percent(options.other_key_pattern_chance, "other-key pattern chance")
    density_window, density_tolerance, density_strength, target_density = validate_density_options(options)
    target_density = target_density if target_density is not None else automatic_target_density(options, stair_chance)

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
    stair_patterns = 0
    chord_patterns = 0
    jack_patterns = 0
    long_note_patterns = 0
    other_key_patterns = 0
    sparse_adjustments = 0
    dense_adjustments = 0

    tick = 0
    while tick < total_ticks:
        state = "stable"
        intensity = 0.0
        if options.density_balance:
            density = recent_density(visible_grid, long_grid, tick, density_window)
            state, intensity = density_state(density, target_density, density_tolerance, density_strength)
            if state == "sparse":
                sparse_adjustments += 1
            elif state == "dense":
                dense_adjustments += 1

        tick_stair_chance = adjusted_stair_chance(stair_chance, state, intensity)
        tick_chord_chance = adjusted_pattern_chance(chord_chance, state, intensity)
        tick_jack_chance = adjusted_pattern_chance(jack_chance, state, intensity)
        tick_long_note_pattern_chance = adjusted_pattern_chance(long_note_pattern_chance, state, intensity)
        tick_other_key_chance = adjusted_pattern_chance(other_key_chance, state, intensity)
        tick_empty_actions = adjusted_empty_actions(single_weight, start_weight, rest_weight, state, intensity)
        tick_holding_actions = adjusted_holding_actions(end_weight, keep_weight, state, intensity)

        descending_stair = rng.choice([False, True])
        stair_pairs = double_stair_lane_pairs(options.lanes, descending_stair)
        remaining_ticks = total_ticks - tick
        can_start_stair = bool(stair_pairs) and remaining_ticks >= len(stair_pairs) and not any(holding)
        if can_start_stair and tick_stair_chance > 0 and rng.random() * 100 < tick_stair_chance:
            for offset, pair in enumerate(stair_pairs):
                for lane in limit_lanes_for_maximum(rng, pair, maximum_notes):
                    visible_grid[lane][tick + offset] = True
                    visible_notes += 1
                visible_notes += fill_min_notes_at_tick(rng, visible_grid, long_grid, tick + offset, minimum_notes)
            stair_patterns += 1
            tick += len(stair_pairs)
            continue

        can_place_other_key = options.lanes > 1 and not any(holding)
        if can_place_other_key and tick_other_key_chance > 0 and rng.random() * 100 < tick_other_key_chance:
            other_key_lanes = limit_lanes_for_maximum(rng, choose_other_key_lanes(rng, options.lanes), maximum_notes)
            visible_notes += place_visible_notes(visible_grid, other_key_lanes, tick)
            visible_notes += fill_min_notes_at_tick(rng, visible_grid, long_grid, tick, minimum_notes)
            other_key_patterns += 1
            tick += 1
            continue

        jack_length = rng.randint(2, 4)
        can_place_jack = remaining_ticks >= jack_length and not any(holding)
        if can_place_jack and tick_jack_chance > 0 and rng.random() * 100 < tick_jack_chance:
            jack_type = rng.choice(["minijack", "jumpjack", "chordjack"])
            if jack_type == "minijack" or options.lanes == 1:
                jack_lanes = [rng.randrange(options.lanes)]
            elif jack_type == "jumpjack":
                jack_lanes = choose_chord_lanes(rng, options.lanes, min(2, options.lanes))
            else:
                jack_lanes = choose_chord_lanes(rng, options.lanes, min(rng.choice([3, 4]), options.lanes))
            jack_lanes = limit_lanes_for_maximum(rng, jack_lanes, maximum_notes)
            for offset in range(jack_length):
                visible_notes += place_visible_notes(visible_grid, jack_lanes, tick + offset)
                visible_notes += fill_min_notes_at_tick(rng, visible_grid, long_grid, tick + offset, minimum_notes)
            jack_patterns += 1
            tick += jack_length
            continue

        long_note_duration = rng.randint(2, 6)
        can_place_long_note_pattern = remaining_ticks > long_note_duration and not any(holding) and minimum_notes < options.lanes
        if (
            can_place_long_note_pattern
            and tick_long_note_pattern_chance > 0
            and rng.random() * 100 < tick_long_note_pattern_chance
        ):
            long_note_lanes = limit_long_note_lanes_for_minimum(
                rng,
                choose_long_note_lanes(rng, options.lanes),
                options.lanes,
                minimum_notes,
            )
            long_note_lanes = limit_lanes_for_maximum(rng, long_note_lanes, maximum_notes)
            if not long_note_lanes:
                tick += 1
                continue
            starts, ends = place_long_notes(
                long_grid,
                long_note_lanes,
                tick,
                tick + long_note_duration,
            )
            long_note_starts += starts
            long_note_ends += ends
            blocked_lanes = set(long_note_lanes)
            for fill_tick in range(tick, tick + long_note_duration + 1):
                visible_notes += fill_min_notes_at_tick(
                    rng,
                    visible_grid,
                    long_grid,
                    fill_tick,
                    minimum_notes,
                    blocked_lanes if tick < fill_tick < tick + long_note_duration else None,
                )
            long_note_patterns += 1
            tick += long_note_duration + 1
            continue

        can_place_chord = not any(holding)
        if can_place_chord and tick_chord_chance > 0 and rng.random() * 100 < tick_chord_chance:
            size = min(max(choose_density_chord_size(rng, options.lanes), minimum_notes), maximum_notes)
            if size <= 0:
                tick += 1
                continue
            visible_notes += place_visible_notes(visible_grid, choose_chord_lanes(rng, options.lanes, size), tick)
            visible_notes += fill_min_notes_at_tick(rng, visible_grid, long_grid, tick, minimum_notes)
            chord_patterns += 1
            tick += 1
            continue

        is_last_tick = tick == total_ticks - 1
        holding_lanes = [lane for lane in range(options.lanes) if holding[lane]]
        empty_lanes = [lane for lane in range(options.lanes) if not holding[lane]]
        end_lanes: set[int] = set()
        keep_lanes: set[int] = set()

        for lane in holding_lanes:
            action = "end" if is_last_tick else base.choose_weighted(rng, tick_holding_actions, "holding")
            if action == "end":
                end_lanes.add(lane)
            else:
                keep_lanes.add(lane)

        forced_end_lanes = apply_generator_forced_long_note_ends(
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

        forced_rest_lanes = choose_generator_forced_rest_lanes(rng, empty_lanes, maximum_notes)
        non_rest_candidate_lanes = [lane for lane in empty_lanes if lane not in forced_rest_lanes]
        forced_non_rest_lanes = choose_generator_forced_non_rest_lanes(rng, non_rest_candidate_lanes, minimum_notes)
        single_lanes: set[int] = set()
        start_lanes: set[int] = set()

        for lane in empty_lanes:
            if lane in forced_rest_lanes:
                action = "rest"
            elif lane in forced_non_rest_lanes:
                action = choose_generator_forced_empty_action(rng, tick_empty_actions, is_last_tick)
            elif is_last_tick:
                final_empty_actions = [(action, weight) for action, weight in tick_empty_actions if action != "start"]
                final_total = sum(weight for _action, weight in final_empty_actions)
                action = base.choose_weighted(rng, final_empty_actions, "final empty") if final_total > 0 else "rest"
            else:
                action = base.choose_weighted(rng, tick_empty_actions, "empty")

            if action == "single":
                single_lanes.add(lane)
            elif action == "start":
                start_lanes.add(lane)

        forced_single_lanes = choose_generator_forced_long_note_start_conversions(
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
        tick += 1

    return GeneratorV1Pattern(
        visible_grid=visible_grid,
        long_grid=long_grid,
        resolution=resolution,
        total_ticks=total_ticks,
        visible_notes=visible_notes,
        long_note_starts=long_note_starts,
        long_note_ends=long_note_ends,
        stair_patterns=stair_patterns,
        chord_patterns=chord_patterns,
        jack_patterns=jack_patterns,
        long_note_patterns=long_note_patterns,
        other_key_patterns=other_key_patterns,
        sparse_adjustments=sparse_adjustments,
        dense_adjustments=dense_adjustments,
    )


def make_generator_v1_bms_bytes(options: GeneratorV1Options) -> tuple[bytes, int, int, int, int, int, int, int, int, int, int]:
    source_bgm = parse_source_bms_bgm(options.source_bms) if options.source_bms is not None else None
    note_id = select_generator_note_id(options.note_object_id, source_bgm.used_wav_ids if source_bgm else set())
    wav_filename = base.validate_wav_filename(options.wav_filename)
    pattern = make_generator_v1_note_pattern(options)
    pattern_measure_count = math.ceil(pattern.total_ticks / pattern.resolution)
    bgm_measure_count = source_bgm.reposition_measure_count if source_bgm is not None else 0
    output_measure_count = max(pattern_measure_count, bgm_measure_count)

    lines: list[bytes] = [
        b"#PLAYER " + (b"3" if options.lanes > 5 else b"1") + b"\r\n",
        f"#TITLE {options.title.strip() or APP_NAME}\r\n".encode("utf-8"),
        b"#ARTIST BMS Decalcomanie Tool\r\n",
        f"#BPM {base.bms_number(float(options.bpm))}\r\n".encode("ascii"),
        b"#PLAYLEVEL 1\r\n",
        b"#RANK 2\r\n",
        b"#TOTAL 100\r\n",
        b"#LNTYPE 1\r\n",
    ]
    key_extension = base.bms_key_extension_line(options.lanes)
    if key_extension is not None:
        lines.insert(1, key_extension)
    if source_bgm is not None:
        lines.extend(source_bgm.wav_lines)
    lines.extend(
        [
            b"#WAV" + note_id + b" " + wav_filename.encode("utf-8") + b"\r\n",
            b"\r\n",
        ]
    )

    for measure_index in range(output_measure_count):
        measure = f"{measure_index + 1:03d}".encode("ascii")
        start = measure_index * pattern.resolution
        end = start + pattern.resolution

        if source_bgm is not None and measure_index < source_bgm.reposition_measure_count:
            lines.extend(source_bgm_lines_for_measure(source_bgm, measure_index))

        if measure_index >= pattern_measure_count:
            continue

        for lane in range(options.lanes):
            if not any(pattern.visible_grid[lane][start : min(end, pattern.total_ticks)]):
                continue
            data = b"".join(
                note_id if tick < pattern.total_ticks and pattern.visible_grid[lane][tick] else b"00"
                for tick in range(start, end)
            )
            lines.append(base.build_chart_line(measure, base.RANDOM_VISIBLE_CHANNELS[lane], data, b"\r\n"))

        for lane in range(options.lanes):
            if not any(pattern.long_grid[lane][start : min(end, pattern.total_ticks)]):
                continue
            data = b"".join(
                note_id if tick < pattern.total_ticks and pattern.long_grid[lane][tick] else b"00"
                for tick in range(start, end)
            )
            lines.append(base.build_chart_line(measure, base.RANDOM_LONGNOTE_CHANNELS[lane], data, b"\r\n"))

    return (
        b"".join(lines),
        pattern.visible_notes,
        pattern.long_note_starts,
        pattern.long_note_ends,
        pattern.stair_patterns,
        pattern.chord_patterns,
        pattern.jack_patterns,
        pattern.long_note_patterns,
        pattern.other_key_patterns,
        pattern.sparse_adjustments,
        pattern.dense_adjustments,
    )


def make_generator_v1_osu_bytes(options: GeneratorV1Options) -> tuple[bytes, int, int, int, int, int, int, int, int, int, int, float]:
    bpm = float(options.bpm)
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("BPM must be greater than 0")
    wav_filename = base.validate_wav_filename(options.wav_filename)
    pattern = make_generator_v1_note_pattern(options)
    beat_interval = base.parse_beat_interval(options.beat_interval)
    beat_length = 60000.0 / bpm
    beat_length_text = f"{beat_length:.8f}".rstrip("0").rstrip(".")
    chart_end_ms = base.osu_time_for_tick(pattern.total_ticks, bpm, beat_interval)

    title = options.title.strip() or APP_NAME
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
        b"Creator:Generator v1\r\n",
        f"Version:Generator v1 {options.lanes}K\r\n".encode("ascii"),
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

    hit_objects: list[tuple[int, int, bytes]] = []
    holding_starts: list[int | None] = [None] * options.lanes

    for tick in range(pattern.total_ticks):
        for lane in range(options.lanes):
            x = base.osu_x_for_column(lane, options.lanes).decode("ascii")
            time_ms = base.osu_time_for_tick(tick, bpm, beat_interval)
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

    for _time_ms, _lane, hit_object in sorted(hit_objects):
        lines.append(hit_object)

    return (
        b"".join(lines),
        pattern.visible_notes,
        pattern.long_note_starts,
        pattern.long_note_ends,
        pattern.stair_patterns,
        pattern.chord_patterns,
        pattern.jack_patterns,
        pattern.long_note_patterns,
        pattern.other_key_patterns,
        pattern.sparse_adjustments,
        pattern.dense_adjustments,
        max(1.0, chart_end_ms / 1000.0 + 1.0),
    )


def make_generator_v1_osu_clipboard_bytes(
    options: GeneratorV1Options,
    time_offset_ms: int = 0,
) -> tuple[bytes, int, int, int, int, int, int, int, int, int, int]:
    bpm = float(options.bpm)
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("BPM must be greater than 0")
    offset = int(time_offset_ms)
    if offset < 0:
        raise ValueError("osu clipboard start time must be 0 or greater")
    pattern = make_generator_v1_note_pattern(options)
    hit_objects, _chart_end_ms = base.build_random_osu_hitobject_lines(pattern, options, offset)
    if not hit_objects:
        raise ValueError("Generator v1 produced no osu hit objects")
    return (
        b"".join(hit_object for _time_ms, _lane, hit_object in hit_objects),
        pattern.visible_notes,
        pattern.long_note_starts,
        pattern.long_note_ends,
        pattern.stair_patterns,
        pattern.chord_patterns,
        pattern.jack_patterns,
        pattern.long_note_patterns,
        pattern.other_key_patterns,
        pattern.sparse_adjustments,
        pattern.dense_adjustments,
    )


def generate_generator_v1_chart_file(output: Path, options: GeneratorV1Options) -> GeneratorV1Result:
    output = output.resolve()
    suffix = output.suffix.lower()
    if output.exists() and not options.overwrite:
        raise FileExistsError(f"output already exists: {output}")

    if suffix in base.BMS_EXTENSIONS:
        (
            raw,
            visible_notes,
            long_note_starts,
            long_note_ends,
            stair_patterns,
            chord_patterns,
            jack_patterns,
            long_note_patterns,
            other_key_patterns,
            sparse_adjustments,
            dense_adjustments,
        ) = make_generator_v1_bms_bytes(options)
        audio_duration_seconds = 0.05
    elif suffix in base.OSU_EXTENSIONS:
        (
            raw,
            visible_notes,
            long_note_starts,
            long_note_ends,
            stair_patterns,
            chord_patterns,
            jack_patterns,
            long_note_patterns,
            other_key_patterns,
            sparse_adjustments,
            dense_adjustments,
            audio_duration_seconds,
        ) = make_generator_v1_osu_bytes(options)
    else:
        raise ValueError("Generator v1 output must be a .bms/.bme/.bml/.pms or .osu file")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)

    wav_filename = base.validate_wav_filename(options.wav_filename)
    silence_wav = output.parent / wav_filename
    silence_wav_created = False
    if not silence_wav.exists():
        base.write_silent_wav(silence_wav, audio_duration_seconds)
        silence_wav_created = True

    return GeneratorV1Result(
        output=output,
        visible_notes=visible_notes,
        long_note_starts=long_note_starts,
        long_note_ends=long_note_ends,
        silence_wav=silence_wav,
        silence_wav_created=silence_wav_created,
        stair_patterns=stair_patterns,
        chord_patterns=chord_patterns,
        jack_patterns=jack_patterns,
        long_note_patterns=long_note_patterns,
        other_key_patterns=other_key_patterns,
        sparse_adjustments=sparse_adjustments,
        dense_adjustments=dense_adjustments,
    )


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("720x950")
    root.minsize(660, 900)

    title_var = tk.StringVar(value=APP_NAME)
    bpm_var = tk.StringVar(value="120")
    beat_interval_var = tk.StringVar(value="0.25")
    key_count_var = tk.StringVar(value="10")
    generation_count_var = tk.StringVar(value="256")
    min_notes_var = tk.StringVar(value="0")
    max_notes_var = tk.StringVar(value="10")
    stair_var = tk.StringVar(value="12.5")
    chord_var = tk.StringVar(value="0")
    jack_var = tk.StringVar(value="0")
    long_note_pattern_var = tk.StringVar(value="0")
    other_key_var = tk.StringVar(value="0")
    density_balance_var = tk.BooleanVar(value=True)
    density_window_var = tk.StringVar(value="16")
    target_density_var = tk.StringVar(value="")
    density_tolerance_var = tk.StringVar(value="25")
    density_strength_var = tk.StringVar(value="100")
    single_var = tk.StringVar(value="25")
    start_var = tk.StringVar(value="50")
    rest_var = tk.StringVar(value="25")
    end_var = tk.StringVar(value="25")
    keep_var = tk.StringVar(value="75")
    seed_var = tk.StringVar(value="")
    output_var = tk.StringVar(value="")
    source_bms_var = tk.StringVar(value="")

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)
    frame.columnconfigure(1, weight=1)

    def add_entry(row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=3)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, pady=3, padx=(8, 0))

    add_entry(0, "Title", title_var)
    add_entry(1, "BPM", bpm_var)
    add_entry(2, "Beat interval", beat_interval_var)
    add_entry(3, "Key count", key_count_var)
    add_entry(4, "Generation count", generation_count_var)
    add_entry(5, "Minimum notes/beat", min_notes_var)
    add_entry(6, "Maximum notes/beat", max_notes_var)
    add_entry(7, "Double-stair chance (%)", stair_var)
    add_entry(8, "Chord/density chance (%)", chord_var)
    add_entry(9, "Jack chance (%)", jack_var)
    add_entry(10, "Long-note pattern chance (%)", long_note_pattern_var)
    add_entry(11, "Other-key chance (%)", other_key_var)
    ttk.Checkbutton(frame, text="Density balance with diff calc", variable=density_balance_var).grid(
        row=12,
        column=0,
        columnspan=2,
        sticky=tk.W,
        pady=3,
    )
    add_entry(13, "Density window", density_window_var)
    add_entry(14, "Target notes/tick (blank auto, max keys)", target_density_var)
    add_entry(15, "Density tolerance (%)", density_tolerance_var)
    add_entry(16, "Density strength (%)", density_strength_var)
    add_entry(17, "1a empty: single note weight", single_var)
    add_entry(18, "2a empty: long-note start weight", start_var)
    add_entry(19, "3a empty: no note weight", rest_var)
    add_entry(20, "1b holding: long-note end weight", end_var)
    add_entry(21, "2b holding: keep holding weight", keep_var)
    add_entry(22, "Seed (optional)", seed_var)

    output_row = ttk.Frame(frame)
    output_row.grid(row=23, column=0, columnspan=2, sticky=tk.EW, pady=(10, 3))
    output_row.columnconfigure(1, weight=1)
    ttk.Label(output_row, text="Output chart").grid(row=0, column=0, sticky=tk.W)
    ttk.Entry(output_row, textvariable=output_var).grid(row=0, column=1, sticky=tk.EW, padx=(8, 8))

    def browse_output() -> None:
        path = filedialog.asksaveasfilename(
            parent=root,
            title="Save Generator v1 chart",
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

    ttk.Button(output_row, text="Browse", command=browse_output).grid(row=0, column=2)

    source_row = ttk.Frame(frame)
    source_row.grid(row=24, column=0, columnspan=2, sticky=tk.EW, pady=(3, 3))
    source_row.columnconfigure(1, weight=1)
    ttk.Label(source_row, text="Source BMS for BGM").grid(row=0, column=0, sticky=tk.W)
    ttk.Entry(source_row, textvariable=source_bms_var).grid(row=0, column=1, sticky=tk.EW, padx=(8, 8))

    def browse_source_bms() -> None:
        path = filedialog.askopenfilename(
            parent=root,
            title="Select source BMS for BGM",
            filetypes=[
                ("BMS files", "*.bms *.bme *.bml *.pms"),
                ("All files", "*.*"),
            ],
        )
        if path:
            source_bms_var.set(path)

    ttk.Button(source_row, text="Browse", command=browse_source_bms).grid(row=0, column=2)

    log_box = tk.Text(frame, height=7, state="disabled", wrap=tk.WORD)

    def append_log(text: str) -> None:
        log_box.configure(state="normal")
        log_box.insert(tk.END, text + "\n")
        log_box.see(tk.END)
        log_box.configure(state="disabled")
        root.update_idletasks()

    def build_options(overwrite: bool = False) -> GeneratorV1Options:
        seed_text = seed_var.get().strip()
        target_density_text = target_density_var.get().strip()
        source_bms_text = source_bms_var.get().strip()
        return GeneratorV1Options(
            title=title_var.get().strip() or APP_NAME,
            bpm=float(bpm_var.get()),
            beat_interval=beat_interval_var.get(),
            generation_count=int(generation_count_var.get()),
            lanes=int(key_count_var.get()),
            min_notes_per_beat=int(min_notes_var.get()),
            max_notes_per_beat=int(max_notes_var.get()),
            source_bms=Path(source_bms_text) if source_bms_text else None,
            stair_pattern_chance=float(stair_var.get()),
            chord_pattern_chance=float(chord_var.get()),
            jack_pattern_chance=float(jack_var.get()),
            long_note_pattern_chance=float(long_note_pattern_var.get()),
            other_key_pattern_chance=float(other_key_var.get()),
            density_balance=density_balance_var.get(),
            density_window=int(density_window_var.get()),
            target_density=float(target_density_text) if target_density_text else None,
            density_tolerance=float(density_tolerance_var.get()),
            density_strength=float(density_strength_var.get()),
            empty_single_weight=float(single_var.get()),
            empty_long_start_weight=float(start_var.get()),
            empty_rest_weight=float(rest_var.get()),
            holding_long_end_weight=float(end_var.get()),
            holding_keep_weight=float(keep_var.get()),
            seed=int(seed_text) if seed_text else None,
            overwrite=overwrite,
        )

    def generate() -> None:
        output_text = output_var.get().strip()
        if not output_text:
            browse_output()
            output_text = output_var.get().strip()
        if not output_text:
            return

        output_path = Path(output_text)
        overwrite = False
        if output_path.exists():
            overwrite = messagebox.askyesno("Overwrite file?", f"{output_path} already exists.\nOverwrite it?", parent=root)
            if not overwrite:
                return

        try:
            options = build_options(overwrite)
            result = generate_generator_v1_chart_file(output_path, options)
        except Exception as exc:  # noqa: BLE001 - GUI should report validation errors.
            messagebox.showerror("Generator v1 failed", str(exc), parent=root)
            return

        append_log(
            f"OK {result.output} "
            f"(single {result.visible_notes}, LN {result.long_note_starts}/{result.long_note_ends}, "
            f"stairs {result.stair_patterns}, chords {result.chord_patterns}, jacks {result.jack_patterns}, "
            f"LN-patterns {result.long_note_patterns}, other-key {result.other_key_patterns}, "
            f"sparse {result.sparse_adjustments}, dense {result.dense_adjustments})"
        )
        if result.silence_wav_created and result.silence_wav is not None:
            append_log(f"OK wrote silent WAV -> {result.silence_wav}")
        messagebox.showinfo("Generator v1 complete", f"Created {result.output}", parent=root)

    def generate_clipboard() -> None:
        try:
            start_time_ms = simpledialog.askinteger(
                "Generator v1 timestamp start ms",
                "Start ms",
                parent=root,
                initialvalue=0,
                minvalue=0,
            )
            if start_time_ms is None:
                return
            options = build_options(False)
            (
                clipboard_bytes,
                visible_notes,
                long_starts,
                long_ends,
                stair_patterns,
                chord_patterns,
                jack_patterns,
                long_note_patterns,
                other_key_patterns,
                sparse_adjustments,
                dense_adjustments,
            ) = make_generator_v1_osu_clipboard_bytes(options, start_time_ms)
        except Exception as exc:  # noqa: BLE001 - GUI should report validation errors.
            messagebox.showerror("Generator v1 clipboard failed", str(exc), parent=root)
            return

        root.clipboard_clear()
        root.clipboard_append(clipboard_bytes.decode("utf-8", errors="replace"))
        root.update()
        append_log(
            f"OK clipboard HitObject rows "
            f"(start {start_time_ms} ms, single {visible_notes}, LN {long_starts}/{long_ends}, "
            f"stairs {stair_patterns}, chords {chord_patterns}, jacks {jack_patterns}, "
            f"LN-patterns {long_note_patterns}, other-key {other_key_patterns}, "
            f"sparse {sparse_adjustments}, dense {dense_adjustments})"
        )
        messagebox.showinfo("Generator v1 clipboard ready", "Copied HitObject rows to clipboard.", parent=root)

    ttk.Label(
        frame,
        text="Pattern families follow chord density, jacks, LN shields, brackets/symmetry, and double-stairs.",
    ).grid(row=25, column=0, columnspan=2, sticky=tk.W, pady=(8, 2))
    ttk.Label(
        frame,
        text="BMS output can reuse a source BMS #WAV table and rearranged #xxx01 BGM lines.",
    ).grid(row=26, column=0, columnspan=2, sticky=tk.W, pady=(0, 2))
    ttk.Label(
        frame,
        text="Diff calc lowers dense sections and fills sparse sections using recent notes/tick.",
    ).grid(row=27, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
    ttk.Button(frame, text="Generate", command=generate).grid(row=28, column=0, columnspan=2, sticky=tk.EW)
    ttk.Button(frame, text="Generate HitObject clipboard", command=generate_clipboard).grid(
        row=29,
        column=0,
        columnspan=2,
        sticky=tk.EW,
        pady=(8, 0),
    )
    log_box.grid(row=30, column=0, columnspan=2, sticky=tk.NSEW, pady=(10, 0))
    frame.rowconfigure(30, weight=1)
    append_log("Generator v1 fork. Default stair pattern chance is 12.5%; density balance is on.")

    root.mainloop()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generator v1 random BMS/osu!mania chart generator.")
    parser.add_argument("--output", "--random-output", dest="output", type=Path, help="Output .bms/.bme/.bml/.pms or .osu file. Empty launches GUI.")
    parser.add_argument("--source-bms", "--bgm-source-bms", dest="source_bms", type=Path, help="Source BMS whose #WAV table and #xxx01 BGM lines are reused for BMS output.")
    parser.add_argument("--title", default=APP_NAME, help="Chart title.")
    parser.add_argument("--bpm", type=float, default=120.0, help="BPM.")
    parser.add_argument("--beat-interval", default="0.25", help="Beat spacing, such as 1, 0.5, 0.25, or 1/8.")
    parser.add_argument("--keys", type=int, default=10, help="Key count from 1 to 10.")
    parser.add_argument("--generate-count", "--note-count", dest="generate_count", type=int, default=256, help="How many beat-interval positions to generate.")
    parser.add_argument("--min-notes-per-beat", type=int, default=0, help="Minimum generated notes per beat position.")
    parser.add_argument("--max-notes-per-beat", type=int, default=10, help="Maximum empty lanes allowed to roll non-3a per beat position.")
    parser.add_argument("--stair-chance", type=float, default=12.5, help="Percent chance to start a double-stair pattern at a generated position.")
    parser.add_argument("--chord-chance", type=float, default=0.0, help="Percent chance to place a double/triple/quad chord.")
    parser.add_argument("--jack-chance", type=float, default=0.0, help="Percent chance to place a mini/jump/chord jack.")
    parser.add_argument("--ln-pattern-chance", type=float, default=0.0, help="Percent chance to place a shield/reverse/inverse long-note pattern.")
    parser.add_argument("--other-key-chance", type=float, default=0.0, help="Percent chance to place a bracket/symmetrical other-key pattern.")
    parser.add_argument("--no-density-balance", action="store_true", help="Disable diff-calc density balancing.")
    parser.add_argument("--density-window", type=int, default=16, help="Recent generated positions used for density calculation.")
    parser.add_argument("--target-density", type=float, help="Target notes per generated position. Values above key count are clamped; empty uses automatic target.")
    parser.add_argument("--density-tolerance", type=float, default=25.0, help="Percent tolerance around target density before adjustment.")
    parser.add_argument("--density-strength", type=float, default=100.0, help="Percent strength for sparse/dense probability adjustment.")
    parser.add_argument("--weight-single", type=float, default=25.0, help="1a: empty lane single-note weight.")
    parser.add_argument("--weight-ln-start", type=float, default=50.0, help="2a: empty lane long-note start weight.")
    parser.add_argument("--weight-empty", type=float, default=25.0, help="3a: empty lane no-note weight.")
    parser.add_argument("--weight-ln-end", type=float, default=25.0, help="1b: holding lane long-note end weight.")
    parser.add_argument("--weight-ln-keep", type=float, default=75.0, help="2b: holding lane keep-holding weight.")
    parser.add_argument("--seed", type=int, help="Optional random seed.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output if it exists.")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if args.output is None:
        launch_gui()
        return 0

    options = GeneratorV1Options(
        title=args.title,
        bpm=args.bpm,
        beat_interval=args.beat_interval,
        generation_count=args.generate_count,
        lanes=args.keys,
        min_notes_per_beat=args.min_notes_per_beat,
        max_notes_per_beat=args.max_notes_per_beat,
        source_bms=args.source_bms,
        stair_pattern_chance=args.stair_chance,
        chord_pattern_chance=args.chord_chance,
        jack_pattern_chance=args.jack_chance,
        long_note_pattern_chance=args.ln_pattern_chance,
        other_key_pattern_chance=args.other_key_chance,
        density_balance=not args.no_density_balance,
        density_window=args.density_window,
        target_density=args.target_density,
        density_tolerance=args.density_tolerance,
        density_strength=args.density_strength,
        empty_single_weight=args.weight_single,
        empty_long_start_weight=args.weight_ln_start,
        empty_rest_weight=args.weight_empty,
        holding_long_end_weight=args.weight_ln_end,
        holding_keep_weight=args.weight_ln_keep,
        seed=args.seed,
        overwrite=args.overwrite,
    )
    try:
        result = generate_generator_v1_chart_file(args.output, options)
    except Exception as exc:  # noqa: BLE001 - CLI should report validation errors.
        print(f"FAIL Generator v1: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK Generator v1 -> {result.output} "
        f"(single {result.visible_notes}, LN {result.long_note_starts}/{result.long_note_ends}, "
        f"stairs {result.stair_patterns}, chords {result.chord_patterns}, jacks {result.jack_patterns}, "
        f"LN-patterns {result.long_note_patterns}, other-key {result.other_key_patterns}, "
        f"sparse {result.sparse_adjustments}, dense {result.dense_adjustments})"
    )
    if result.silence_wav_created and result.silence_wav is not None:
        print(f"OK silent WAV -> {result.silence_wav}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    return run_cli(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
