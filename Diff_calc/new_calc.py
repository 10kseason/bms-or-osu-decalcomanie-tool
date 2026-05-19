"""
new_calc.py - 선형 회귀 기반 난이도 계산 모델

기존 calc.py의 복잡한 모델 대신, NPS 기반 선형 회귀 모델을 사용합니다.
BMS 데이터 분석 결과, 단순 선형 회귀가 더 정확한 결과를 보여줍니다 (MAE 1.12).
"""
import time
from bisect import bisect_left
import math


def calculate_time_deltas(judgments, type_time_delta="C"):
    """
    판정범위 기반 time_delta(ms) 계산.

    - score: score손해비(=config score%)가 100인 판정 범위에서 계산(기존과 동일)
    - acc: config의 `type_time_delta`에 따라 계산 방식 분기

    Args:
        judgments: config.yaml의 판정 리스트
            각 판정: [이름, +범위(단노트), -범위(단노트), LN머리+, LN머리-, LN꼬리+, LN꼬리-, 점수%, 정확도%]
        type_time_delta: "A" | "B" | "C"(default)

    Returns:
        dict: {
            'time_delta_score_plus_rice': int,
            'time_delta_score_minus_rice': int,
            'time_delta_score_plus_head': int,
            'time_delta_score_minus_head': int,
            'time_delta_score_plus_tail': int,
            'time_delta_score_minus_tail': int,
            'time_delta_acc_plus_rice': int,
            'time_delta_acc_minus_rice': int,
            'time_delta_acc_plus_head': int,
            'time_delta_acc_minus_head': int,
            'time_delta_acc_plus_tail': int,
            'time_delta_acc_minus_tail': int,
        }
    """

    def _safe_get(arr, idx):
        return arr[idx] if isinstance(arr, (list, tuple)) and idx < len(arr) else None

    def _to_int_ms(value, *, absolute=False):
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if absolute:
            v = abs(v)
        return int(v)

    suffix_defs = {
        'plus_rice': (1, False),
        'minus_rice': (2, True),
        'plus_head': (3, False),
        'minus_head': (4, True),
        'plus_tail': (5, False),
        'minus_tail': (6, True),
    }

    result = {
        'time_delta_score_plus_rice': 0,
        'time_delta_score_minus_rice': 0,
        'time_delta_score_plus_head': 0,
        'time_delta_score_minus_head': 0,
        'time_delta_score_plus_tail': 0,
        'time_delta_score_minus_tail': 0,
        'time_delta_acc_plus_rice': 0,
        'time_delta_acc_minus_rice': 0,
        'time_delta_acc_plus_head': 0,
        'time_delta_acc_minus_head': 0,
        'time_delta_acc_plus_tail': 0,
        'time_delta_acc_minus_tail': 0,
    }

    if not judgments:
        return result

    ttd = str(type_time_delta or "C").strip().upper() or "C"

    score_max = {k: 0 for k in suffix_defs}
    acc95_max = {k: 0 for k in suffix_defs}
    acc95_found = {k: False for k in suffix_defs}

    for j in judgments:
        score_pct = _safe_get(j, 7)
        acc_pct = _safe_get(j, 8)

        if score_pct == 100:
            for suffix, (idx, absolute) in suffix_defs.items():
                v = _to_int_ms(_safe_get(j, idx), absolute=absolute)
                if v is not None:
                    score_max[suffix] = max(score_max[suffix], v)

        if ttd in ("A", "B"):
            if acc_pct is not None and acc_pct >= 95:
                for suffix, (idx, absolute) in suffix_defs.items():
                    v = _to_int_ms(_safe_get(j, idx), absolute=absolute)
                    if v is not None:
                        acc95_max[suffix] = max(acc95_max[suffix], v)
                        acc95_found[suffix] = True

    for suffix in suffix_defs:
        result[f'time_delta_score_{suffix}'] = score_max[suffix]

    if ttd == "A":
        for suffix in suffix_defs:
            score_val = score_max[suffix]

            if acc95_found[suffix]:
                acc_val = max(score_val, max(0, acc95_max[suffix] - 1))
            else:
                acc_val = score_val
            result[f'time_delta_acc_{suffix}'] = int(acc_val)
        return result

    if ttd == "B":
        for suffix in suffix_defs:
            score_val = score_max[suffix]

            if acc95_found[suffix]:
                acc_blend = max(score_val, (score_val * 0.5) + (acc95_max[suffix] * 0.5))
                acc_val = int(acc_blend)
            else:
                acc_val = score_val
            result[f'time_delta_acc_{suffix}'] = int(acc_val)
        return result

    for suffix in suffix_defs:
        result[f'time_delta_acc_{suffix}'] = result[f'time_delta_score_{suffix}']

    return result


def _apply_judgment_overrides(judgments, *, zero_poor_mode=False, perfect_play=False):
    if not judgments:
        return judgments

    adjusted = []
    for row in judgments:
        if not isinstance(row, (list, tuple)):
            adjusted.append(row)
            continue
        entry = list(row)
        if zero_poor_mode:
            if len(entry) > 7 and entry[7] is None:
                entry[7] = 0
            if len(entry) > 8 and entry[8] is None:
                entry[8] = 0
        if perfect_play:
            score_pct = None
            if len(entry) > 7 and entry[7] is not None:
                try:
                    score_pct = float(entry[7])
                except (TypeError, ValueError):
                    score_pct = None
            if score_pct is not None and score_pct < 100:
                if len(entry) > 7 and entry[7] is not None:
                    entry[7] = 0
                if len(entry) > 8 and entry[8] is not None:
                    entry[8] = 0
        adjusted.append(entry)

    return adjusted


def get_judgment_by_timing(ms_offset, judgments, note_type='rice', use_full_range=True, return_gauge=False):
    """
    노트 타입별로 다른 판정범위 인덱스를 사용하여 점수/정확도/게이지 손해비 계산

    Args:
        ms_offset: 밀림 ms (양수)
        judgments: 판정 리스트
        note_type: 'rice' (단노트), 'head' (롱노트 머리), 'tail' (롱노트 꼬리)
        use_full_range: True면 양+음 절대값 합산, False면 양의 범위만
        return_gauge: True면 게이지 손해비까지 반환

    Returns:
        (score_ratio, acc_ratio) 또는 (score_ratio, acc_ratio, gauge_ratio)
        판정 범위를 벗어나면 None 반환
    """
    if judgments is None:
        if return_gauge:
            return (100, 100, 100)
        return (100, 100)
    
    # 노트 타입별 인덱스 매핑
    # 판정 구조: [이름, +범위(단노트), -범위(단노트), LN머리+, LN머리-, LN꼬리+, LN꼬리-, 점수%, 정확도%]
    if note_type == 'rice':
        plus_idx, minus_idx = 1, 2
    elif note_type == 'head':
        plus_idx, minus_idx = 3, 4
    elif note_type == 'tail':
        plus_idx, minus_idx = 5, 6
    else:
        plus_idx, minus_idx = 1, 2  # 기본값: 단노트
    
    for j in judgments:
        if len(j) < 9:
            continue
        
        plus_range = j[plus_idx]   # +범위
        minus_range = j[minus_idx]  # -범위
        score_pct = j[7]
        acc_pct = j[8]
        gauge_pct = j[9] if len(j) > 9 else None
        
        # null 범위 처리: null = 무한대 (해당 판정이 모든 오프셋에 적용)
        if plus_range is None:
            final_score = 0 if score_pct is None else score_pct
            final_acc = 0 if acc_pct is None else acc_pct
            final_gauge = 0 if gauge_pct is None else gauge_pct
            if return_gauge:
                return (final_score, final_acc, final_gauge)
            return (final_score, final_acc)
        
        # 범위 계산
        if use_full_range:
            # 전체 범위: 양 + 음 절대값 합산
            total_range = abs(plus_range)
            if minus_range is not None:
                total_range += abs(minus_range)
            elif minus_range is None:
                # minus_range가 None이면 무한대 → 이 판정 적용
                final_score = 0 if score_pct is None else score_pct
                final_acc = 0 if acc_pct is None else acc_pct
                final_gauge = 0 if gauge_pct is None else gauge_pct
                if return_gauge:
                    return (final_score, final_acc, final_gauge)
                return (final_score, final_acc)
        else:
            # 양의 범위만
            total_range = abs(plus_range)
        
        # 범위 내에 있는지 확인
        if ms_offset <= total_range:
            final_score = 0 if score_pct is None else score_pct
            final_acc = 0 if acc_pct is None else acc_pct
            final_gauge = 0 if gauge_pct is None else gauge_pct
            if return_gauge:
                return (final_score, final_acc, final_gauge)
            return (final_score, final_acc)
    
    # 모든 판정 범위를 벗어나면 (None, None) 반환
    if return_gauge:
        return (None, None, None)
    return (None, None)


def get_judgment_result_typed(ms_offset, judgments, note_type='rice'):
    """
    노트 타입별 판정 결과 반환 (양의범위/전체범위 평균) - JDS 계산용
    
    Args:
        ms_offset: ms 밀림값 (양수)
        judgments: 판정 리스트
        note_type: 'rice', 'head', 'tail'
    
    Returns:
        (score_ratio, acc_ratio): 0~100 범위, 또는 (None, None) if all out of range
    
    Note:
        JDS 계산용: null 판정은 0으로 처리
    """
    result_positive = get_judgment_by_timing(ms_offset, judgments, note_type, use_full_range=False)
    result_full = get_judgment_by_timing(ms_offset, judgments, note_type, use_full_range=True)
    
    # 둘 다 None이면 None 반환
    if result_positive[0] is None and result_full[0] is None:
        return (None, None)
    
    # 하나만 None이면 다른 하나 사용
    if result_positive[0] is None:
        return result_full
    if result_full[0] is None:
        return result_positive
    
    # 두 결과의 평균
    avg_score = (result_positive[0] + result_full[0]) / 2
    avg_acc = (result_positive[1] + result_full[1]) / 2
    
    return (avg_score, avg_acc)



def _get_judgment_for_fds_rds_values(timing_offset_ms, judgments, note_type='rice'):
    """
    FDS/RDS용 판정손해비 계산 (점수/정확도/게이지)
    """
    if judgments is None:
        return (100, 100, 100)

    # 노트 타입별 인덱스 매핑
    # 판정 구조: [이름, +범위(단노트), -범위(단노트), LN머리+, LN머리-, LN꼬리+, LN꼬리-, 점수%, 정확도%, 게이지%]
    if note_type == 'rice':
        plus_idx, minus_idx = 1, 2
    elif note_type == 'head':
        plus_idx, minus_idx = 3, 4
    elif note_type == 'tail':
        plus_idx, minus_idx = 5, 6
    else:
        plus_idx, minus_idx = 1, 2

    abs_offset = abs(timing_offset_ms)
    is_late = timing_offset_ms >= 0  # 양수 = 늦게 침

    for j in judgments:
        if len(j) < 9:
            continue

        plus_range = j[plus_idx]   # +범위 (늦게 칠 때)
        minus_range = j[minus_idx]  # -범위 (빨리 칠 때)
        score_pct = j[7]
        acc_pct = j[8]
        gauge_pct = j[9] if len(j) > 9 else None

        target_range = plus_range if is_late else minus_range

        if target_range is None:
            return (score_pct, acc_pct, gauge_pct)

        if abs_offset <= abs(target_range):
            return (score_pct, acc_pct, gauge_pct)

    if judgments:
        last_j = judgments[-1]
        if len(last_j) >= 9:
            return (last_j[7], last_j[8], last_j[9] if len(last_j) > 9 else None)

    return (None, None, None)


def get_judgment_for_fds_rds(timing_offset_ms, judgments, note_type='rice'):
    """
    FDS/RDS용 판정손해비 계산

    Args:
        timing_offset_ms: 타이밍 오프셋 (ms)
            - 양수: 늦게 침 → 양의 판정범위 사용
            - 음수: 빨리 침 → 음의 판정범위 사용
        judgments: 판정 리스트
        note_type: 'rice', 'head', 'tail'

    Returns:
        (score_ratio, acc_ratio): 0~100 범위

    Note:
        - null 범위: config 값 그대로 반환 (0 처리 안함)
        - JDS와 다르게 양/음 방향에 따라 해당 범위만 사용
    """
    score_ratio, acc_ratio, _ = _get_judgment_for_fds_rds_values(timing_offset_ms, judgments, note_type)
    return (score_ratio, acc_ratio)


# ====================================================================
# OD 선형보간 함수 (OSU Stable/Lazer)
# ====================================================================

def interpolate_osu_judgments(od, config, use_lazer=False):
    """
    OSU OD 값에 따라 판정범위를 선형보간
    
    Args:
        od (float): OverallDifficulty 값 (0~10)
        config (dict): config.yaml 로드된 데이터
        use_lazer (bool): True면 osu_lazer_od*, False면 osu_od* 사용
    
    Returns:
        list: 보간된 judgments 리스트
    """
    od_points = [0, 5, 8, 10]
    
    if use_lazer:
        preset_pattern = 'osu_lazer_od{}'
    else:
        preset_pattern = 'osu_od{}'
    
    od = max(0, min(10, od))
    
    # 정확한 값이면 해당 프리셋 직접 반환
    for point in od_points:
        if abs(od - point) < 0.001:
            preset_key = preset_pattern.format(point)
            if 'judgment_presets' in config and preset_key in config['judgment_presets']:
                return config['judgment_presets'][preset_key].get('judgments', None)
            return None
    
    # 보간할 두 OD 찾기
    lower_od = 0
    upper_od = 10
    for i, point in enumerate(od_points):
        if point < od:
            lower_od = point
        if point > od:
            upper_od = point
            break
    
    lower_key = preset_pattern.format(lower_od)
    upper_key = preset_pattern.format(upper_od)
    
    if 'judgment_presets' not in config:
        return None
    
    if lower_key not in config['judgment_presets'] or upper_key not in config['judgment_presets']:
        print(f"[Warning] 보간용 프리셋 없음: {lower_key} 또는 {upper_key}")
        return None
    
    lower_judgments = config['judgment_presets'][lower_key].get('judgments', [])
    upper_judgments = config['judgment_presets'][upper_key].get('judgments', [])
    
    if not lower_judgments or not upper_judgments:
        return None
    
    ratio = (od - lower_od) / (upper_od - lower_od) if upper_od != lower_od else 0
    
    interpolated = []
    for i, (lower_j, upper_j) in enumerate(zip(lower_judgments, upper_judgments)):
        if len(lower_j) < 9 or len(upper_j) < 9:
            interpolated.append(lower_j)
            continue
        
        new_j = [lower_j[0]]
        
        for idx in range(1, 7):
            lower_val = lower_j[idx]
            upper_val = upper_j[idx]
            
            if lower_val is None or upper_val is None:
                # 둘 중 하나가 null이면 null 유지
                new_j.append(None)
            else:
                interp_val = lower_val + ratio * (upper_val - lower_val)
                new_j.append(round(interp_val, 9))
        
        new_j.append(lower_j[7])
        new_j.append(lower_j[8])
        if len(lower_j) > 9:
            new_j.append(lower_j[9])
        elif len(upper_j) > 9:
            new_j.append(upper_j[9])
        
        interpolated.append(new_j)
    
    print(f"[INTERPOLATE] OD {od}: {lower_key} + {upper_key} (ratio={ratio:.3f})")
    return interpolated


# ====================================================================
# NPS v2 / Distance / Note Difficulty 공용 헬퍼
# ====================================================================

_NOTE_TYPE_ORDER = {
    'ln_end': 0,    # tail
    'note': 1,      # rice
    'ln_start': 2,  # head
}


def _get_note_type_order(note_type):
    return _NOTE_TYPE_ORDER.get(note_type, 1)


def _sort_notes_for_difficulty(notes):
    return sorted(
        notes,
        key=lambda n: (
            n.get('time', 0),
            _get_note_type_order(n.get('type', 'note')),
            n.get('column', 1),
        ),
    )


def _normalize_mode_name(mode_name):
    if not mode_name:
        return None
    return str(mode_name).strip().lower().replace(' ', '')


def _resolve_weights_key(key_mode, mode_name):
    normalized = _normalize_mode_name(mode_name)
    if normalized in {'5+1', '5+1k', '5p1', '5p1k'}:
        return 'weights_5p1k'
    if normalized in {'7+1', '7+1k', '7p1', '7p1k'}:
        return 'weights_7p1k'
    # BMS DP scratch 모드: DP12(10+2), DP16(14+2)
    if normalized in {'10+2', '10+2k', '10p2', '10p2k', 'dp12'}:
        return 'weights_10p2k'
    if normalized in {'14+2', '14+2k', '14p2', '14p2k', 'dp16'}:
        return 'weights_14p2k'
    return f'weights_{key_mode}k'


def _get_scratch_indices(key_mode, mode_name):
    normalized = _normalize_mode_name(mode_name)
    if normalized in {'5+1', '5+1k', '5p1', '5p1k', '7+1', '7+1k', '7p1', '7p1k'}:
        return [0]
    if normalized in {'10+2', '10+2k', '10p2', '10p2k', '14+2', '14+2k', '14p2', '14p2k', 'dp12', 'dp16'}:
        if key_mode >= 2:
            return [0, key_mode - 1]
    return []


# _DEFAULT_TYPE_DISTANCE_MATRIX = (
#     (0.0, 1.0, 1.0),
#     (1.0, 0.0, 1.0),
#     (1.0, 1.0, 0.0),
# )


def _coerce_float_matrix(matrix, expected_rows=None, expected_cols=None):
    if not isinstance(matrix, list):
        return None
    if expected_rows is not None and len(matrix) != expected_rows:
        return None
    coerced = []
    for row in matrix:
        if not isinstance(row, list):
            return None
        if expected_cols is not None and len(row) != expected_cols:
            return None
        try:
            coerced.append([float(v) for v in row])
        except (TypeError, ValueError):
            return None
    return coerced


def _load_distance_matrices(config, key_mode, mode_name, random_placement=False):
    weights_key = _resolve_weights_key(key_mode, mode_name)

    config = config or {}
    dd_config = config.get('distance_difficulty', {}) if isinstance(config, dict) else {}

    type_matrix = _coerce_float_matrix(dd_config.get('type_distance_matrix'), 3, 3)
    assert type_matrix is not None
    #    type_matrix = [list(row) for row in _DEFAULT_TYPE_DISTANCE_MATRIX]

    visual_matrices = dd_config.get('visual_distance_matrices')
    if not isinstance(visual_matrices, dict):
        visual_matrices = {}

    visual_matrix = visual_matrices.get(weights_key)
    if visual_matrix is None:
        visual_matrix = visual_matrices.get(weights_key.replace('weights_', ''), None)

    visual_matrix = _coerce_float_matrix(visual_matrix, int(key_mode), int(key_mode)) if visual_matrix is not None else None
    scratch_indices = _get_scratch_indices(key_mode, mode_name)
    assert visual_matrix is not None

    if random_placement:
        visual_matrix = _apply_random_placement_matrix(visual_matrix, scratch_indices)

    return type_matrix, visual_matrix


def _build_line_note_index(sorted_notes):
    """
    line_notes[col] = [{'idx': int, 'time': float, 'type': str}, ...] (시간/타입 순)
    idx_to_line_info[idx] = 동일 dict (timing_order 포함)
    line_times[col] = [time, ...] (bisect용)
    """
    line_notes = {}
    for idx, note in enumerate(sorted_notes):
        col = note.get('column', 1)
        line_notes.setdefault(col, []).append({
            'idx': idx,
            'time': note.get('time', 0.0),
            'type': note.get('type', 'note'),
        })

    idx_to_line_info = {}
    line_times = {}
    for col, notes_in_line in line_notes.items():
        line_times[col] = [n['time'] for n in notes_in_line]
        for timing_order, info in enumerate(notes_in_line):
            info['timing_order'] = timing_order
            idx_to_line_info[info['idx']] = info

    return line_notes, idx_to_line_info, line_times


def _compute_ln_tail_weights(sorted_notes, line_notes, idx_to_line_info, time_window_ms):
    """
    ln_end 노트가 참조될 때 적용할 가중치.
    - ln_tail_weight = clamp((tail_time - prev_note_time) / time_window_ms, 0.1, 1.0)  # ms 기반
    - 본인(i==j)에는 적용하지 않는 것을 전제로, 여기서는 값만 제공.
    """
    n = len(sorted_notes)
    weights = [1.0] * n

    time_window_ms = float(time_window_ms) if time_window_ms else 1000.0

    for idx, note in enumerate(sorted_notes):
        if note.get('type') != 'ln_end':
            continue
        info = idx_to_line_info.get(idx)
        if not info:
            continue

        col = note.get('column', 1)
        order = info.get('timing_order', 0)
        if order <= 0:
            continue

        prev_time = line_notes[col][order - 1]['time']
        ln_duration_ms = (note.get('time', 0.0) - prev_time) * 1000.0
        raw_weight = ln_duration_ms / time_window_ms
        weights[idx] = max(0.05, min(1.0, raw_weight))

    return weights


\


def _apply_random_placement_matrix(matrix, scratch_indices):
    if matrix is None:
        return None

    n = len(matrix)
    scratch_set = {i for i in (scratch_indices or []) if 0 <= i < n}
    non_scratch = [i for i in range(n) if i not in scratch_set]

    def _avg(values, default=0.0):
        return sum(values) / len(values) if values else default

    diag_non_scratch = [matrix[i][i] for i in non_scratch]
    diag_scratch = [matrix[i][i] for i in scratch_set if i < n]
    offdiag_non_scratch = [
        matrix[i][j]
        for i in non_scratch
        for j in non_scratch
        if i != j
    ]
    offdiag_scratch = [
        matrix[i][j]
        for i in range(n)
        for j in range(n)
        if i != j and (i in scratch_set or j in scratch_set)
    ]

    avg_diag_non = _avg(diag_non_scratch, 0.0)
    avg_diag_scratch = _avg(diag_scratch, avg_diag_non)
    avg_off_non = _avg(offdiag_non_scratch, avg_diag_non)
    avg_off_scratch = _avg(offdiag_scratch, avg_off_non)

    randomized = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j and i in scratch_set:
                row.append(avg_diag_scratch)
            elif i == j:
                row.append(avg_diag_non)
            elif i in scratch_set or j in scratch_set:
                row.append(avg_off_scratch)
            else:
                row.append(avg_off_non)
        randomized.append(row)

    return randomized


def _accumulate_ratio(numer, denom, timing_offset_sec, judgments, note_type, weight, kind):
    score_ratio, acc_ratio, gauge_ratio = _get_judgment_for_fds_rds_values(
        timing_offset_sec * 1000, judgments, note_type
    )
    if kind == 'score':
        ratio = score_ratio
    elif kind == 'gauge':
        ratio = gauge_ratio
    else:
        ratio = acc_ratio
    if ratio is None:
        return numer, denom
    return numer + ratio * weight, denom + weight


def _type_distance(type_a, type_b):
    idx_a = 0 if type_a == 'note' else (1 if type_a == 'ln_start' else 2)
    idx_b = 0 if type_b == 'note' else (1 if type_b == 'ln_start' else 2)
    return 0.0 if idx_a == idx_b else 1.0


def _calculate_nps_v2_and_distance(
    *,
    sorted_notes,
    key_mode,
    column_weights,
    time_window_ms,
    ln_tail_weights,
    type_distance_matrix,
    visual_distance_matrix,
    judgments=None,
    time_deltas=None,
    vibro_nerf_nps_condition=10.0,
    vibro_nps_nerf_weight=0.9,
    create_multiprocessing_workers=False,
):
    note_count = len(sorted_notes)
    if note_count == 0:
        return [], [], [], [], [], [], [], [], []

    time_window_ms = float(time_window_ms) if time_window_ms else 1000.0
    time_window_s = time_window_ms / 1000.0

    nps_values = [0.0] * note_count
    nps_v2_values = [0.0] * note_count
    distance_difficulty_values = [0.0] * note_count
    jack_nps_v2_values = [0.0] * note_count
    same_line_nps_v2_values = [0.0] * note_count
    minimum_distance_sum_values = [0.0] * note_count
    same_line_minimum_distance_sum_values = [0.0] * note_count
    jack_interval_values = [time_window_ms] * note_count
    jack_score_uniformity_values = [100.0] * note_count
    jack_acc_uniformity_values = [100.0] * note_count
    nps_v2_nerf_values = [0.0] * note_count
    window_start_indices = [0] * note_count
    window_finish_indices = [0] * note_count

    try:
        vibro_nerf_nps_condition = float(vibro_nerf_nps_condition)
    except (TypeError, ValueError):
        vibro_nerf_nps_condition = 10.0
    if vibro_nerf_nps_condition < 0:
        vibro_nerf_nps_condition = 0.0

    try:
        vibro_nps_nerf_weight = float(vibro_nps_nerf_weight)
    except (TypeError, ValueError):
        vibro_nps_nerf_weight = 0.9
    if vibro_nps_nerf_weight < 0:
        vibro_nps_nerf_weight = 0.0

    has_uniformity = bool(judgments) and isinstance(time_deltas, dict)

    def _delta_sec(key):
        if not isinstance(time_deltas, dict):
            return 0.0
        try:
            return float(time_deltas.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0

    td_score_plus_rice = _delta_sec('score_plus_rice')
    td_score_minus_rice = _delta_sec('score_minus_rice')
    td_score_plus_head = _delta_sec('score_plus_head')
    td_score_minus_head = _delta_sec('score_minus_head')
    td_acc_plus_rice = _delta_sec('acc_plus_rice')
    td_acc_minus_rice = _delta_sec('acc_minus_rice')
    td_acc_plus_head = _delta_sec('acc_plus_head')
    td_acc_minus_head = _delta_sec('acc_minus_head')

    window_start_index = 0
    window_finish_index = 0
    prev_note_time = None

    t_start = time.time()

    for i, note in enumerate(sorted_notes):
        t = note.get('time', 0.0)
        col_i = max(0, note.get('column', 1) - 1)
        same_col_note_list = []
        half_same_col_note_list = []
        nps = 0
        jack_nps_v2 = 0.0
        same_line_nps_v2 = 0.0
        jack_interval_sec = time_window_ms / 1000.0
        jack_score_uniformity = 100.0
        jack_acc_uniformity = 100.0
        half_jack_score_uniformity = 100.0
        half_jack_acc_uniformity = 100.0

        if prev_note_time is None or t != prev_note_time:
            while (
                window_start_index < window_finish_index
                and sorted_notes[window_start_index].get('time', 0.0) <= t - time_window_s
            ):
                window_start_index += 1

            while (
                window_finish_index < note_count
                and sorted_notes[window_finish_index].get('time', 0.0) < t + time_window_s
            ):
                window_finish_index += 1

            prev_note_time = t

        weighted_count = 0.0
        minimum_plus_delta_ms = time_window_ms
        minimum_minus_delta_ms = time_window_ms
        for j in range(window_start_index, window_finish_index):
            window_note = sorted_notes[j]
            dt_ms = (t - window_note.get('time', 0.0)) * 1000.0
            abs_dt_ms = abs(dt_ms)
            if -500 < dt_ms and dt_ms <= 500:
                nps += 1
            if abs_dt_ms >= time_window_ms:
                continue

            time_weight = 1.0 - (abs_dt_ms / time_window_ms)

            col_j = max(0, window_note.get('column', 1) - 1)
            col_weight = 1.0
            if column_weights is not None:
                try:
                    col_weight = column_weights[col_i][col_j]
                except (IndexError, TypeError):
                    col_weight = 1.0

            tail_weight = 1.0
            if j != i and window_note.get('type') == 'ln_end':
                tail_weight = ln_tail_weights[j]

            weighted_count += col_weight * tail_weight * time_weight
            if col_i == col_j:
                same_line_nps_v2 += col_weight * tail_weight * time_weight

            if col_i == col_j and window_note.get('type') != 'ln_end':
                same_col_note_list.append(j)
                if abs_dt_ms < time_window_ms * 0.5:
                    half_same_col_note_list.append(j)
                jack_nps_v2 += time_weight

            if dt_ms > 0:
                minimum_plus_delta_ms = min(minimum_plus_delta_ms, dt_ms)
            elif dt_ms < 0:
                minimum_minus_delta_ms = min(minimum_minus_delta_ms, abs_dt_ms)

        jack_size = len(same_col_note_list)
        half_jack_size = len(half_same_col_note_list)
        if jack_size >= 2:
            first_time = sorted_notes[same_col_note_list[0]].get('time', 0.0)
            last_time = sorted_notes[same_col_note_list[-1]].get('time', 0.0)
            if jack_size > 1:
                jack_interval_sec = (last_time - first_time) / (jack_size - 1)
            if jack_interval_sec < 0:
                jack_interval_sec = 0.0

            if has_uniformity:
                jack_score_sum = 0.0
                jack_acc_sum = 0.0

                for j, target_index in enumerate(same_col_note_list):
                    target_note = sorted_notes[target_index]
                    target_time = target_note.get('time', 0.0)
                    target_type = target_note.get('type', 'note')

                    if target_type == 'ln_start':
                        note_kind = 'head'
                        score_plus = td_score_plus_head
                        score_minus = td_score_minus_head
                        acc_plus = td_acc_plus_head
                        acc_minus = td_acc_minus_head
                    else:
                        note_kind = 'rice'
                        score_plus = td_score_plus_rice
                        score_minus = td_score_minus_rice
                        acc_plus = td_acc_plus_rice
                        acc_minus = td_acc_minus_rice

                    target_timing = first_time + (j * jack_interval_sec)

                    for offset in (0.0, score_plus, -score_minus):
                        offset_ms = abs((target_time - (target_timing + offset)) * 1000.0)
                        score_ratio, _ = get_judgment_result_typed(offset_ms, judgments, note_kind)
                        if score_ratio is not None:
                            jack_score_sum += score_ratio

                    for offset in (0.0, acc_plus, -acc_minus):
                        offset_ms = abs((target_time - (target_timing + offset)) * 1000.0)
                        _, acc_ratio = get_judgment_result_typed(offset_ms, judgments, note_kind)
                        if acc_ratio is not None:
                            jack_acc_sum += acc_ratio

                jack_score_uniformity = max((jack_score_sum / 6.0) - (jack_size * 50.0) + 100.0, 0.0)
                jack_acc_uniformity = max((jack_acc_sum / 6.0) - (jack_size * 50.0) + 100.0, 0.0)

                jack_score_uniformity = min(jack_score_uniformity, 100.0)
                jack_acc_uniformity = min(jack_acc_uniformity, 100.0)

        if has_uniformity and half_jack_size >= 3:
            half_first_time = sorted_notes[half_same_col_note_list[0]].get('time', 0.0)
            half_last_time = sorted_notes[half_same_col_note_list[-1]].get('time', 0.0)
            if half_jack_size > 1:
                half_jack_interval_sec = (half_last_time - half_first_time) / (half_jack_size - 1)
            else:
                half_jack_interval_sec = 0.0
            if half_jack_interval_sec < 0:
                half_jack_interval_sec = 0.0

            half_jack_score_sum = 0.0
            half_jack_acc_sum = 0.0

            for j, target_index in enumerate(half_same_col_note_list):
                target_note = sorted_notes[target_index]
                target_time = target_note.get('time', 0.0)
                target_type = target_note.get('type', 'note')

                if target_type == 'ln_start':
                    note_kind = 'head'
                    score_plus = td_score_plus_head
                    score_minus = td_score_minus_head
                    acc_plus = td_acc_plus_head
                    acc_minus = td_acc_minus_head
                else:
                    note_kind = 'rice'
                    score_plus = td_score_plus_rice
                    score_minus = td_score_minus_rice
                    acc_plus = td_acc_plus_rice
                    acc_minus = td_acc_minus_rice

                target_timing = half_first_time + (j * half_jack_interval_sec)

                for offset in (0.0, score_plus, -score_minus):
                    offset_ms = abs((target_time - (target_timing + offset)) * 1000.0)
                    score_ratio, _ = get_judgment_result_typed(offset_ms, judgments, note_kind)
                    if score_ratio is not None:
                        half_jack_score_sum += score_ratio

                for offset in (0.0, acc_plus, -acc_minus):
                    offset_ms = abs((target_time - (target_timing + offset)) * 1000.0)
                    _, acc_ratio = get_judgment_result_typed(offset_ms, judgments, note_kind)
                    if acc_ratio is not None:
                        half_jack_acc_sum += acc_ratio

            half_jack_score_uniformity = max(
                (half_jack_score_sum / 3.0) - (half_jack_size * 100.0) + 100.0, 0.0
            )
            half_jack_acc_uniformity = max(
                (half_jack_acc_sum / 3.0) - (half_jack_size * 100.0) + 100.0, 0.0
            )

            half_jack_score_uniformity = min(half_jack_score_uniformity, 100.0)
            half_jack_acc_uniformity = min(half_jack_acc_uniformity, 100.0)

            if jack_score_uniformity < half_jack_score_uniformity:
                jack_interval_sec = half_jack_interval_sec

        jack_score_uniformity = max(jack_score_uniformity, half_jack_score_uniformity)
        jack_acc_uniformity = max(jack_acc_uniformity, half_jack_acc_uniformity)

        nps_values[i] = nps
        jack_nps_v2_values[i] = jack_nps_v2
        jack_interval_values[i] = jack_interval_sec * 1000.0
        jack_score_uniformity_values[i] = jack_score_uniformity
        jack_acc_uniformity_values[i] = jack_acc_uniformity

        nps_v2_nerf = 0.0
        if has_uniformity and jack_nps_v2 > vibro_nerf_nps_condition and jack_nps_v2 > 0:
            uniformity_ratio = max(min(jack_score_uniformity, 100.0), 0.0) / 100.0
            nps_v2_nerf = ((jack_nps_v2 - vibro_nerf_nps_condition) / jack_nps_v2) * uniformity_ratio
            nps_v2_nerf = max(0.0, min(nps_v2_nerf, 1.0)) * vibro_nps_nerf_weight
            same_line_nps_v2_values[i] = same_line_nps_v2 * (1.0 - nps_v2_nerf)
            nps_v2_values[i] = weighted_count * (1.0 - nps_v2_nerf)
        else:
            same_line_nps_v2_values[i] = same_line_nps_v2
            nps_v2_values[i] = weighted_count
        nps_v2_nerf_values[i] = nps_v2_nerf
        window_start_indices[i] = window_start_index
        window_finish_indices[i] = window_finish_index

        minimum_delta_ms = max(min(minimum_plus_delta_ms, minimum_minus_delta_ms), 10.0)
        minimum_distance = 0.0
        note_type_i = note.get('type', 'note')

        for j in range(window_start_index, window_finish_index):
            if j == i:
                continue
            window_note = sorted_notes[j]
            dt_abs_ms = abs((t - window_note.get('time', 0.0)) * 1000.0)

            col_j = max(0, window_note.get('column', 1) - 1)
            visual_distance = 0.0
            try:
                visual_distance = visual_distance_matrix[col_i][col_j]
            except (IndexError, TypeError):
                visual_distance = 0.0

            type_distance = _type_distance(note_type_i, window_note.get('type', 'note'))
            if type_distance_matrix is not None:
                idx_a = 0 if note_type_i == 'note' else (1 if note_type_i == 'ln_start' else 2)
                type_j = window_note.get('type', 'note')
                idx_b = 0 if type_j == 'note' else (1 if type_j == 'ln_start' else 2)
                try:
                    type_distance = float(type_distance_matrix[idx_a][idx_b])
                except (IndexError, TypeError, ValueError):
                    type_distance = _type_distance(note_type_i, type_j)

            denom = minimum_delta_ms if minimum_delta_ms > 0 else dt_abs_ms
            timing_distance = min(dt_abs_ms / denom, 3.0) + (dt_abs_ms / time_window_ms)

            total_distance = visual_distance + type_distance + timing_distance
            minimum_distance = total_distance if minimum_distance == 0.0 else min(minimum_distance, total_distance)

        if minimum_distance < 1.0:
            minimum_distance = 1.0
        distance_difficulty_values[i] = minimum_distance


    print(f"[TIMER] NPS V2 First : {(time.time() - t_start):.2f} ")
    t_start = time.time()
    for i, note in enumerate(sorted_notes):
        window_start_index = window_start_indices[i]
        window_finish_index = window_finish_indices[i]
        nps_v2_nerf = nps_v2_nerf_values[i]
        minimum_distance_sum = 0.0
        same_line_minimum_distance_sum = 0.0
        t = note.get('time', 0.0)
        col_i = note.get('column', 1)

        for j in range(window_start_index, window_finish_index):
            window_note = sorted_notes[j]
            abs_dt_ms = abs((t - window_note.get('time', 0.0)) * 1000.0)
            time_weight = 1.0 - (abs_dt_ms / time_window_ms)

            tail_weight = 1.0
            if j != i and window_note.get('type') == 'ln_end':
                tail_weight = ln_tail_weights[j]

            weighted_distance = distance_difficulty_values[j] * tail_weight * time_weight
            minimum_distance_sum += weighted_distance

            if col_i == window_note.get('column', 1):
                same_line_minimum_distance_sum += weighted_distance

        minimum_distance_sum_values[i] = minimum_distance_sum * (1.0 - nps_v2_nerf)
        same_line_minimum_distance_sum_values[i] = same_line_minimum_distance_sum * (1.0 - nps_v2_nerf)

    print(f"[TIMER] NPS V2 Second : {(time.time() - t_start):.2f} ")
    return (
        nps_v2_values,
        distance_difficulty_values,
        jack_nps_v2_values,
        same_line_nps_v2_values,
        minimum_distance_sum_values,
        same_line_minimum_distance_sum_values,
        jack_interval_values,
        jack_score_uniformity_values,
        jack_acc_uniformity_values,
        nps_values,
    )


# ====================================================================
# 노트별 난이도 통합 계산 (Note Difficulty)
# ====================================================================

def _calculate_note_difficulty_improved(
    notes,
    duration,
    key_mode=7,
    preset_name='qwilight_bms_ez',
    mode_name=None,
    random_placement=False,
    target_mode=None,
    zero_poor_mode=False,
    config=None,
    create_multiprocessing_workers=False,
):

    target_type = _parse_target_option(target_mode)

    # 기본값 설정
    coefficients = {'j75': 1.0, 'j100': 1.0, 'j125': 0.9, 'j150': 0.1}
    ln_half_interval = True
    judgments = None
    column_weights = None
    time_window_ms = 1000
    type_time_delta = "C"

    fd_weight = 1.0
    rd_weight = 1.0
    lfd_weight = 1.0
    lrd_weight = 1.0
    distance_weight = 0.5
    vibro_nerf_nps_condition = 10.0
    vibro_nps_nerf_weight = 0.9
    vibro_j75_nerf_weight = 0.6
    vibro_j100_nerf_weight = 0.9
    vibro_j125_nerf_weight = 0.5
    vibro_j150_nerf_weight = 0.5

    if config:
        type_time_delta = str(config.get('type_time_delta', type_time_delta)).strip().upper() or "C"

        # weighted_nps 설정
        if 'weighted_nps' in config:
            time_window_ms = config['weighted_nps'].get('time_window_ms', 1000)
            weights_key = _resolve_weights_key(key_mode, mode_name)
            column_weights = config['weighted_nps'].get(weights_key, None)
            if random_placement and isinstance(column_weights, list):
                scratch_indices = _get_scratch_indices(key_mode, mode_name)
                column_weights = _apply_random_placement_matrix(column_weights, scratch_indices)

        # jack_difficulty 설정 + 가중치 설정
        if 'jack_difficulty' in config:
            jack_config = config['jack_difficulty']
            if 'coefficients' in jack_config:
                coefficients.update(jack_config['coefficients'])
            ln_half_interval = jack_config.get('ln_half_interval', True)
            fd_weight = jack_config.get('fd_weight', 1.0)
            rd_weight = jack_config.get('rd_weight', 1.0)
            lfd_weight = jack_config.get('lfd_weight', 1.0)
            lrd_weight = jack_config.get('lrd_weight', 1.0)
            distance_weight = jack_config.get('distance_weight', 0.5)
            vibro_nerf_nps_condition = jack_config.get(
                'vibro_nerf_nps_condition', vibro_nerf_nps_condition
            )
            vibro_nps_nerf_weight = jack_config.get('vibro_nps_nerf_weight', vibro_nps_nerf_weight)
            vibro_j75_nerf_weight = jack_config.get('vibro_j75_nerf_weight', vibro_j75_nerf_weight)
            vibro_j100_nerf_weight = jack_config.get('vibro_j100_nerf_weight', vibro_j100_nerf_weight)
            vibro_j125_nerf_weight = jack_config.get('vibro_j125_nerf_weight', vibro_j125_nerf_weight)
            vibro_j150_nerf_weight = jack_config.get('vibro_j150_nerf_weight', vibro_j150_nerf_weight)

    # 판정 프리셋 (보간 지원)
    if preset_name.startswith('osu_od_interpolate_'):
        od = float(preset_name.replace('osu_od_interpolate_', ''))
        judgments = interpolate_osu_judgments(od, config, use_lazer=False)
        print(f"[DEBUG] interpolate Stable OD={od}, judgments={'OK' if judgments else 'None'}")
    elif preset_name.startswith('osu_lazer_od_interpolate_'):
        od = float(preset_name.replace('osu_lazer_od_interpolate_', ''))
        judgments = interpolate_osu_judgments(od, config, use_lazer=True)
        print(f"[DEBUG] interpolate Lazer OD={od}, judgments={'OK' if judgments else 'None'}")
    elif 'judgment_presets' in config and preset_name in config['judgment_presets']:
        preset = config['judgment_presets'][preset_name]
        judgments = preset.get('judgments', None)
        print(f"[DEBUG] direct preset={preset_name}, judgments={'OK' if judgments else 'None'}")


    judgments = _apply_judgment_overrides(
        judgments,
        zero_poor_mode=zero_poor_mode,
        perfect_play=(target_type == 'perfect_play'),
    )

    def _as_float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    vibro_nerf_nps_condition = _as_float(vibro_nerf_nps_condition, 10.0)
    if vibro_nerf_nps_condition < 0:
        vibro_nerf_nps_condition = 0.0
    vibro_nps_nerf_weight = _as_float(vibro_nps_nerf_weight, 0.9)
    if vibro_nps_nerf_weight < 0:
        vibro_nps_nerf_weight = 0.0
    vibro_j75_nerf_weight = _as_float(vibro_j75_nerf_weight, 0.6)
    vibro_j100_nerf_weight = _as_float(vibro_j100_nerf_weight, 0.9)
    vibro_j125_nerf_weight = _as_float(vibro_j125_nerf_weight, 0.5)
    vibro_j150_nerf_weight = _as_float(vibro_j150_nerf_weight, 0.5)

    # time_delta 값 계산 (config type_time_delta 반영)
    time_deltas = calculate_time_deltas(judgments, type_time_delta=type_time_delta)

    def _delta_sec(key):
        try:
            return float(time_deltas.get(key, 0.0)) / 1000.0
        except (TypeError, ValueError):
            return 0.0

    time_deltas_sec = {
        'score_plus_rice': _delta_sec('time_delta_score_plus_rice'),
        'score_minus_rice': _delta_sec('time_delta_score_minus_rice'),
        'score_plus_head': _delta_sec('time_delta_score_plus_head'),
        'score_minus_head': _delta_sec('time_delta_score_minus_head'),
        'score_plus_tail': _delta_sec('time_delta_score_plus_tail'),
        'score_minus_tail': _delta_sec('time_delta_score_minus_tail'),
        'acc_plus_rice': _delta_sec('time_delta_acc_plus_rice'),
        'acc_minus_rice': _delta_sec('time_delta_acc_minus_rice'),
        'acc_plus_head': _delta_sec('time_delta_acc_plus_head'),
        'acc_minus_head': _delta_sec('time_delta_acc_minus_head'),
        'acc_plus_tail': _delta_sec('time_delta_acc_plus_tail'),
        'acc_minus_tail': _delta_sec('time_delta_acc_minus_tail'),
    }
    has_uniformity = bool(judgments)

    # 빈 노트 처리
    if not notes:
        return {
            'nps_v2': [],
            'distance_difficulty': [],
            'same_line_nps_v2': [],
            'minimum_distance_sum': [],
            'same_line_minimum_distance_sum': [],
            'j75': [], 'j100': [], 'j125': [], 'j150': [],
            'jack_nps_v2': [], 'jack_interval': [],
            'jack_score_uniformity': [], 'jack_acc_uniformity': [],
            'note_jack_diff_score': [], 'note_jack_diff_acc': [],
            'jack_diff_score': 0.0, 'jack_diff_acc': 0.0,
            'fds': [], 'fds_d': [], 'fda': [], 'fda_d': [],
            'rds': [], 'rds_d': [], 'rda': [], 'rda_d': [],
            'lfds': [], 'lfds_d': [], 'lfda': [], 'lfda_d': [],
            'lrds': [], 'lrds_d': [], 'lrda': [], 'lrda_d': [],
            'ldb': [],
            'ldbd': [],
            'vrs': [], 'vra': [],
            'avg_fds': 100.0, 'avg_fda': 100.0,
            'avg_rds': 100.0, 'avg_rda': 100.0,
            'avg_lfds': 100.0, 'avg_lfda': 100.0,
            'avg_lrds': 100.0, 'avg_lrda': 100.0,
            'avg_ldb': 0.0, 'avg_ldbd': 0.0, 'avg_distance_difficulty': 0.0,
            'fd_weight': fd_weight, 'rd_weight': rd_weight,
            'lfd_weight': lfd_weight, 'lrd_weight': lrd_weight,
            'distance_weight': distance_weight,
            'type_time_delta': type_time_delta,
            'time_deltas': time_deltas,
        }

    # 시간/타입 정렬
    sorted_notes = _sort_notes_for_difficulty(notes)
    note_count = len(sorted_notes)

    # 라인별 인덱스
    line_notes, idx_to_line_info, line_times = _build_line_note_index(sorted_notes)

    # ln_tail_weight (nps_v2에서 tail 참조에만 적용)
    ln_tail_weights = _compute_ln_tail_weights(sorted_notes, line_notes, idx_to_line_info, time_window_ms)

    # distance 행렬
    type_distance_matrix, visual_distance_matrix = _load_distance_matrices(
        config, key_mode, mode_name, random_placement=random_placement
    )


    prev_nps_v2 = time.time()

    # 1) NPS v2 + distance_difficulty (슬라이딩 윈도우)
    (
        nps_v2_values,
        distance_difficulty_values,
        jack_nps_v2_values,
        same_line_nps_v2_values,
        minimum_distance_sum_values,
        same_line_minimum_distance_sum_values,
        jack_interval_values,
        jack_score_uniformity_values,
        jack_acc_uniformity_values,
        nps_values,
    ) = _calculate_nps_v2_and_distance(
        sorted_notes=sorted_notes,
        key_mode=key_mode,
        column_weights=column_weights,
        time_window_ms=time_window_ms,
        ln_tail_weights=ln_tail_weights,
        type_distance_matrix=type_distance_matrix,
        visual_distance_matrix=visual_distance_matrix,
        judgments=judgments,
        time_deltas=time_deltas_sec,
        vibro_nerf_nps_condition=vibro_nerf_nps_condition,
        vibro_nps_nerf_weight=vibro_nps_nerf_weight,
        create_multiprocessing_workers=create_multiprocessing_workers,
    )
    print("nps_v2 소요시간 : " + str(time.time() - prev_nps_v2))
    # 2) 잭 + 3) fds/rds/lfds/lrds/ldb
    j75_values, j100_values, j125_values, j150_values = [], [], [], []
    note_jack_diff_score, note_jack_diff_acc = [], []
    vrs_values, vra_values = [], []

    fds_values, fds_d_values, fda_values, fda_d_values = [], [], [], []
    rds_values, rds_d_values, rda_values, rda_d_values = [], [], [], []
    lfds_values, lfds_d_values, lfda_values, lfda_d_values = [], [], [], []
    lrds_values, lrds_d_values, lrda_values, lrda_d_values = [], [], [], []
    ldb_values = []
    ldbd_values = []

    prev_offsets_by_idx = [None] * note_count
    prev_ln_length_by_idx = [0.0] * note_count
    prev_ln_space_by_idx = [0.0] * note_count
    fds_n_by_idx = [None] * note_count
    fds_d_by_idx = [None] * note_count
    fda_n_by_idx = [None] * note_count
    fda_d_by_idx = [None] * note_count
    rds_n_by_idx = [None] * note_count
    rds_d_by_idx = [None] * note_count
    rda_n_by_idx = [None] * note_count
    rda_d_by_idx = [None] * note_count

    # 잭 계산용 상태
    base_intervals = {'j75': 75, 'j100': 100, 'j125': 125, 'j150': 150}
    ln_base_intervals = {'j75': 37.5, 'j100': 50, 'j125': 62.5, 'j150': 75}
    scratch_columns = {idx + 1 for idx in _get_scratch_indices(key_mode, mode_name)}
    col_state = {}  # col -> {'last_time': float, 'last_type': str, 'accumulated': {...}}
    total_jack_score_loss = 0.0
    total_jack_acc_loss = 0.0

    # time_delta 값 추출 (sec)
    td_score_plus_rice = time_deltas_sec.get('score_plus_rice', 0.0)
    td_score_minus_rice = time_deltas_sec.get('score_minus_rice', 0.0)
    td_score_plus_head = time_deltas_sec.get('score_plus_head', 0.0)
    td_score_minus_head = time_deltas_sec.get('score_minus_head', 0.0)
    td_score_plus_tail = time_deltas_sec.get('score_plus_tail', 0.0)
    td_score_minus_tail = time_deltas_sec.get('score_minus_tail', 0.0)

    # time_delta 값 추출 (sec) - config `type_time_delta` 반영
    td_acc_plus_rice = time_deltas_sec.get('acc_plus_rice', 0.0)
    td_acc_minus_rice = time_deltas_sec.get('acc_minus_rice', 0.0)
    td_acc_plus_head = time_deltas_sec.get('acc_plus_head', 0.0)
    td_acc_minus_head = time_deltas_sec.get('acc_minus_head', 0.0)
    td_acc_plus_tail = time_deltas_sec.get('acc_plus_tail', 0.0)
    td_acc_minus_tail = time_deltas_sec.get('acc_minus_tail', 0.0)

    vibro_j_nerf_weights = {
        'j75': vibro_j75_nerf_weight,
        'j100': vibro_j100_nerf_weight,
        'j125': vibro_j125_nerf_weight,
        'j150': vibro_j150_nerf_weight,
    }

    def _apply_vibro_nerf(base_coef, uniformity_ratio, nerf_weight):
        nerf = base_coef * uniformity_ratio * nerf_weight
        return max(base_coef - nerf, 0.0)

    prev_note_calc_v2 = time.time()
    for i, current_note in enumerate(sorted_notes):
        t = current_note.get('time', 0.0)
        t_ms = t * 1000.0
        current_line = current_note.get('column', 1)
        current_type = current_note.get('type', 'note')
        col_i = max(0, current_line - 1)

        # ------------------------------------------------------------
        # 2. 잭 난이도 계산 (동시 계산 유지)
        # ------------------------------------------------------------
        if current_line not in col_state:
            col_state[current_line] = {
                'last_time': None,
                'last_type': None,
                'accumulated': {'j75': 0, 'j100': 0, 'j125': 0, 'j150': 0},
            }

        state = col_state[current_line]
        if state['last_time'] is None:
            j75_values.append(0)
            j100_values.append(0)
            j125_values.append(0)
            j150_values.append(0)
        else:
            actual_interval = t_ms - state['last_time']
            if ln_half_interval and state['last_type'] in ('ln_start', 'ln_end'):
                intervals_to_use = ln_base_intervals
            else:
                intervals_to_use = base_intervals

            interval_multiplier = 0.5 if current_line in scratch_columns else 1.0
            for j_name, base_interval in intervals_to_use.items():
                adjusted_interval = base_interval * interval_multiplier
                if actual_interval < adjusted_interval:
                    slip = adjusted_interval - actual_interval
                    state['accumulated'][j_name] += slip
                else:
                    recovery = actual_interval - adjusted_interval
                    state['accumulated'][j_name] = max(0, state['accumulated'][j_name] - recovery)

            j75_values.append(round(state['accumulated']['j75'], 9))
            j100_values.append(round(state['accumulated']['j100'], 9))
            j125_values.append(round(state['accumulated']['j125'], 9))
            j150_values.append(round(state['accumulated']['j150'], 9))

        state['last_time'] = t_ms
        state['last_type'] = current_type

        # 노트별 JDS/JDA 계산
        j_values = {
            'j75': j75_values[-1],
            'j100': j100_values[-1],
            'j125': j125_values[-1],
            'j150': j150_values[-1],
        }
        jack_score_uniformity = jack_score_uniformity_values[i] if i < len(jack_score_uniformity_values) else 100.0
        jack_acc_uniformity = jack_acc_uniformity_values[i] if i < len(jack_acc_uniformity_values) else 100.0
        score_uniformity_ratio = max(min(jack_score_uniformity, 100.0), 0.0) / 100.0
        acc_uniformity_ratio = max(min(jack_acc_uniformity, 100.0), 0.0) / 100.0
        current_jack_interval = jack_interval_values[i] if i < len(jack_interval_values) else time_window_ms
        if current_jack_interval <= 0:
            current_jack_interval = time_window_ms

        note_score_loss = 0.0
        note_acc_loss = 0.0

        if current_type == 'ln_start':
            jds_note_type = 'head'
        elif current_type == 'ln_end':
            jds_note_type = 'tail'
        else:
            jds_note_type = 'rice'

        for j_name, j_val in j_values.items():
            if j_val <= 0:
                continue
            base_coef = coefficients.get(j_name, 1.0)
            if has_uniformity:
                nerf_weight = vibro_j_nerf_weights.get(j_name, 0.0)
                score_coef = _apply_vibro_nerf(base_coef, score_uniformity_ratio, nerf_weight)
                acc_coef = _apply_vibro_nerf(base_coef, acc_uniformity_ratio, nerf_weight)
            else:
                score_coef = base_coef
                acc_coef = base_coef
            result = get_judgment_result_typed(j_val, judgments, jds_note_type)
            if result[0] is not None:
                score_loss = 100 - result[0]
                acc_loss = 100 - result[1]
                note_score_loss += score_coef * score_loss
                note_acc_loss += acc_coef * acc_loss
                total_jack_score_loss += score_coef * score_loss
                total_jack_acc_loss += acc_coef * acc_loss

        note_jack_diff_score.append(round(note_score_loss, 9))
        note_jack_diff_acc.append(round(note_acc_loss, 9))

        # ------------------------------------------------------------
        # 3. FDS/FDA/RDS/RDA/LFDS/LFDA/LRDS/LRDA/LDB/LDBD 계산 (개선안 반영)
        # ------------------------------------------------------------
        current_line_notes = line_notes.get(current_line, [])
        current_info = idx_to_line_info.get(i)
        current_order = current_info.get('timing_order') if current_info else None

        prev_note_info = None
        next_note_info = None
        if current_order is not None and 0 <= current_order < len(current_line_notes):
            if current_order > 0:
                prev_note_info = current_line_notes[current_order - 1]
            if current_order + 1 < len(current_line_notes):
                next_note_info = current_line_notes[current_order + 1]

        prev_offsets = [None] * (key_mode + 1)  # 1-indexed
        prev_ln_length = 0.0
        prev_ln_space = 0.0
        prev_head_t = None

        if prev_note_info is not None:
            prev_idx = prev_note_info['idx']
            if prev_offsets_by_idx[prev_idx] is not None:
                prev_offsets = list(prev_offsets_by_idx[prev_idx])
            prev_ln_length = prev_ln_length_by_idx[prev_idx]
            prev_ln_space = min(prev_ln_space_by_idx[prev_idx], 75 / 1000.0)

            if current_type == 'ln_end':
                prev_head_t = prev_note_info['time']
                prev_ln_length = t - prev_head_t
                if next_note_info is not None:
                    prev_ln_space = min(max(0.0, next_note_info['time'] - t), 75 / 1000.0)

        min_ln_length = 0.0
        min_ln_space = 0.0

        selected_press_time = t
        selected_release_time = t
        ldb = 0.0
        ldbd = 0.0

        current_weight = 1.0
        if column_weights is not None:
            try:
                current_weight = column_weights[col_i][col_i]
            except (IndexError, TypeError):
                current_weight = 1.0

        fds_n, fds_d = 3 * 100.0 * current_weight, 3 * current_weight
        fda_n, fda_d = 3 * 100.0 * current_weight, 3 * current_weight
        rds_n, rds_d = 3 * 100.0 * current_weight, 3 * current_weight
        rda_n, rda_d = 3 * 100.0 * current_weight, 3 * current_weight
        lfds_n, lfds_d = 3 * 100.0 * current_weight, 3 * current_weight
        lfda_n, lfda_d = 3 * 100.0 * current_weight, 3 * current_weight
        lrds_n, lrds_d = 3 * 100.0 * current_weight, 3 * current_weight
        lrda_n, lrda_d = 3 * 100.0 * current_weight, 3 * current_weight

        skip_fds_rds = current_type == 'ln_end'
        if skip_fds_rds and prev_note_info is not None:
            prev_idx = prev_note_info['idx']
            if fds_n_by_idx[prev_idx] is not None:
                fds_n = fds_n_by_idx[prev_idx]
                fds_d = fds_d_by_idx[prev_idx]
                fda_n = fda_n_by_idx[prev_idx]
                fda_d = fda_d_by_idx[prev_idx]
                rds_n = rds_n_by_idx[prev_idx]
                rds_d = rds_d_by_idx[prev_idx]
                rda_n = rda_n_by_idx[prev_idx]
                rda_d = rda_d_by_idx[prev_idx]

        vrs_n, vrs_d = 0.0, 0.0
        vra_n, vra_d = 0.0, 0.0

        for direction in ('left', 'right'):
            selected_press_time = t
            selected_release_time = t

            if direction == 'left':
                line_range = range(current_line - 1, 0, -1)
            else:
                line_range = range(current_line + 1, key_mode + 1)

            for selected_line in line_range:
                selected_line_notes = line_notes.get(selected_line)
                if not selected_line_notes:
                    continue

                times = line_times[selected_line]
                pos = bisect_left(times, t)

                selected_note_info = None
                selected_tail_info = None
                selected_head_info = None
                prev_selected_note_info = None

                if pos < len(selected_line_notes):
                    candidate = selected_line_notes[pos]
                    if candidate['type'] == 'ln_end':
                        selected_tail_info = candidate
                        if pos > 0:
                            selected_head_info = selected_line_notes[pos - 1]

                        if pos + 1 < len(selected_line_notes):
                            nxt = selected_line_notes[pos + 1]
                            if nxt['type'] != 'ln_end':
                                selected_note_info = nxt
                    else:
                        selected_note_info = candidate

                if pos > 0:
                    prev_candidate = selected_line_notes[pos - 1]
                    if prev_candidate['type'] == 'ln_end':
                        if pos - 2 >= 0:
                            prev_selected_note_info = selected_line_notes[pos - 2]
                    else:
                        prev_selected_note_info = prev_candidate

                if selected_note_info is None and selected_tail_info is None and prev_selected_note_info is None:
                    continue

                sel_col_i = selected_line - 1
                selected_weight = 1.0
                if column_weights is not None:
                    try:
                        selected_weight = column_weights[col_i][sel_col_i]
                    except (IndexError, TypeError):
                        selected_weight = 1.0

                closest_note_info = None
                candidate_next = selected_line_notes[pos] if pos < len(selected_line_notes) else None
                candidate_prev = selected_line_notes[pos - 1] if pos > 0 else None
                if candidate_next is not None and candidate_prev is not None:
                    if abs(candidate_next['time'] - t) < abs(t - candidate_prev['time']):
                        closest_note_info = candidate_next
                    else:
                        closest_note_info = candidate_prev
                else:
                    closest_note_info = candidate_next if candidate_next is not None else candidate_prev

                if closest_note_info is not None:
                    closest_idx = closest_note_info.get('idx')
                    if closest_idx is not None:
                        closest_jack_interval = (
                            jack_interval_values[closest_idx]
                            if closest_idx < len(jack_interval_values)
                            else time_window_ms
                        )
                        if closest_jack_interval <= 0:
                            closest_jack_interval = time_window_ms
                        closest_jack_score_uniformity = (
                            jack_score_uniformity_values[closest_idx]
                            if closest_idx < len(jack_score_uniformity_values)
                            else 100.0
                        )
                        closest_jack_acc_uniformity = (
                            jack_acc_uniformity_values[closest_idx]
                            if closest_idx < len(jack_acc_uniformity_values)
                            else 100.0
                        )

                        jack_interval_ratio_diff = (time_window_ms / current_jack_interval) - (
                            time_window_ms / closest_jack_interval
                        )
                        jack_interval_relation = max(1.0 - abs(jack_interval_ratio_diff), 0.0)
                        relation_score_rate = (
                            (jack_score_uniformity / 100.0)
                            * (closest_jack_score_uniformity / 100.0)
                            * jack_interval_relation
                        )
                        relation_acc_rate = (
                            (jack_acc_uniformity / 100.0)
                            * (closest_jack_acc_uniformity / 100.0)
                            * jack_interval_relation
                        )

                        relation_time_delta = abs(t - closest_note_info.get('time', 0.0)) * 1000.0
                        if time_window_ms > 0:
                            relation_time_weight = max(
                                (time_window_ms - relation_time_delta) / time_window_ms, 0.0
                            )
                        else:
                            relation_time_weight = 0.0

                        vrs_n += selected_weight * relation_score_rate * relation_time_weight
                        vrs_d += selected_weight * relation_time_weight
                        vra_n += selected_weight * relation_acc_rate * relation_time_weight
                        vra_d += selected_weight * relation_time_weight

                def _note_type_and_deltas(note_info):
                    if note_info is None:
                        return None, 0.0, 0.0, 0.0, 0.0
                    if note_info['type'] == 'ln_start':
                        return (
                            'head',
                            td_score_plus_head,
                            td_score_minus_head,
                            td_acc_plus_head,
                            td_acc_minus_head,
                        )
                    return (
                        'rice',
                        td_score_plus_rice,
                        td_score_minus_rice,
                        td_acc_plus_rice,
                        td_acc_minus_rice,
                    )

                (
                    sel_type,
                    sel_td_sp,
                    sel_td_sm,
                    sel_td_ap,
                    sel_td_am,
                ) = _note_type_and_deltas(selected_note_info)
                (
                    prev_type,
                    prev_td_sp,
                    prev_td_sm,
                    prev_td_ap,
                    prev_td_am,
                ) = _note_type_and_deltas(prev_selected_note_info)

                def _ratio_at(press_time, note_info, note_type_str, delta, kind):
                    if note_info is None or note_type_str is None:
                        return None
                    offset_sec = (press_time + delta) - note_info['time']
                    score_ratio, acc_ratio, _ = _get_judgment_for_fds_rds_values(
                        offset_sec * 1000, judgments, note_type_str
                    )
                    if kind == 'score':
                        return score_ratio
                    return acc_ratio

                def _select_ratio(selected_ratio, prev_ratio):
                    if selected_ratio is not None and prev_ratio is not None and prev_ratio > 0:
                        return max(selected_ratio, prev_ratio)
                    if selected_ratio is not None:
                        return selected_ratio
                    if prev_ratio is not None and prev_ratio > 0:
                        return prev_ratio
                    return None

                def _accumulate_pair(numer, denom, press_time, delta_sel, delta_prev, kind):
                    selected_ratio = _ratio_at(press_time, selected_note_info, sel_type, delta_sel, kind)
                    prev_ratio = _ratio_at(press_time, prev_selected_note_info, prev_type, delta_prev, kind)
                    ratio = _select_ratio(selected_ratio, prev_ratio)
                    if ratio is None:
                        return numer, denom
                    return numer + ratio * selected_weight, denom + selected_weight

                if not skip_fds_rds and (selected_note_info is not None or prev_selected_note_info is not None):
                    fds_n, fds_d = _accumulate_pair(fds_n, fds_d, selected_press_time, 0.0, 0.0, 'score')
                    fds_n, fds_d = _accumulate_pair(fds_n, fds_d, selected_press_time, sel_td_sp, prev_td_sp, 'score')
                    fds_n, fds_d = _accumulate_pair(fds_n, fds_d, selected_press_time, -sel_td_sm, -prev_td_sm, 'score')
                    fda_n, fda_d = _accumulate_pair(fda_n, fda_d, selected_press_time, 0.0, 0.0, 'acc')
                    fda_n, fda_d = _accumulate_pair(fda_n, fda_d, selected_press_time, sel_td_ap, prev_td_ap, 'acc')
                    fda_n, fda_d = _accumulate_pair(fda_n, fda_d, selected_press_time, -sel_td_am, -prev_td_am, 'acc')

                    if prev_offsets[selected_line] is not None:
                        ref_time = t + prev_offsets[selected_line]
                        rds_n, rds_d = _accumulate_pair(rds_n, rds_d, ref_time, 0.0, 0.0, 'score')
                        rds_n, rds_d = _accumulate_pair(rds_n, rds_d, ref_time, sel_td_sp, prev_td_sp, 'score')
                        rds_n, rds_d = _accumulate_pair(rds_n, rds_d, ref_time, -sel_td_sm, -prev_td_sm, 'score')
                        rda_n, rda_d = _accumulate_pair(rda_n, rda_d, ref_time, 0.0, 0.0, 'acc')
                        rda_n, rda_d = _accumulate_pair(rda_n, rda_d, ref_time, sel_td_ap, prev_td_ap, 'acc')
                        rda_n, rda_d = _accumulate_pair(rda_n, rda_d, ref_time, -sel_td_am, -prev_td_am, 'acc')

                if current_type != 'ln_end' and (selected_note_info is not None or prev_selected_note_info is not None):
                    selected_press_result = _ratio_at(t, selected_note_info, sel_type, sel_td_sp, 'score')
                    prev_press_result = _ratio_at(t, prev_selected_note_info, prev_type, -prev_td_sm, 'score')
                    st = selected_note_info['time'] if selected_note_info is not None else None
                    pst = prev_selected_note_info['time'] if prev_selected_note_info is not None else None

                    chosen_time = None
                    if selected_press_result is not None and prev_press_result is not None and prev_press_result > 0:
                        if st is not None and pst is not None:
                            if st - t < t - pst:
                                chosen_time = st
                            else:
                                chosen_time = pst
                        else:
                            chosen_time = st if st is not None else pst
                    elif selected_press_result is not None:
                        chosen_time = st
                    elif prev_press_result is not None and prev_press_result > 0:
                        chosen_time = pst

                    if chosen_time is None:
                        prev_offsets[selected_line] = None
                    else:
                        if not random_placement:
                            selected_press_time = chosen_time
                        prev_offsets[selected_line] = chosen_time - t

                # selected_tail 처리 (ln_end)
                if selected_tail_info is not None and selected_head_info is not None:
                    st = selected_tail_info['time']
                    pt = selected_head_info['time']
                    nt_time = selected_note_info['time'] if selected_note_info is not None else None

                    ln_distance = min(t - pt, st - t)
                    if ln_distance > 0:
                        ldb += selected_weight * min(ln_distance, 1.0)
                        ldbd += min(ln_distance, 1.0)

                    def _ratio_or_zero(timing_offset_sec, note_type_str, kind):
                        score_ratio, acc_ratio, _ = _get_judgment_for_fds_rds_values(
                            timing_offset_sec * 1000, judgments, note_type_str
                        )
                        if kind == 'score':
                            value = score_ratio
                        else:
                            value = acc_ratio
                        return 0.0 if value is None else float(value)

                    # ln_weight 계산 (개선안 수정사항.txt 반영: score/acc 별도)
                    ln_alpha_score = (
                        _ratio_or_zero(t - st, 'tail', 'score')
                        + _ratio_or_zero((t + td_score_plus_tail) - st, 'tail', 'score')
                        + _ratio_or_zero((t - td_score_minus_tail) - st, 'tail', 'score')
                    ) / 3.0
                    ln_beta_score = (
                        _ratio_or_zero(t - pt, 'head', 'score')
                        + _ratio_or_zero((t + td_score_plus_head) - pt, 'head', 'score')
                        + _ratio_or_zero((t - td_score_minus_head) - pt, 'head', 'score')
                    ) / 3.0

                    ln_alpha_acc = (
                        _ratio_or_zero(t - st, 'tail', 'acc')
                        + _ratio_or_zero((t + td_acc_plus_tail) - st, 'tail', 'acc')
                        + _ratio_or_zero((t - td_acc_minus_tail) - st, 'tail', 'acc')
                    ) / 3.0
                    ln_beta_acc = (
                        _ratio_or_zero(t - pt, 'head', 'acc')
                        + _ratio_or_zero((t + td_acc_plus_head) - pt, 'head', 'acc')
                        + _ratio_or_zero((t - td_acc_minus_head) - pt, 'head', 'acc')
                    ) / 3.0

                    ln_weight_score = (100.0 - max(ln_alpha_score, ln_beta_score)) / 100.0
                    ln_weight_acc = (100.0 - max(ln_alpha_acc, ln_beta_acc)) / 100.0

                    score_w = selected_weight * ln_weight_score
                    acc_w = selected_weight * ln_weight_acc

                    def _ratio_or_none(timing_offset_sec, note_type_str, kind):
                        score_ratio, acc_ratio, _ = _get_judgment_for_fds_rds_values(
                            timing_offset_sec * 1000, judgments, note_type_str
                        )
                        if kind == 'score':
                            return score_ratio
                        return acc_ratio

                    def _max_ratio(timing_offset_a, timing_offset_b, note_type_str, kind):
                        ratio_a = _ratio_or_none(timing_offset_a, note_type_str, kind)
                        ratio_b = _ratio_or_none(timing_offset_b, note_type_str, kind) if timing_offset_b is not None else None
                        if ratio_a is None:
                            return ratio_b
                        if ratio_b is None:
                            return ratio_a
                        return max(ratio_a, ratio_b)

                    if ln_weight_score > 0:
                        # LFDS: selected_release_time 기준
                        lfds_n, lfds_d = _accumulate_ratio(lfds_n, lfds_d, selected_release_time - st, judgments, 'tail', score_w, 'score')
                        lfds_n, lfds_d = _accumulate_ratio(lfds_n, lfds_d, (selected_release_time + td_score_plus_tail) - st, judgments, 'tail', score_w, 'score')
                        lfds_n, lfds_d = _accumulate_ratio(lfds_n, lfds_d, (selected_release_time - td_score_minus_tail) - st, judgments, 'tail', score_w, 'score')

                        # LRDS: pt+prev_ln_length 기준 (+ optional nt-prev_ln_space)
                        ref_time1 = pt + prev_ln_length
                        if nt_time is None:
                            lrds_n, lrds_d = _accumulate_ratio(lrds_n, lrds_d, ref_time1 - st, judgments, 'tail', score_w, 'score')
                            lrds_n, lrds_d = _accumulate_ratio(lrds_n, lrds_d, (ref_time1 + td_score_plus_tail) - st, judgments, 'tail', score_w, 'score')
                            lrds_n, lrds_d = _accumulate_ratio(lrds_n, lrds_d, (ref_time1 - td_score_minus_tail) - st, judgments, 'tail', score_w, 'score')
                        else:
                            ref_time2 = nt_time - prev_ln_space
                            for delta in (0.0, td_score_plus_tail, -td_score_minus_tail):
                                ratio = _max_ratio((ref_time1 + delta) - st, (ref_time2 + delta) - st, 'tail', 'score')
                                if ratio is not None:
                                    lrds_n += ratio * score_w
                                    lrds_d += score_w

                    if ln_weight_acc > 0:
                        # LFDA: selected_release_time 기준
                        lfda_n, lfda_d = _accumulate_ratio(lfda_n, lfda_d, selected_release_time - st, judgments, 'tail', acc_w, 'acc')
                        lfda_n, lfda_d = _accumulate_ratio(lfda_n, lfda_d, (selected_release_time + td_acc_plus_tail) - st, judgments, 'tail', acc_w, 'acc')
                        lfda_n, lfda_d = _accumulate_ratio(lfda_n, lfda_d, (selected_release_time - td_acc_minus_tail) - st, judgments, 'tail', acc_w, 'acc')

                        # LRDA: pt+prev_ln_length 기준 (+ optional nt-prev_ln_space)
                        ref_time1 = pt + prev_ln_length
                        if nt_time is None:
                            lrda_n, lrda_d = _accumulate_ratio(lrda_n, lrda_d, ref_time1 - st, judgments, 'tail', acc_w, 'acc')
                            lrda_n, lrda_d = _accumulate_ratio(lrda_n, lrda_d, (ref_time1 + td_acc_plus_tail) - st, judgments, 'tail', acc_w, 'acc')
                            lrda_n, lrda_d = _accumulate_ratio(lrda_n, lrda_d, (ref_time1 - td_acc_minus_tail) - st, judgments, 'tail', acc_w, 'acc')
                        else:
                            ref_time2 = nt_time - prev_ln_space
                            for delta in (0.0, td_acc_plus_tail, -td_acc_minus_tail):
                                ratio = _max_ratio((ref_time1 + delta) - st, (ref_time2 + delta) - st, 'tail', 'acc')
                                if ratio is not None:
                                    lrda_n += ratio * acc_w
                                    lrda_d += acc_w

                    # release_time 갱신 판단: t + score_plus 범위 기준
                    t_check_score, _ = get_judgment_for_fds_rds(((t + td_score_plus_tail) - st) * 1000, judgments, 'tail')
                    if t_check_score is not None and not random_placement:
                        selected_release_time = st

                    # min_ln_length / min_ln_space 업데이트
                    ln_len = st - pt
                    if ln_len > 0:
                        min_ln_length = ln_len if min_ln_length <= 0 else min(min_ln_length, ln_len)

                    if nt_time is not None:
                        ln_space = nt_time - st
                        if ln_space > 0:
                            min_ln_space = ln_space if min_ln_space <= 0 else min(min_ln_space, ln_space)

        # prev_offsets 저장 (다음 노트에서 참조)
        prev_offsets_by_idx[i] = prev_offsets

        if min_ln_length > 0:
            prev_ln_length = min_ln_length
        if min_ln_space > 0:
            prev_ln_space = min(min_ln_space, 75 / 1000.0)
        prev_ln_length_by_idx[i] = prev_ln_length
        prev_ln_space_by_idx[i] = prev_ln_space
        fds_n_by_idx[i] = fds_n
        fds_d_by_idx[i] = fds_d
        fda_n_by_idx[i] = fda_n
        fda_d_by_idx[i] = fda_d
        rds_n_by_idx[i] = rds_n
        rds_d_by_idx[i] = rds_d
        rda_n_by_idx[i] = rda_n
        rda_d_by_idx[i] = rda_d

        final_fds = (fds_n / fds_d) if fds_d > 0 else 100.0
        final_fda = (fda_n / fda_d) if fda_d > 0 else 100.0
        final_rds = (rds_n / rds_d) if rds_d > 0 else 100.0
        final_rda = (rda_n / rda_d) if rda_d > 0 else 100.0
        final_lfds = (lfds_n / lfds_d) if lfds_d > 0 else 100.0
        final_lfda = (lfda_n / lfda_d) if lfda_d > 0 else 100.0
        final_lrds = (lrds_n / lrds_d) if lrds_d > 0 else 100.0
        final_lrda = (lrda_n / lrda_d) if lrda_d > 0 else 100.0

        fds_values.append(round(final_fds, 9))
        fds_d_values.append(round(fds_d, 9))
        fda_values.append(round(final_fda, 9))
        fda_d_values.append(round(fda_d, 9))
        rds_values.append(round(final_rds, 9))
        rds_d_values.append(round(rds_d, 9))
        rda_values.append(round(final_rda, 9))
        rda_d_values.append(round(rda_d, 9))

        lfds_values.append(round(final_lfds, 9))
        lfds_d_values.append(round(lfds_d, 9))
        lfda_values.append(round(final_lfda, 9))
        lfda_d_values.append(round(lfda_d, 9))
        lrds_values.append(round(final_lrds, 9))
        lrds_d_values.append(round(lrds_d, 9))
        lrda_values.append(round(final_lrda, 9))
        lrda_d_values.append(round(lrda_d, 9))
        vrs = (vrs_n / vrs_d) if vrs_d > 0 else 1.0
        vra = (vra_n / vra_d) if vra_d > 0 else 1.0
        vrs_values.append(round(vrs, 9))
        vra_values.append(round(vra, 9))
        current_note['vrs'] = vrs
        current_note['vra'] = vra

        ldb_values.append(round(ldb, 9))
        ldbd_values.append(round(ldbd, 9))

    print("노트별 계산 소요시간 : "+str(time.time()- prev_note_calc_v2))
    
    return {
        # NPS v2
        'nps': nps_values,
        'nps_v2': nps_v2_values,
        'distance_difficulty': distance_difficulty_values,
        'same_line_nps_v2': same_line_nps_v2_values,
        'minimum_distance_sum': minimum_distance_sum_values,
        'same_line_minimum_distance_sum': same_line_minimum_distance_sum_values,
        # 'peak_nps_v2': round(peak_nps_v2, 9),
        # 'avg_nps_v2': round(avg_nps_v2, 9),

        # 잭 난이도
        'j75': j75_values,
        'j100': j100_values,
        'j125': j125_values,
        'j150': j150_values,
        'jack_nps_v2': jack_nps_v2_values,
        'jack_interval': jack_interval_values,
        'jack_score_uniformity': jack_score_uniformity_values,
        'jack_acc_uniformity': jack_acc_uniformity_values,
        'note_jack_diff_score': note_jack_diff_score,
        'note_jack_diff_acc': note_jack_diff_acc,
        # 'jack_diff_score': jack_diff_score,
        # 'jack_diff_acc': jack_diff_acc,

        # 유연성/반복성/롱노트/거리
        'fds': fds_values,
        'fds_d': fds_d_values,
        'fda': fda_values,
        'fda_d': fda_d_values,
        'rds': rds_values,
        'rds_d': rds_d_values,
        'rda': rda_values,
        'rda_d': rda_d_values,
        'lfds': lfds_values,
        'lfds_d': lfds_d_values,
        'lfda': lfda_values,
        'lfda_d': lfda_d_values,
        'lrds': lrds_values,
        'lrds_d': lrds_d_values,
        'lrda': lrda_values,
        'lrda_d': lrda_d_values,
        'ldb': ldb_values,
        'ldbd': ldbd_values,
        'vrs': vrs_values,
        'vra': vra_values,

        # 전체 평균
        # 'avg_fds': round(avg_fds, 9),
        # 'avg_fda': round(avg_fda, 9),
        # 'avg_rds': round(avg_rds, 9),
        # 'avg_rda': round(avg_rda, 9),
        # 'avg_lfds': round(avg_lfds, 9),
        # 'avg_lfda': round(avg_lfda, 9),
        # 'avg_lrds': round(avg_lrds, 9),
        # 'avg_lrda': round(avg_lrda, 9),
        # 'avg_ldb': round(avg_ldb, 9),
        # 'avg_ldbd': round(avg_ldbd, 9),
        # 'avg_distance_difficulty': round(avg_distance, 9),

        # 가중치
        'fd_weight': fd_weight,
        'rd_weight': rd_weight,
        'lfd_weight': lfd_weight,
        'lrd_weight': lrd_weight,
        'distance_weight': distance_weight,

        # time_delta (디버그용)
        'type_time_delta': type_time_delta,
        'time_deltas': time_deltas,
    }



def _parse_target_option(value):
    if value is None:
        return 'score_acc'
    text = str(value).strip().lower()
    if text in (
        'score % acc %',
        'score% acc%',
        'score % acc%',
        'score %acc%',
        'score acc',
        'score/acc',
        'acc/score',
        'auto',
    ):
        return 'score_acc'
    if text in ('full combo', 'fullcombo', 'fc'):
        return 'full_combo'
    if text in ('perfect play', 'perfectplay', 'pp'):
        return 'perfect_play'
    return 'score_acc'
# ====================================================================
# 전체 난이도 계산 (Total Difficulty)
# ====================================================================

def calculate_total_difficulty(
    notes,
    duration,
    key_mode=7,
    preset_name='qwilight_bms_ez',
    mode_name=None,
    random_placement=False,
    life_gauge='auto',
    sv_list=None,
    zero_poor_mode=False,
    config=None,
    create_multiprocessing_workers=False,
):
    """
    전체 난이도 계산 - calculate_note_difficulty를 사용하여 새 공식 적용
    
    Args:
        notes (list): 노트 리스트
        duration (float): 곡 길이 (초)
        key_mode (int): 키 개수
        preset_name (str): 판정 프리셋 이름
        config_path (str, optional): config.yaml 경로
    
    Returns:
        dict: {
            'note_score_diff': list,   # 각 노트별 점수 난이도 (SD)
            'note_acc_diff': list,     # 각 노트별 정확도 난이도 (AD)
            'score_diff_l5_sum': float, # 점수 난이도^5 합
            'score_diff_l5_avg': float, # L1 평균 기반 점수 난이도
            'acc_diff_l5_sum': float,   # 정확도 난이도^5 합
            'acc_diff_l5_avg': float,   # L1 평균 기반 정확도 난이도
            'note_diff': dict,          # calculate_note_difficulty 전체 결과
        }
    
    새 공식 (요약):
        same_line_distance_val = same_line_minimum_distance_sum
        ldbd_contrib = ldb_weight * ldbd
        other_line_distance_val = minimum_distance_sum - same_line_distance_val + ldbd_contrib
        other_line_nps = nps_v2 - same_line_nps_v2 + (ldb_weight * ldb)
        other_line_nerf_score = vrs * vibro_relation_nerf_weight
        other_line_nerf_acc = vra * vibro_relation_nerf_weight

        base_score = (((same_line_nps_v2 + (other_line_nps * (1 - other_line_nerf_score)))
                      * ((same_line_distance_val + (other_line_distance_val * (1 - other_line_nerf_score)))
                      ** distance_weight)) ** (1 / (1 + distance_weight))) * (1 + jds / 100)
        base_acc = (((same_line_nps_v2 + (other_line_nps * (1 - other_line_nerf_acc)))
                    * ((same_line_distance_val + (other_line_distance_val * (1 - other_line_nerf_acc)))
                    ** distance_weight)) ** (1 / (1 + distance_weight))) * (1 + jda / 100)

        sd = base_score * FD * RD * LFD * LRD * JUDGE
        ad = base_acc * FD * RD * LFD * LRD * JUDGE
    """
    judgments = None
    time_window_ms = 1000
    ldb_weight = 1.0
    vibro_relation_nerf_weight = 0.5
    target_type = _parse_target_option(life_gauge)

    if config:
        time_window_ms = config.get('weighted_nps', {}).get('time_window_ms', 1000)
        ldb_weight = config.get('ldb_weight', ldb_weight)
        jack_config = config.get('jack_difficulty', {})
        if isinstance(jack_config, dict):
            vibro_relation_nerf_weight = jack_config.get(
                'vibro_relation_nerf_weight', vibro_relation_nerf_weight
            )
        vibro_relation_nerf_weight = config.get('vibro_relation_nerf_weight', vibro_relation_nerf_weight)

        if preset_name.startswith('osu_od_interpolate_'):
            od = float(preset_name.replace('osu_od_interpolate_', ''))
            judgments = interpolate_osu_judgments(od, config, use_lazer=False)
        elif preset_name.startswith('osu_lazer_od_interpolate_'):
            od = float(preset_name.replace('osu_lazer_od_interpolate_', ''))
            judgments = interpolate_osu_judgments(od, config, use_lazer=True)
        elif 'judgment_presets' in config and preset_name in config['judgment_presets']:
            preset = config['judgment_presets'][preset_name]
            judgments = preset.get('judgments', None)

    judgments = _apply_judgment_overrides(
        judgments,
        zero_poor_mode=zero_poor_mode,
        perfect_play=(target_type == 'perfect_play'),
    )

    try:
        ldb_weight = float(ldb_weight)
    except (TypeError, ValueError):
        ldb_weight = 1.0
    try:
        vibro_relation_nerf_weight = float(vibro_relation_nerf_weight)
    except (TypeError, ValueError):
        vibro_relation_nerf_weight = 0.5
    if vibro_relation_nerf_weight < 0:
        vibro_relation_nerf_weight = 0.0
    # 통합 노트별 난이도 계산
    note_diff = _calculate_note_difficulty_improved(
        notes,
        duration,
        key_mode=key_mode,
        preset_name=preset_name,
        mode_name=mode_name,
        random_placement=random_placement,
        target_mode=target_type,
        zero_poor_mode=zero_poor_mode,
        config=config,
        create_multiprocessing_workers=create_multiprocessing_workers,
    )
    
    nps_v2_values = note_diff.get('nps_v2', [])
    same_line_nps_v2_values = note_diff.get('same_line_nps_v2', [])
    ldb_values = note_diff.get('ldb', [])
    ldbd_values = note_diff.get('ldbd', [])
    note_jack_score = note_diff.get('note_jack_diff_score', [])
    note_jack_acc = note_diff.get('note_jack_diff_acc', [])
    fds_values = note_diff.get('fds', [])
    fda_values = note_diff.get('fda', [])
    rds_values = note_diff.get('rds', [])
    rda_values = note_diff.get('rda', [])
    fd_weight = note_diff.get('fd_weight', 1.0)
    rd_weight = note_diff.get('rd_weight', 1.0)
    lfds_values = note_diff.get('lfds', [])
    lfda_values = note_diff.get('lfda', [])
    lrds_values = note_diff.get('lrds', [])
    lrda_values = note_diff.get('lrda', [])
    minimum_distance_sum_values = note_diff.get('minimum_distance_sum', [])
    same_line_minimum_distance_sum_values = note_diff.get('same_line_minimum_distance_sum', [])
    lfd_weight = note_diff.get('lfd_weight', 1.0)
    lrd_weight = note_diff.get('lrd_weight', 1.0)
    distance_weight = note_diff.get('distance_weight', 0.5)
    vrs_values = note_diff.get('vrs', [])
    vra_values = note_diff.get('vra', [])
    nps_values = note_diff.get('nps', [])

    sorted_notes = _sort_notes_for_difficulty(notes)
    note_types = [n.get('type', 'note') for n in sorted_notes]

    def _judge_difficulty_for_type(note_type_str):
        score_n = 0.0
        score_d = 0.0
        acc_n = 0.0
        acc_d = 0.0
        if not judgments:
            return 100.0, 100.0

        limit = int(time_window_ms) if time_window_ms else 0
        for i in range(limit):
            weight = 1.0 / (i + 1)
            for offset in (i, -i):
                score_ratio, acc_ratio, _ = _get_judgment_for_fds_rds_values(
                    offset, judgments, note_type_str
                )
                if score_ratio is not None:
                    score_n += score_ratio * weight
                    score_d += weight
                if acc_ratio is not None:
                    acc_n += acc_ratio * weight
                    acc_d += weight

        score_val = score_n / score_d if score_d > 0 else 100.0
        acc_val = acc_n / acc_d if acc_d > 0 else 100.0
        return score_val, acc_val

    judge_score_rice, judge_acc_rice = _judge_difficulty_for_type('rice')
    judge_score_head, judge_acc_head = _judge_difficulty_for_type('head')
    judge_score_tail, judge_acc_tail = _judge_difficulty_for_type('tail')

    def _judge_values_for_note(note_type_str):
        if note_type_str == 'ln_start':
            return judge_score_head, judge_acc_head
        if note_type_str == 'ln_end':
            return judge_score_tail, judge_acc_tail
        return judge_score_rice, judge_acc_rice

    sv_list_output = sv_list if isinstance(sv_list, list) else []
    if sv_list_output:
        print(f"[DEBUG] sv_list ({len(sv_list_output)}): {sv_list_output}")
    
    # 각 노트별 난이도 계산
    # sd = (nps_v2 + ldb) * (1 + (jds / 100)) * ((100 / fds) ^ fd_weight) * ((100 / rds) ^ rd_weight)
    note_score_diff = []
    note_acc_diff = []
    raw_score_l1_sum = 0.0
    raw_acc_l1_sum = 0.0
    raw_score_l5_sum = 0.0
    raw_acc_l5_sum = 0.0
    peak_nps = 0
    global_nps = 0
    
    for i, nps_val in enumerate(nps_v2_values):
        peak_nps = max(peak_nps, nps_values[i])

        ldb = ldb_values[i] if i < len(ldb_values) else 0
        ldbd = ldbd_values[i] if i < len(ldbd_values) else 0
        jack_score = note_jack_score[i] if i < len(note_jack_score) else 0
        jack_acc = note_jack_acc[i] if i < len(note_jack_acc) else 0
        fds = fds_values[i] if i < len(fds_values) else 100.0
        fda = fda_values[i] if i < len(fda_values) else 100.0
        rds = rds_values[i] if i < len(rds_values) else 100.0
        rda = rda_values[i] if i < len(rda_values) else 100.0
        lfds = lfds_values[i] if i < len(lfds_values) else 100.0
        lfda = lfda_values[i] if i < len(lfda_values) else 100.0
        lrds = lrds_values[i] if i < len(lrds_values) else 100.0
        lrda = lrda_values[i] if i < len(lrda_values) else 100.0
        minimum_distance_sum = (
            minimum_distance_sum_values[i] if i < len(minimum_distance_sum_values) else 0.0
        )
        same_line_minimum_distance_sum = (
            same_line_minimum_distance_sum_values[i]
            if i < len(same_line_minimum_distance_sum_values)
            else 0.0
        )
        same_line_nps_v2 = same_line_nps_v2_values[i] if i < len(same_line_nps_v2_values) else 0.0
        vrs = vrs_values[i] if i < len(vrs_values) else 1.0
        vra = vra_values[i] if i < len(vra_values) else 1.0
        note_type_str = note_types[i] if i < len(note_types) else 'note'

        # Division by zero 방지 (최소값 0.01)
        fds = max(fds, 0.01)
        fda = max(fda, 0.01)
        rds = max(rds, 0.01)
        rda = max(rda, 0.01)
        lfds = max(lfds, 0.01)
        lfda = max(lfda, 0.01)
        lrds = max(lrds, 0.01)
        lrda = max(lrda, 0.01)

        judge_score, judge_acc = _judge_values_for_note(note_type_str)
        judge_score = max(judge_score, 0.01)
        judge_acc = max(judge_acc, 0.01)

        # 새 공식 적용
        flex_read_mult_score = (((100.0 / fds) - 1)*fd_weight) + (((100.0 / lfds) - 1)*lfd_weight) + (((100.0 / rds) - 1)*rd_weight) + (((100.0 / lrds) - 1)*lrd_weight) + 1
        flex_read_mult_acc = (((100.0 / fda) - 1)*fd_weight) + (((100.0 / lfda) - 1)*lfd_weight) + (((100.0 / rda) - 1)*rd_weight) + (((100.0 / lrda) - 1)*lrd_weight) + 1

        ldb_contrib = ldb_weight * ldb
        ldbd_contrib = ldb_weight * ldbd
        same_line_nps_val = same_line_nps_v2
        other_line_nps_val = nps_val - same_line_nps_v2 + ldb_contrib
        other_line_nerf_score = min(max(vrs * vibro_relation_nerf_weight, 0.0), 1.0)
        other_line_nerf_acc = min(max(vra * vibro_relation_nerf_weight, 0.0), 1.0)

        same_line_distance_val = same_line_minimum_distance_sum
        other_line_distance_val = minimum_distance_sum - same_line_distance_val + ldbd_contrib

        base_score = (
            (
                (
                    same_line_nps_val
                    + (other_line_nps_val * (1.0 - other_line_nerf_score))
                )
                * (
                    (
                        same_line_distance_val
                        + (other_line_distance_val * (1.0 - other_line_nerf_score))
                    )
                    ** distance_weight
                )
            )
            ** (1 / (1 + distance_weight))
        ) * (1 + (jack_score / 100))
        base_acc = (
            (
                (
                    same_line_nps_val
                    + (other_line_nps_val * (1.0 - other_line_nerf_acc))
                )
                * (
                    (
                        same_line_distance_val
                        + (other_line_distance_val * (1.0 - other_line_nerf_acc))
                    )
                    ** distance_weight
                )
            )
            ** (1 / (1 + distance_weight))
        ) * (1 + (jack_acc / 100))

        judge_score_mult = 100.0 / judge_score
        judge_acc_mult = 100.0 / judge_acc

        score_diff = (
            base_score
            * flex_read_mult_score
            * judge_score_mult
        )
        acc_diff = (
            base_acc
            * flex_read_mult_acc
            * judge_acc_mult
        )

        note_score_diff.append(score_diff)
        note_acc_diff.append(acc_diff)
        raw_score_l1_sum += score_diff
        raw_acc_l1_sum += acc_diff
        raw_score_l5_sum += score_diff ** 5
        raw_acc_l5_sum += acc_diff ** 5
    

    # L5 합산: (Σ(diff^5))^0.2
    score_diff_l5_sum = raw_score_l5_sum ** 0.2 if raw_score_l5_sum > 0 else 0
    acc_diff_l5_sum = raw_acc_l5_sum ** 0.2 if raw_acc_l5_sum > 0 else 0
    
    # L1 평균 (노트수 기준)
    note_count = len(notes)
    if note_count > 0:
        global_nps = note_count / max(duration, 1)
        score_diff_l5_avg = raw_score_l1_sum / note_count
        acc_diff_l5_avg = raw_acc_l1_sum / note_count
    else:
        global_nps = 0
        score_diff_l5_avg = 0
        acc_diff_l5_avg = 0

    score_weight = 0.1
    acc_weight = 0.9
    rating_weight = 0.343
    rating_power = 0.5
    avg_rating_power = 1.0
    avg_lv_power = 1.0

    revive_score_weight = 0.1
    revive_acc_weight = 0.9
    revive_level_scale = 0.073
    revive_level_power = 0.81
    revive_max_level = 25

    if isinstance(config, dict):
        score_weight = config.get('score_weight', score_weight)
        acc_weight = config.get('acc_weight', acc_weight)
        rating_weight = config.get('rating_weight', rating_weight)
        rating_power = config.get('rating_power', rating_power)
        avg_rating_power = config.get('avg_rating_power', avg_rating_power)
        avg_lv_power = config.get('avg_lv_power', avg_lv_power)

        revive_score_weight = config.get('revive_score_weight', config.get('score_weight', revive_score_weight))
        revive_acc_weight = config.get('revive_acc_weight', config.get('acc_weight', revive_acc_weight))

        revive_level_scale = config.get(
            'revive_level_scale', config.get('level_scale', config.get('level_weight', revive_level_scale))
        )
        revive_level_power = config.get('revive_level_power', config.get('level_power', revive_level_power))
        revive_max_level = config.get('revive_max_level', revive_max_level)

    try:
        score_weight = float(score_weight)
    except (TypeError, ValueError):
        score_weight = 0.1
    try:
        acc_weight = float(acc_weight)
    except (TypeError, ValueError):
        acc_weight = 0.9
    try:
        rating_weight = float(rating_weight)
    except (TypeError, ValueError):
        rating_weight = 0.343
    try:
        rating_power = float(rating_power)
    except (TypeError, ValueError):
        rating_power = 0.5
    if rating_power <= 0:
        rating_power = 0.5
    try:
        avg_rating_power = float(avg_rating_power)
    except (TypeError, ValueError):
        avg_rating_power = 1.0
    if avg_rating_power <= 0:
        avg_rating_power = 1.0
    try:
        avg_lv_power = float(avg_lv_power)
    except (TypeError, ValueError):
        avg_lv_power = 1.0
    if avg_lv_power <= 0:
        avg_lv_power = 1.0

    if target_type not in ('full_combo', 'perfect_play'):
        score_avg_term = score_diff_l5_avg ** avg_rating_power if score_diff_l5_avg > 0 else 0.0
        acc_avg_term = acc_diff_l5_avg ** avg_rating_power if acc_diff_l5_avg > 0 else 0.0
        score_avg_lv_term = score_diff_l5_avg ** avg_lv_power if score_diff_l5_avg > 0 else 0.0
        acc_avg_lv_term = acc_diff_l5_avg ** avg_lv_power if acc_diff_l5_avg > 0 else 0.0
    else:
        score_avg_term = score_diff_l5_sum ** avg_rating_power if score_diff_l5_avg > 0 else 0.0
        acc_avg_term = acc_diff_l5_sum ** avg_rating_power if acc_diff_l5_avg > 0 else 0.0
        score_avg_lv_term = score_diff_l5_sum ** avg_lv_power if score_diff_l5_avg > 0 else 0.0
        acc_avg_lv_term = acc_diff_l5_sum ** avg_lv_power if acc_diff_l5_avg > 0 else 0.0

    rating_base = (
        (score_weight * score_diff_l5_sum * score_avg_term)
        + (acc_weight * acc_diff_l5_sum * acc_avg_term)
    )
    circus_rating = ((rating_weight * rating_base) ** rating_power) if rating_base > 0 and rating_weight > 0 else 0.0

    revive_difficulty = (
        (revive_score_weight * score_diff_l5_sum * score_avg_lv_term)
        + (revive_acc_weight * acc_diff_l5_sum * acc_avg_lv_term)
    )

    try:
        revive_level_scale = float(revive_level_scale)
    except (TypeError, ValueError):
        revive_level_scale = 0.073
    try:
        revive_level_power = float(revive_level_power)
    except (TypeError, ValueError):
        revive_level_power = 0.81
    if revive_level_power <= 0:
        revive_level_power = 0.81
    try:
        revive_max_level = float(revive_max_level)
    except (TypeError, ValueError):
        revive_max_level = 25

    if revive_difficulty > 0:
        revive_base = revive_level_scale * revive_difficulty
        revive_powered = (revive_base ** revive_level_power) if revive_base > 0 else 0.0
        if revive_max_level > 0:
            revive_lv = math.ceil(
                revive_max_level - ((revive_max_level**2) / (revive_powered + revive_max_level))
            )
        else:
            revive_lv = math.ceil(revive_powered)
    else:
        revive_lv = 0
    
    return {
        'global_nps': global_nps,
        'peak_nps': peak_nps,
        'target_type': target_type,
        'note_score_diff': note_score_diff,
        'note_acc_diff': note_acc_diff,
        'score_diff_l5_sum': round(score_diff_l5_sum, 9),
        'score_diff_l5_avg': round(score_diff_l5_avg, 9),
        'acc_diff_l5_sum': round(acc_diff_l5_sum, 9),
        'acc_diff_l5_avg': round(acc_diff_l5_avg, 9),
        'circus_rating': round(circus_rating, 9),
        'revive_difficulty': round(revive_difficulty, 9),
        'revive_lv': revive_lv,
        'judge_difficulty_score_rice': round(judge_score_rice, 9),
        'judge_difficulty_score_head': round(judge_score_head, 9),
        'judge_difficulty_score_tail': round(judge_score_tail, 9),
        'judge_difficulty_acc_rice': round(judge_acc_rice, 9),
        'judge_difficulty_acc_head': round(judge_acc_head, 9),
        'judge_difficulty_acc_tail': round(judge_acc_tail, 9),
        'sv_list': sv_list_output,
        'note_diff': note_diff,  # 전체 세부 결과 포함
        # 하위 호환성을 위해 기존 키도 유지
        'nps_v2': {
            'nps_v2': nps_v2_values,
            'peak_nps_v2': note_diff.get('peak_nps_v2', 0),
            'avg_nps_v2': note_diff.get('avg_nps_v2', 0),
        },
        'jack_diff': {
            'j75': note_diff.get('j75', []),
            'j100': note_diff.get('j100', []),
            'j125': note_diff.get('j125', []),
            'j150': note_diff.get('j150', []),
            'note_jack_diff_score': note_jack_score,
            'note_jack_diff_acc': note_jack_acc,
            'jack_diff_score': note_diff.get('jack_diff_score', 0),
            'jack_diff_acc': note_diff.get('jack_diff_acc', 0),
        },
    }

