from pathlib import Path
import tempfile
import unittest

from bms_generator_v1 import (
    GeneratorV1Options,
    double_stair_lane_pairs,
    generate_generator_v1_chart_file,
    make_generator_v1_bms_bytes,
    make_generator_v1_note_pattern,
    make_generator_v1_osu_bytes,
    make_generator_v1_osu_timestamp_clipboard_bytes,
)


class GeneratorV1Tests(unittest.TestCase):
    def test_default_stair_chance_is_12_5_percent(self) -> None:
        self.assertEqual(GeneratorV1Options().stair_pattern_chance, 12.5)

    def test_double_stair_pairs_skip_by_two_lanes(self) -> None:
        self.assertEqual(double_stair_lane_pairs(10, descending=False), [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)])
        self.assertEqual(double_stair_lane_pairs(10, descending=True), [(8, 9), (6, 7), (4, 5), (2, 3), (0, 1)])

    def test_stair_chance_100_creates_one_clean_double_stair(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=2,
                beat_interval="1",
                stair_pattern_chance=100,
                density_balance=False,
            )
        )

        self.assertEqual(pattern.visible_notes, 4)
        self.assertEqual(pattern.long_note_starts, 0)
        self.assertEqual(pattern.long_note_ends, 0)
        self.assertEqual(pattern.stair_patterns, 1)
        self.assertEqual([sum(1 for lane in range(4) if pattern.visible_grid[lane][tick]) for tick in range(2)], [2, 2])
        self.assertEqual([sum(1 for tick in range(2) if pattern.visible_grid[lane][tick]) for lane in range(4)], [1, 1, 1, 1])

    def test_stair_chance_zero_preserves_normal_generation(self) -> None:
        raw, visible_notes, long_starts, long_ends, stair_patterns, *_pattern_counts, sparse_adjustments, dense_adjustments = make_generator_v1_bms_bytes(
            GeneratorV1Options(
                lanes=4,
                generation_count=3,
                beat_interval="1",
                stair_pattern_chance=0,
                density_balance=False,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            )
        )

        self.assertEqual(visible_notes, 12)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertEqual(stair_patterns, 0)
        self.assertEqual(sparse_adjustments, 0)
        self.assertEqual(dense_adjustments, 0)
        self.assertIn(b"#4K\r\n", raw)
        self.assertIn(b"#00111:01010100\r\n", raw)
        self.assertNotIn(b"#00115:", raw)

    def test_bms_generation_uses_10k_extension_and_omits_9k_extension(self) -> None:
        raw_10k, *_counts = make_generator_v1_bms_bytes(
            GeneratorV1Options(
                lanes=10,
                generation_count=1,
                beat_interval="1",
                stair_pattern_chance=0,
                density_balance=False,
            )
        )
        raw_9k, *_counts_9k = make_generator_v1_bms_bytes(
            GeneratorV1Options(
                lanes=9,
                generation_count=1,
                beat_interval="1",
                stair_pattern_chance=0,
                density_balance=False,
            )
        )

        self.assertIn(b"#10K\r\n", raw_10k)
        self.assertNotIn(b"#9K\r\n", raw_9k)
        self.assertNotIn(b"#10K\r\n", raw_9k)

    def test_bms_generation_reuses_and_repositions_source_bgm(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.bms"
            source.write_bytes(
                b"#WAV01 source_note_conflict.wav\r\n"
                b"#WAVAA bgm_a.wav\r\n"
                b"#WAVBB bgm_b.wav\r\n"
                b"#00101:AA00\r\n"
                b"#00111:AA00\r\n"
                b"#00201:00BB\r\n"
                b"#00511:BB00\r\n"
            )

            raw, visible_notes, *_rest = make_generator_v1_bms_bytes(
                GeneratorV1Options(
                    source_bms=source,
                    lanes=1,
                    generation_count=12,
                    beat_interval="1",
                    stair_pattern_chance=0,
                    density_balance=False,
                    empty_single_weight=100,
                    empty_long_start_weight=0,
                    empty_rest_weight=0,
                )
            )

        self.assertEqual(visible_notes, 12)
        self.assertIn(b"#WAV01 source_note_conflict.wav\r\n", raw)
        self.assertIn(b"#WAVAA bgm_a.wav\r\n", raw)
        self.assertIn(b"#WAVBB bgm_b.wav\r\n", raw)
        self.assertIn(b"#WAV02 _random_note_silence.wav\r\n", raw)
        self.assertIn(b"#00101:AA00\r\n", raw)
        self.assertIn(b"#00201:00BB\r\n", raw)
        self.assertIn(b"#00301:AA00\r\n", raw)
        self.assertIn(b"#00401:00BB\r\n", raw)
        self.assertIn(b"#00501:AA00\r\n", raw)
        self.assertNotIn(b"#00601:", raw)
        self.assertIn(b"#00111:02020202\r\n", raw)
        self.assertNotIn(b"#00111:AA00\r\n", raw)

    def test_min_notes_prevents_empty_rest_action(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=3,
                beat_interval="1",
                min_notes_per_beat=2,
                stair_pattern_chance=0,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=11,
            )
        )

        self.assertEqual(pattern.visible_notes, 6)
        self.assertEqual(pattern.long_note_starts, 0)
        self.assertEqual(pattern.long_note_ends, 0)
        for tick in range(3):
            self.assertEqual(sum(1 for lane in range(4) if pattern.visible_grid[lane][tick]), 2)

    def test_max_notes_forces_excess_empty_lanes_to_rest(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=10,
                generation_count=3,
                beat_interval="1",
                max_notes_per_beat=4,
                stair_pattern_chance=0,
                density_balance=False,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
                seed=31,
            )
        )

        self.assertEqual(pattern.visible_notes, 12)
        self.assertEqual(pattern.long_note_starts, 0)
        self.assertEqual(pattern.long_note_ends, 0)
        for tick in range(3):
            self.assertEqual(sum(1 for lane in range(10) if pattern.visible_grid[lane][tick]), 4)

    def test_min_notes_above_max_notes_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_generator_v1_note_pattern(
                GeneratorV1Options(
                    lanes=10,
                    generation_count=1,
                    min_notes_per_beat=5,
                    max_notes_per_beat=4,
                    density_balance=False,
                )
            )

    def test_min_notes_forces_long_note_end_when_all_keys_held(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=3,
                beat_interval="1",
                min_notes_per_beat=2,
                stair_pattern_chance=0,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=100,
                empty_rest_weight=0,
                holding_long_end_weight=0,
                holding_keep_weight=100,
            )
        )

        self.assertEqual(pattern.visible_notes, 4)
        self.assertEqual(pattern.long_note_starts, 4)
        self.assertEqual(pattern.long_note_ends, 4)
        self.assertEqual(sum(1 for lane in range(4) if pattern.visible_grid[lane][0]), 2)
        self.assertEqual(sum(1 for lane in range(4) if pattern.long_grid[lane][0]), 2)
        self.assertEqual(sum(1 for lane in range(4) if pattern.long_grid[lane][1]), 4)
        self.assertEqual(sum(1 for lane in range(4) if pattern.visible_grid[lane][2]), 2)

    def test_min_notes_converts_excess_long_starts_to_singles(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=2,
                beat_interval="1",
                min_notes_per_beat=2,
                stair_pattern_chance=0,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=100,
                empty_rest_weight=0,
                holding_long_end_weight=0,
                holding_keep_weight=100,
                seed=21,
            )
        )

        self.assertEqual(sum(1 for lane in range(4) if pattern.visible_grid[lane][0]), 2)
        self.assertEqual(sum(1 for lane in range(4) if pattern.long_grid[lane][0]), 2)
        self.assertEqual(sum(1 for lane in range(4) if pattern.long_grid[lane][1]), 2)
        self.assertEqual(pattern.visible_notes, 4)
        self.assertEqual(pattern.long_note_starts, 2)
        self.assertEqual(pattern.long_note_ends, 2)

    def test_min_notes_fills_special_pattern_ticks(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=2,
                beat_interval="1",
                min_notes_per_beat=3,
                stair_pattern_chance=100,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=12,
            )
        )

        self.assertEqual(pattern.stair_patterns, 1)
        self.assertEqual(pattern.visible_notes, 6)
        for tick in range(2):
            self.assertEqual(sum(1 for lane in range(4) if pattern.visible_grid[lane][tick]), 3)

    def test_min_notes_fills_long_note_pattern_middle_ticks(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=8,
                beat_interval="1",
                min_notes_per_beat=2,
                stair_pattern_chance=0,
                long_note_pattern_chance=100,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=13,
            )
        )

        self.assertGreaterEqual(pattern.long_note_patterns, 1)
        for tick in range(8):
            note_count = sum(
                1
                for lane in range(4)
                if pattern.visible_grid[lane][tick] or pattern.long_grid[lane][tick]
            )
            self.assertGreaterEqual(note_count, 2)

    def test_osu_stair_generation_respects_key_count(self) -> None:
        raw, visible_notes, long_starts, long_ends, stair_patterns, *_pattern_counts, sparse_adjustments, dense_adjustments, _duration = make_generator_v1_osu_bytes(
            GeneratorV1Options(
                lanes=4,
                generation_count=2,
                beat_interval="1",
                stair_pattern_chance=100,
                density_balance=False,
            )
        )

        self.assertEqual(visible_notes, 4)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertEqual(stair_patterns, 1)
        self.assertEqual(sparse_adjustments, 0)
        self.assertEqual(dense_adjustments, 0)
        self.assertIn(b"CircleSize:4\r\n", raw)
        hitobject_lines = raw.split(b"[HitObjects]\r\n", 1)[1].strip().splitlines()
        self.assertEqual(len(hitobject_lines), 4)
        self.assertTrue(all(b",1,0,0:0:0:0:" in line for line in hitobject_lines))
        times = [int(line.split(b",")[2]) for line in hitobject_lines]
        self.assertEqual(times, [0, 0, 500, 500])

    def test_osu_timestamp_clipboard_uses_start_offset(self) -> None:
        clipboard, visible_notes, long_starts, long_ends, stair_patterns, *_rest = make_generator_v1_osu_timestamp_clipboard_bytes(
            GeneratorV1Options(
                lanes=4,
                generation_count=2,
                beat_interval="1",
                stair_pattern_chance=100,
                density_balance=False,
                seed=1,
            ),
            67061,
        )

        self.assertEqual(visible_notes, 4)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertEqual(stair_patterns, 1)
        self.assertEqual(clipboard, b"01:07:061 (67061|0,67061|1,67561|2,67561|3) -")

    def test_chord_density_pattern_places_double_triple_or_quad(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=1,
                beat_interval="1",
                stair_pattern_chance=0,
                chord_pattern_chance=100,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=3,
            )
        )

        self.assertEqual(pattern.chord_patterns, 1)
        self.assertGreaterEqual(pattern.visible_notes, 2)
        self.assertLessEqual(pattern.visible_notes, 4)

    def test_jack_pattern_repeats_notes_across_ticks(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=4,
                beat_interval="1",
                stair_pattern_chance=0,
                jack_pattern_chance=100,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=4,
            )
        )

        self.assertEqual(pattern.jack_patterns, 1)
        self.assertGreaterEqual(pattern.visible_notes, 2)
        self.assertTrue(any(sum(1 for lane in range(4) if pattern.visible_grid[lane][tick]) > 0 for tick in range(4)))

    def test_long_note_pattern_places_balanced_starts_and_ends(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=8,
                beat_interval="1",
                stair_pattern_chance=0,
                long_note_pattern_chance=100,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=5,
            )
        )

        self.assertGreaterEqual(pattern.long_note_patterns, 1)
        self.assertEqual(pattern.long_note_starts, pattern.long_note_ends)
        self.assertGreater(pattern.long_note_starts, 0)

    def test_other_key_pattern_places_bracket_or_symmetry(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=10,
                generation_count=1,
                beat_interval="1",
                stair_pattern_chance=0,
                other_key_pattern_chance=100,
                density_balance=False,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=6,
            )
        )

        self.assertEqual(pattern.other_key_patterns, 1)
        self.assertEqual(pattern.visible_notes, 2)

    def test_density_balance_reduces_overdense_generation(self) -> None:
        unbalanced = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=24,
                beat_interval="1",
                stair_pattern_chance=0,
                density_balance=False,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
                seed=1,
            )
        )
        balanced = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=24,
                beat_interval="1",
                stair_pattern_chance=0,
                target_density=1,
                density_window=4,
                density_tolerance=0,
                density_strength=100,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
                seed=1,
            )
        )

        self.assertLess(balanced.visible_notes, unbalanced.visible_notes)
        self.assertGreater(balanced.dense_adjustments, 0)

    def test_density_balance_fills_sparse_generation(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=4,
                generation_count=24,
                beat_interval="1",
                stair_pattern_chance=0,
                target_density=2,
                density_window=4,
                density_tolerance=0,
                density_strength=100,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=2,
            )
        )

        self.assertGreater(pattern.visible_notes, 0)
        self.assertGreater(pattern.sparse_adjustments, 0)

    def test_target_density_above_key_count_is_clamped(self) -> None:
        pattern = make_generator_v1_note_pattern(
            GeneratorV1Options(
                lanes=10,
                generation_count=4,
                beat_interval="1",
                target_density=3500,
                density_window=1,
                density_tolerance=25,
                density_strength=100,
                stair_pattern_chance=0,
                empty_single_weight=0,
                empty_long_start_weight=0,
                empty_rest_weight=100,
                seed=8,
            )
        )

        self.assertGreaterEqual(pattern.sparse_adjustments, 1)

    def test_generate_generator_v1_file_writes_osu_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "generator_v1.osu"

            result = generate_generator_v1_chart_file(
                output,
                GeneratorV1Options(lanes=4, generation_count=2, beat_interval="1", stair_pattern_chance=100, density_balance=False),
            )

            self.assertEqual(result.output, output.resolve())
            self.assertEqual(result.stair_patterns, 1)
            self.assertTrue(output.exists())
            self.assertIsNotNone(result.silence_wav)
            assert result.silence_wav is not None
            self.assertTrue(result.silence_wav.exists())


if __name__ == "__main__":
    unittest.main()
