# BMS/osu 5K to 10K Decalcomanie Tool

Development: CircusGalop & 윾이 & Codex

Korean documentation: [README_KO.md](README_KO.md)

Double-click `dist\BMS_Decalcomanie_Tool.exe`, `run_decalcomanie_tool.bat`, or `BMS_Decalcomanie_Tool.pyw`, add BMS or osu!mania files, then click **Convert to 10K decalcomanie**.

The original files are not overwritten. By default, converted files are written beside each source file so existing relative BMS `#WAVxx` paths and osu `AudioFilename` paths still work. If you choose another output folder, make sure the referenced sound files are available from that folder too.

The GUI also has **Copy selected osu decal notes to clipboard** for selected `.osu` files. It copies only mirrored HitObject rows. **Open random chart generator** creates direct BMS or osu!mania files, copies generated osu timestamp text, or inserts a generated section into an existing `.osu` file. BMS output uses visible lanes in order from `11-15` then `21-25`, with long-note lanes `51-55` then `61-65`; osu output uses `Mode: 3` and sets `CircleSize` to the key count.

## BMS conversion rule

- Keep original 5K lanes `11-15`.
- Copy the same note object IDs to the opposite side in reverse order:
  - `11 -> 25`
  - `12 -> 24`
  - `13 -> 23`
  - `14 -> 22`
  - `15 -> 21`
- Copy long-note lanes when enabled:
  - `51 -> 65`
  - `52 -> 64`
  - `53 -> 63`
  - `54 -> 62`
  - `55 -> 61`
- Set `#PLAYER 3` by default so the output is treated as double play.
- Replace or add the BMS key extension command as `#10K`.
- Do not copy or rename sound files. The output reuses the existing `#WAVxx` key-sound definitions and note IDs.

## osu!mania conversion rule

- Accept `.osu` files with `Mode: 3` and `CircleSize: 5`.
- Set `CircleSize:10`.
- Move the original 5K columns into the left half of the 10K field.
- Copy each hit object to the right half in reverse order.
- Preserve the rest of each hit-object line, including hold end times and hit-sample fields.
- Keep `AudioFilename` unchanged and append ` [10K Decal]` to the difficulty `Version`.
- The clipboard action emits the same mirrored hit objects without the `.osu` file sections, for manual text editing under `[HitObjects]`.

## CLI

```bat
python bms_decalcomanie_converter.py "path\to\chart.bms"
python bms_decalcomanie_converter.py "path\to\chart.osu"
python bms_decalcomanie_converter.py "path\to\folder" -o "path\to\output"
```

## Random chart generator

The generator checks each selected key lane at a fixed beat interval and can write either BMS or osu!mania based on the output extension.

- `Key count`: lane count from `1` to `10`.
- BMS key extension command: `4K-8K` outputs `#4K` through `#8K`, `9K` outputs no key extension command, and `10K` outputs `#10K`.
- `Generation count`: how many beat-interval positions to roll. For example, `256` at `0.25` beat interval makes 16 measures of 16th-note positions.
- `Minimum notes/beat`: when greater than `0`, that many randomly chosen empty lanes per generated position cannot roll `3a`. If too many lanes are being held by long notes, enough `2b` keeps are forced into `1b` ends so the next position can still create the minimum.
- `Maximum notes/beat`: default `10`. When the number of empty lanes is greater than this value, the excess randomly chosen empty lanes are forced to `3a`.
- If `2a` long-note starts would leave too few free lanes for the next position, the excess `2a` starts are randomly converted into `1a` single notes.

- Empty lane:
  - `1a`: create a single note, default weight `25`
  - `2a`: start a long note, default weight `50`
  - `3a`: create no note, default weight `25`
- Holding long note:
  - `1b`: end the long note, default weight `25`
  - `2b`: keep holding, default weight `75`

`Beat interval` is in beats and must divide one 4-beat measure exactly, such as `1`, `0.5`, `0.25`, or `1/8`. The generator writes a silent WAV named `_random_note_silence.wav` beside the output if it does not already exist. BMS uses it as a key-sound; osu uses it as `AudioFilename`.

Use **Generate random clipboard** when you want osu timestamp text for manual text editing. The click prompts for a start ms and copies text like `01:07:061 (67061|3,67061|2) -`.

The osu! client does not reliably paste raw text as editor objects. For editor-section workflows, choose a target `.osu` file and click **Apply random section to osu file**. It inserts the generated rows at `Clipboard/file start time (ms)`, sorts the `[HitObjects]` section by time, checks that `CircleSize` matches `Key count`, and writes a one-time `.osu.bak` backup beside the target file.

```bat
python bms_decalcomanie_converter.py --random-output "path\to\random_10k.bms" --bpm 150 --beat-interval 0.25 --measures 16
python bms_decalcomanie_converter.py --random-output "path\to\random_10k.osu" --bpm 150 --beat-interval 0.25 --measures 16
python bms_decalcomanie_converter.py --random-output "path\to\random_7k.osu" --keys 7 --generate-count 128
python bms_decalcomanie_converter.py --random-output "path\to\random_10k.osu" --keys 10 --generate-count 256 --min-notes-per-beat 2
python bms_decalcomanie_converter.py --random-output "path\to\random_10k.osu" --keys 10 --generate-count 256 --max-notes-per-beat 4
```

## Build EXE

```bat
build_exe.bat
```

The EXE is written to `dist\BMS_Decalcomanie_Tool.exe`.

Options:

- `--no-player-3`: leave `#PLAYER` unchanged.
- `--no-ln`: do not mirror long-note channels.
- `--mirror-invisible`: also mirror invisible channels `31-35` to `45-41`.
- `--overwrite`: overwrite the default output filename.
- `--random-output`: create a direct random BMS or osu!mania file.
- `--keys`: random output key count, `1-10`.
- `--generate-count`: number of beat-interval positions to generate. Alias: `--note-count`.
- `--min-notes-per-beat`: minimum notes to force per generated beat position.
- `--max-notes-per-beat`: maximum empty lanes allowed to roll non-`3a` per generated beat position. Default: `10`.
- `--weight-single`, `--weight-ln-start`, `--weight-empty`, `--weight-ln-end`, `--weight-ln-keep`: random generator weights.
- `--seed`: repeat a random generator result.
- `--random-overwrite`: allow overwriting an existing random output file.
