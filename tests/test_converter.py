from pathlib import Path
import tempfile
import unittest

from bms_decalcomanie_converter import (
    ConvertOptions,
    RandomNoteOptions,
    apply_random_osu_section_file,
    bms_key_extension_line,
    convert_bytes,
    convert_file,
    convert_osu_bytes,
    generate_random_chart_file,
    generate_random_bms_file,
    insert_osu_hitobjects,
    make_osu_editor_clipboard_bytes,
    make_random_bms_bytes,
    make_random_note_pattern,
    make_random_osu_bytes,
    make_random_osu_clipboard_bytes,
)


class ConverterTests(unittest.TestCase):
    def test_bms_key_extension_line_rules(self) -> None:
        self.assertEqual(bms_key_extension_line(4), b"#4K\r\n")
        self.assertEqual(bms_key_extension_line(5), b"#5K\r\n")
        self.assertEqual(bms_key_extension_line(8), b"#8K\r\n")
        self.assertIsNone(bms_key_extension_line(9))
        self.assertEqual(bms_key_extension_line(10), b"#10K\r\n")

    def test_visible_and_long_notes_are_mirrored_with_same_sound_ids(self) -> None:
        raw = (
            b"#PLAYER 1\r\n"
            b"#5K\r\n"
            b"#TITLE sample\r\n"
            b"#WAV01 kick.wav\r\n"
            b"#WAV02 snare.wav\r\n"
            b"#00111:0100\r\n"
            b"#00112:0002\r\n"
            b"#00115:0300\r\n"
            b"#00251:0400\r\n"
        )

        converted, mirrored_lines, collisions, warnings = convert_bytes(raw, ConvertOptions())

        self.assertEqual(warnings, [])
        self.assertEqual(collisions, 0)
        self.assertEqual(mirrored_lines, 4)
        self.assertIn(b"#PLAYER 3\r\n", converted)
        self.assertIn(b"#10K\r\n", converted)
        self.assertNotIn(b"#5K\r\n", converted)
        self.assertIn(b"#00125:0100\r\n", converted)
        self.assertIn(b"#00124:0002\r\n", converted)
        self.assertIn(b"#00121:0300\r\n", converted)
        self.assertIn(b"#00265:0400\r\n", converted)
        self.assertIn(b"#WAV01 kick.wav\r\n", converted)
        self.assertIn(b"#WAV02 snare.wav\r\n", converted)

    def test_existing_target_line_is_merged_without_overwriting_notes(self) -> None:
        raw = (
            b"#00111:0100\r\n"
            b"#00125:0002\r\n"
        )

        converted, _mirrored_lines, collisions, warnings = convert_bytes(raw, ConvertOptions())

        self.assertEqual(warnings, [])
        self.assertEqual(collisions, 0)
        self.assertIn(b"#00125:0102\r\n", converted)

    def test_convert_file_writes_beside_source_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "chart.bms"
            source.write_bytes(b"#00111:0100\n")

            result = convert_file(source, ConvertOptions())

            self.assertIsNotNone(result.output)
            assert result.output is not None
            self.assertTrue(result.output.exists())
            self.assertEqual(result.output.parent, source.parent)
            self.assertEqual(result.output.name, "chart_10k_decal.bms")
            output_bytes = result.output.read_bytes()
            self.assertIn(b"#00125:0100\n", output_bytes)
            self.assertIn(b"#10K\n", output_bytes)

    def test_osu_mania_5k_is_repositioned_and_mirrored_to_10k(self) -> None:
        raw = (
            b"osu file format v14\r\n"
            b"\r\n"
            b"[General]\r\n"
            b"AudioFilename: audio.mp3\r\n"
            b"Mode: 3\r\n"
            b"\r\n"
            b"[Metadata]\r\n"
            b"Title:sample\r\n"
            b"Version:5K\r\n"
            b"\r\n"
            b"[Difficulty]\r\n"
            b"CircleSize:5\r\n"
            b"\r\n"
            b"[HitObjects]\r\n"
            b"51,192,1000,1,0,0:0:0:0:\r\n"
            b"256,192,2000,128,0,2500:0:0:0:0:\r\n"
        )

        converted, mirrored_objects, collisions, warnings = convert_osu_bytes(raw, ConvertOptions())

        self.assertEqual(warnings, [])
        self.assertEqual(collisions, 0)
        self.assertEqual(mirrored_objects, 2)
        self.assertIn(b"CircleSize:10\r\n", converted)
        self.assertIn(b"Version:5K [10K Decal]\r\n", converted)
        self.assertIn(b"25,192,1000,1,0,0:0:0:0:\r\n", converted)
        self.assertIn(b"486,192,1000,1,0,0:0:0:0:\r\n", converted)
        self.assertIn(b"128,192,2000,128,0,2500:0:0:0:0:\r\n", converted)
        self.assertIn(b"384,192,2000,128,0,2500:0:0:0:0:\r\n", converted)
        self.assertIn(b"AudioFilename: audio.mp3\r\n", converted)

    def test_osu_editor_clipboard_contains_only_mirrored_hitobjects(self) -> None:
        raw = (
            b"osu file format v14\r\n"
            b"\r\n"
            b"[General]\r\n"
            b"Mode: 3\r\n"
            b"\r\n"
            b"[Metadata]\r\n"
            b"Version:5K\r\n"
            b"\r\n"
            b"[Difficulty]\r\n"
            b"CircleSize:5\r\n"
            b"\r\n"
            b"[HitObjects]\r\n"
            b"51,192,1000,1,0,0:0:0:0:\r\n"
            b"256,192,2000,128,0,2500:0:0:0:0:\r\n"
        )

        clipboard, mirrored_objects, warnings = make_osu_editor_clipboard_bytes(raw)

        self.assertEqual(warnings, [])
        self.assertEqual(mirrored_objects, 2)
        self.assertEqual(
            clipboard,
            b"25,192,1000,1,0,0:0:0:0:\r\n"
            b"486,192,1000,1,0,0:0:0:0:\r\n"
            b"128,192,2000,128,0,2500:0:0:0:0:\r\n"
            b"384,192,2000,128,0,2500:0:0:0:0:\r\n",
        )
        self.assertNotIn(b"[HitObjects]", clipboard)
        self.assertNotIn(b"CircleSize", clipboard)

    def test_random_osu_clipboard_contains_generated_hitobjects_only(self) -> None:
        clipboard, visible_notes, long_starts, long_ends = make_random_osu_clipboard_bytes(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=2,
                lanes=4,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            )
        )

        self.assertEqual(visible_notes, 8)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertEqual(len(clipboard.strip().splitlines()), 8)
        self.assertIn(b"64,192,0,1,0,0:0:0:0:\r\n", clipboard)
        self.assertIn(b"448,192,500,1,0,0:0:0:0:\r\n", clipboard)
        self.assertNotIn(b"[HitObjects]", clipboard)
        self.assertNotIn(b"CircleSize", clipboard)

    def test_random_osu_clipboard_can_start_at_offset(self) -> None:
        clipboard, visible_notes, long_starts, long_ends = make_random_osu_clipboard_bytes(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=2,
                lanes=4,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            ),
            1234,
        )

        self.assertEqual(visible_notes, 8)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertIn(b"64,192,1234,1,0,0:0:0:0:\r\n", clipboard)
        self.assertIn(b"448,192,1734,1,0,0:0:0:0:\r\n", clipboard)

    def test_insert_osu_hitobjects_rejects_key_count_mismatch(self) -> None:
        raw = (
            b"osu file format v14\r\n"
            b"[General]\r\n"
            b"Mode: 3\r\n"
            b"[Difficulty]\r\n"
            b"CircleSize:4\r\n"
            b"[HitObjects]\r\n"
        )

        with self.assertRaises(ValueError):
            insert_osu_hitobjects(raw, b"256,192,1000,1,0,0:0:0:0:\r\n", 5)

    def test_apply_random_osu_section_file_writes_backup_and_sorted_hitobjects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target.osu"
            target.write_bytes(
                b"osu file format v14\r\n"
                b"[General]\r\n"
                b"Mode: 3\r\n"
                b"\r\n"
                b"[Difficulty]\r\n"
                b"CircleSize:4\r\n"
                b"\r\n"
                b"[HitObjects]\r\n"
                b"64,192,2000,1,0,0:0:0:0:\r\n"
            )

            inserted, visible_notes, long_starts, long_ends, backup = apply_random_osu_section_file(
                target,
                RandomNoteOptions(
                    beat_interval="1",
                    generation_count=1,
                    lanes=4,
                    empty_single_weight=100,
                    empty_long_start_weight=0,
                    empty_rest_weight=0,
                ),
                1000,
            )

            self.assertEqual(inserted, 4)
            self.assertEqual(visible_notes, 4)
            self.assertEqual(long_starts, 0)
            self.assertEqual(long_ends, 0)
            self.assertEqual(backup, target.with_suffix(".osu.bak"))
            self.assertTrue(target.with_suffix(".osu.bak").exists())
            hitobject_lines = target.read_bytes().split(b"[HitObjects]\r\n", 1)[1].strip().splitlines()
            self.assertEqual(len(hitobject_lines), 5)
            self.assertTrue(all(b",1000," in line for line in hitobject_lines[:4]))
            self.assertIn(b",2000,", hitobject_lines[-1])

    def test_osu_non_5k_is_rejected(self) -> None:
        raw = (
            b"osu file format v14\n"
            b"[General]\n"
            b"Mode: 3\n"
            b"[Difficulty]\n"
            b"CircleSize:4\n"
            b"[HitObjects]\n"
            b"64,192,1000,1,0,0:0:0:0:\n"
        )

        with self.assertRaises(ValueError):
            convert_osu_bytes(raw, ConvertOptions())

    def test_convert_file_accepts_osu_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "chart.osu"
            source.write_bytes(
                b"osu file format v14\n"
                b"[General]\n"
                b"Mode: 3\n"
                b"[Difficulty]\n"
                b"CircleSize:5\n"
                b"[HitObjects]\n"
                b"51,192,1000,1,0,0:0:0:0:\n"
            )

            result = convert_file(source, ConvertOptions())

            self.assertIsNotNone(result.output)
            assert result.output is not None
            self.assertEqual(result.output.name, "chart_10k_decal.osu")
            self.assertIn(b"CircleSize:10\n", result.output.read_bytes())

    def test_random_generator_creates_direct_10k_visible_channels(self) -> None:
        raw, visible_notes, long_starts, long_ends = make_random_bms_bytes(
            RandomNoteOptions(
                beat_interval="1",
                measures=1,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            )
        )

        self.assertEqual(visible_notes, 40)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertIn(b"#PLAYER 3\r\n", raw)
        self.assertIn(b"#10K\r\n", raw)
        for channel in (b"11", b"12", b"13", b"14", b"15", b"21", b"22", b"23", b"24", b"25"):
            self.assertIn(b"#001" + channel + b":01010101\r\n", raw)

    def test_random_generator_respects_key_count_and_generation_count_for_bms(self) -> None:
        raw, visible_notes, long_starts, long_ends = make_random_bms_bytes(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=3,
                lanes=4,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            )
        )

        self.assertEqual(visible_notes, 12)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertIn(b"#PLAYER 1\r\n", raw)
        self.assertIn(b"#4K\r\n", raw)
        self.assertNotIn(b"#9K\r\n", raw)
        for channel in (b"11", b"12", b"13", b"14"):
            self.assertIn(b"#001" + channel + b":01010100\r\n", raw)
        self.assertNotIn(b"#00115:", raw)

    def test_random_generator_omits_bms_key_extension_for_9k(self) -> None:
        raw, *_counts = make_random_bms_bytes(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=1,
                lanes=9,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            )
        )

        self.assertIn(b"#PLAYER 3\r\n", raw)
        self.assertNotIn(b"#9K\r\n", raw)
        self.assertNotIn(b"#10K\r\n", raw)

    def test_random_generator_closes_holding_long_notes_on_final_tick(self) -> None:
        raw, visible_notes, long_starts, long_ends = make_random_bms_bytes(
            RandomNoteOptions(
                beat_interval="1",
                measures=1,
                empty_single_weight=0,
                empty_long_start_weight=100,
                empty_rest_weight=0,
                holding_long_end_weight=0,
                holding_keep_weight=100,
            )
        )

        self.assertEqual(visible_notes, 0)
        self.assertEqual(long_starts, 10)
        self.assertEqual(long_ends, 10)
        for channel in (b"51", b"52", b"53", b"54", b"55", b"61", b"62", b"63", b"64", b"65"):
            self.assertIn(b"#001" + channel + b":01000001\r\n", raw)

    def test_random_generator_min_notes_prevents_empty_rest_action(self) -> None:
        pattern = make_random_note_pattern(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=3,
                lanes=4,
                min_notes_per_beat=2,
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

    def test_random_generator_max_notes_forces_excess_empty_lanes_to_rest(self) -> None:
        pattern = make_random_note_pattern(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=3,
                lanes=10,
                max_notes_per_beat=4,
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

    def test_random_generator_min_notes_above_max_notes_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_random_note_pattern(
                RandomNoteOptions(
                    lanes=10,
                    generation_count=1,
                    min_notes_per_beat=5,
                    max_notes_per_beat=4,
                )
            )

    def test_random_generator_min_notes_forces_long_note_end_when_all_keys_held(self) -> None:
        pattern = make_random_note_pattern(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=3,
                lanes=4,
                min_notes_per_beat=2,
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

    def test_random_generator_min_notes_converts_excess_long_starts_to_singles(self) -> None:
        pattern = make_random_note_pattern(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=2,
                lanes=4,
                min_notes_per_beat=2,
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

    def test_random_generator_writes_bms_and_silent_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "random.bms"

            result = generate_random_bms_file(
                output,
                RandomNoteOptions(measures=1, beat_interval="1", seed=7),
            )

            self.assertEqual(result.output, output.resolve())
            self.assertTrue(output.exists())
            self.assertIsNotNone(result.silence_wav)
            assert result.silence_wav is not None
            self.assertTrue(result.silence_wav.exists())
            self.assertIn(b"#WAV01 _random_note_silence.wav\r\n", output.read_bytes())

    def test_random_generator_creates_direct_10k_osu_hitobjects(self) -> None:
        raw, visible_notes, long_starts, long_ends, _audio_duration = make_random_osu_bytes(
            RandomNoteOptions(
                beat_interval="1",
                measures=1,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            )
        )

        self.assertEqual(visible_notes, 40)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertIn(b"Mode: 3\r\n", raw)
        self.assertIn(b"CircleSize:10\r\n", raw)
        self.assertIn(b"0,500,4,1,0,100,1,0\r\n", raw)
        self.assertIn(b"25,192,0,1,0,0:0:0:0:\r\n", raw)
        self.assertIn(b"486,192,1500,1,0,0:0:0:0:\r\n", raw)

    def test_random_generator_respects_key_count_and_generation_count_for_osu(self) -> None:
        raw, visible_notes, long_starts, long_ends, _audio_duration = make_random_osu_bytes(
            RandomNoteOptions(
                beat_interval="1",
                generation_count=2,
                lanes=4,
                empty_single_weight=100,
                empty_long_start_weight=0,
                empty_rest_weight=0,
            )
        )

        self.assertEqual(visible_notes, 8)
        self.assertEqual(long_starts, 0)
        self.assertEqual(long_ends, 0)
        self.assertIn(b"CircleSize:4\r\n", raw)
        self.assertIn(b"64,192,0,1,0,0:0:0:0:\r\n", raw)
        self.assertIn(b"448,192,500,1,0,0:0:0:0:\r\n", raw)
        self.assertNotIn(b"486,192,", raw)

    def test_random_generator_creates_direct_10k_osu_long_notes(self) -> None:
        raw, visible_notes, long_starts, long_ends, _audio_duration = make_random_osu_bytes(
            RandomNoteOptions(
                beat_interval="1",
                measures=1,
                empty_single_weight=0,
                empty_long_start_weight=100,
                empty_rest_weight=0,
                holding_long_end_weight=0,
                holding_keep_weight=100,
            )
        )

        self.assertEqual(visible_notes, 0)
        self.assertEqual(long_starts, 10)
        self.assertEqual(long_ends, 10)
        self.assertIn(b"25,192,0,128,0,1500:0:0:0:0:\r\n", raw)
        self.assertIn(b"486,192,0,128,0,1500:0:0:0:0:\r\n", raw)

    def test_random_generator_writes_osu_and_silent_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "random.osu"

            result = generate_random_chart_file(
                output,
                RandomNoteOptions(measures=1, beat_interval="1", seed=7),
            )

            self.assertEqual(result.output, output.resolve())
            self.assertTrue(output.exists())
            self.assertIsNotNone(result.silence_wav)
            assert result.silence_wav is not None
            self.assertTrue(result.silence_wav.exists())
            self.assertIn(b"AudioFilename: _random_note_silence.wav\r\n", output.read_bytes())


if __name__ == "__main__":
    unittest.main()
