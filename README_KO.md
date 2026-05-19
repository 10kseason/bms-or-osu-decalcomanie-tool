# BMS/osu 데칼코마니 툴

개발: CircusGalop & 윾이 & Codex

5K BMS 또는 osu!mania 차분을 10K 데칼코마니 형태로 변환하고, 랜덤 BMS/osu!mania 패턴을 생성하는 Windows용 Python/Tkinter 도구입니다.

## 실행

다음 중 하나를 실행합니다.

```bat
dist\BMS_Decalcomanie_Tool.exe
run_decalcomanie_tool.bat
python BMS_Decalcomanie_Tool.pyw
```

GUI에서 BMS 또는 osu!mania 파일을 추가한 뒤 **Convert to 10K decalcomanie**를 누르면 됩니다.

원본 파일은 덮어쓰지 않습니다. 출력 폴더를 따로 지정하지 않으면 원본 옆에 변환 파일을 만듭니다. BMS `#WAVxx` 경로나 osu `AudioFilename` 상대 경로를 유지하려면 음원 파일도 같은 기준 경로에서 접근 가능해야 합니다.

## BMS 변환 규칙

- 원래 5K 라인 `11-15`는 유지합니다.
- 같은 노트 오브젝트 ID를 반대편 라인에 역순으로 복사합니다.
- 기본 매핑은 `11 -> 25`, `12 -> 24`, `13 -> 23`, `14 -> 22`, `15 -> 21`입니다.
- 롱노트 복사가 켜져 있으면 `51-55`를 `65-61`로 복사합니다.
- 기본적으로 `#PLAYER 3`을 설정합니다.
- 키 확장 명령은 `#10K`로 추가하거나 교체합니다.
- 음원 파일은 복사하거나 이름을 바꾸지 않습니다.

## osu!mania 변환 규칙

- `Mode: 3`, `CircleSize: 5`인 `.osu` 파일을 받습니다.
- `CircleSize:10`으로 변경합니다.
- 원래 5K 컬럼은 10K 왼쪽 절반으로 이동합니다.
- 각 노트를 오른쪽 절반에 역순으로 복사합니다.
- 홀드 노트 종료 시간과 히트샘플 필드는 유지합니다.
- 난이도 `Version` 뒤에 ` [10K Decal]`을 붙입니다.

## 랜덤 차트 생성기

GUI의 **Open random chart generator**에서 랜덤 BMS/osu!mania 차트를 만들 수 있습니다.

주요 옵션:

- `Key count`: 1K부터 10K까지 선택합니다.
- `Generation count`: 생성할 박자 위치 수입니다.
- `Beat interval`: `1`, `0.5`, `0.25`, `1/8`처럼 한 마디를 나눌 박자 간격입니다.
- `Minimum notes/beat`: 각 위치에서 최소 몇 개의 노트가 나오게 할지 정합니다.
- `Maximum notes/beat`: 기본값은 `10`입니다. 빈 라인 수가 이 값보다 크면 초과분은 랜덤하게 `3a`로 강제됩니다.
- `1a`: 빈 라인에 단노트를 생성하는 가중치입니다.
- `2a`: 빈 라인에 롱노트를 시작하는 가중치입니다.
- `3a`: 빈 라인을 비워두는 가중치입니다.
- `1b`: 누르고 있는 롱노트를 끝내는 가중치입니다.
- `2b`: 롱노트를 유지하는 가중치입니다.

**Generate random clipboard**는 `Clipboard/file start time (ms)` 값을 기준으로 raw `.osu` HitObject 줄을 클립보드에 복사합니다.

예시:

```text
64,192,67061,1,0,0:0:0:0:
192,192,67061,1,0,0:0:0:0:
```

osu 에디터에 직접 붙여넣는 용도가 아니라, `.osu` 파일을 메모장 등으로 열고 `[HitObjects]` 섹션 아래에 붙여넣는 용도입니다. GUI에서 **Apply random section to osu file**을 쓰면 이 삽입 과정을 파일에 직접 적용할 수 있습니다.

## Generator v1

`BMS_Decalcomanie_Generator_v1.pyw` 또는 `bms_generator_v1.py`는 랜덤 생성기 확장판입니다.

추가 기능:

- 더블 계단 패턴
- 코드/밀도 패턴
- 잭 패턴
- 롱노트 패턴
- 좌우 대칭/브라켓 패턴
- Diff Calc 기반 밀도 보정
- 소스 BMS의 `#WAV` 테이블과 `#xxx01` BGM 라인 재사용

자세한 내용은 [README_Generator_v1.md](README_Generator_v1.md)를 참고하면 됩니다.

## CLI 예시

```bat
python bms_decalcomanie_converter.py "path\to\chart.bms"
python bms_decalcomanie_converter.py "path\to\chart.osu"
python bms_decalcomanie_converter.py "path\to\folder" -o "path\to\output"
python bms_decalcomanie_converter.py --random-output "path\to\random_10k.osu" --keys 10 --generate-count 256
```

Generator v1:

```bat
python bms_generator_v1.py --output "path\to\stair_10k.osu" --keys 10 --generate-count 256 --stair-chance 12.5
python bms_generator_v1.py --output "path\to\bgm_10k.bms" --source-bms "path\to\source.bms" --keys 10 --generate-count 256
```

## 테스트

```bat
python -m unittest discover -s tests -p "test_*.py"
```

## 빌드

메인 EXE:

```bat
build_exe.bat
```

Generator v1 EXE:

```bat
build_generator_v1_exe.bat
```

빌드 결과물은 `dist\`에 생성되며, GitHub에는 소스만 올리고 빌드 결과물은 포함하지 않습니다.
