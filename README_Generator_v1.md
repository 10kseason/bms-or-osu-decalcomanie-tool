# Generator v1

`Generator v1` is a fork of the random chart generator. The existing `BMS_Decalcomanie_Tool.exe` is left as-is.

Run `dist\Generator_v1.exe`, `BMS_Decalcomanie_Generator_v1.pyw`, or:

```bat
python bms_generator_v1.py --output "path\to\chart.osu"
python bms_generator_v1.py --output "path\to\chart.bms"
```

For BMS output, `Source BMS for BGM` can point at an existing BMS/BME/BML/PMS. Generator v1 copies its `#WAVxx` table and rearranges its `#xxx01` background-sound lines until the source BMS key-sound end measure, not just the generated note measure count. If the source key-sound section is longer than the source BGM section, the BGM section loops. Keep the generated BMS beside the source audio files, or keep the same relative audio paths.

BMS key extension command follows the selected key count: `4K-8K` outputs `#4K` through `#8K`, `9K` outputs no key extension command, and `10K` outputs `#10K`.

## Minimum Notes Per Beat

- `Minimum notes/beat`: when greater than `0`, that many randomly chosen empty lanes per generated position cannot roll `3a`.
- `Maximum notes/beat`: default `10`. When the number of empty lanes is greater than this value, the excess randomly chosen empty lanes are forced to `3a`.
- If long notes are occupying too many lanes, Generator v1 forces enough `2b` keeps into `1b` ends so the next generated position has room for the minimum.
- If `2a` long-note starts would occupy too many lanes for the next generated position, Generator v1 randomly converts the excess `2a` starts into `1a` single notes.
- Special Generator v1 pattern ticks, such as double-stairs, chords, jacks, long-note patterns, and other-key patterns, are filled up to the same minimum when needed.
- **Generate HitObject clipboard** prompts for a start ms and copies raw `.osu` HitObject rows for manual text editing under `[HitObjects]`.

## Added Pattern

- `Double-stair chance (%)`: default `12.5`.
- A double-stair pattern places adjacent two-note chords and moves by two lanes per generation tick.
- In 10K, ascending double-stair output is `1+2 -> 3+4 -> 5+6 -> 7+8 -> 9+10`; descending is the reverse.
- Direction is randomized between ascending and descending.
- Stair patterns are only started when no long note is currently being held, so the pattern stays readable.

The following reference-pattern families are optional and default to `0%` so old Generator v1 behavior stays stable:

- `Chord/density chance (%)`: places jump/double, hand/triple, or quad chords.
- `Jack chance (%)`: places minijack, jumpjack, or chordjack repetitions.
- `Long-note pattern chance (%)`: places shield, reverse-shield, or inverse-style LN patterns.
- `Other-key chance (%)`: places bracket or symmetrical mirrored patterns.

## Diff Calc Density Balance

Generator v1 also has density balancing enabled by default.

- `Density window`: recent generated positions to inspect, default `16`.
- `Target notes/tick`: target local density per generated position. Blank means auto-calculated from key count and base weights; values above the key count are clamped to the key count.
- `Density tolerance (%)`: no correction while local density is inside this range, default `25`.
- `Density strength (%)`: how strongly sparse/dense sections change probabilities, default `100`.

When the recent section is sparse, Generator v1 raises note/end probabilities. When it is dense, it raises rest/keep probabilities and suppresses stair starts.

## CLI Example

```bat
python bms_generator_v1.py --output "path\to\stair_10k.osu" --keys 10 --generate-count 256 --stair-chance 12.5
python bms_generator_v1.py --output "path\to\balanced_10k.osu" --target-density 3 --density-window 16
python bms_generator_v1.py --output "path\to\pattern_10k.osu" --chord-chance 10 --jack-chance 5 --ln-pattern-chance 5 --other-key-chance 10
python bms_generator_v1.py --output "path\to\min_10k.osu" --keys 10 --generate-count 256 --min-notes-per-beat 2
python bms_generator_v1.py --output "path\to\max_10k.osu" --keys 10 --generate-count 256 --max-notes-per-beat 4
python bms_generator_v1.py --output "path\to\bgm_10k.bms" --source-bms "path\to\source.bms" --keys 10 --generate-count 256
```

Build the fork EXE:

```bat
build_generator_v1_exe.bat
```
