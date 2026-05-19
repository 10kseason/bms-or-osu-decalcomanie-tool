"""
debug_osu_export.py - 디버그용 OSU 파일 생성

각 노트의 메트릭 값을 키음 이름으로 표시하여 오스 에디터에서 시각적으로 확인 가능
예: n12 (NPS=12), f24.50 (flex=24.50), j16 (jack=16)
"""

import os


def calculate_note_metrics(notes, nps_v2=None, jack_diff=None, total_diff=None, note_diff=None):
    """
    각 노트별 메트릭 계산
    
    Args:
        notes (list): 노트 리스트
        nps_v2 (dict): NPS v2 결과 (None이면 기존 NPS 사용)
        jack_diff (dict): Jack difficulty 결과
        total_diff (dict): Total difficulty 결과
        note_diff (dict): calculate_note_difficulty 결과 (새 지표 포함)
    
    Returns:
        list: 각 노트별 메트릭 딕셔너리 리스트
    """
    note_metrics = []
    
    # NPS v2 값 리스트 (있으면 사용)
    nps_v2_values = nps_v2.get('nps_v2', []) if nps_v2 else []
    
    # Jack difficulty 값 리스트
    j75_values = jack_diff.get('j75', []) if jack_diff else []
    j100_values = jack_diff.get('j100', []) if jack_diff else []
    j125_values = jack_diff.get('j125', []) if jack_diff else []
    j150_values = jack_diff.get('j150', []) if jack_diff else []
    # Jack difficulty 노트별 값 (글로벌 평균이 아닌 노트별 리스트)
    note_jack_diff_score = jack_diff.get('note_jack_diff_score', []) if jack_diff else []
    note_jack_diff_acc = jack_diff.get('note_jack_diff_acc', []) if jack_diff else []
    
    # Total difficulty 값 리스트
    score_diff_values = total_diff.get('note_score_diff', []) if total_diff else []
    acc_diff_values = total_diff.get('note_acc_diff', []) if total_diff else []
    
    # 새 지표 (note_diff에서 가져오거나 total_diff에서 추출)
    if note_diff:
        ldb_values = note_diff.get('ldb', [])
        ldbd_values = note_diff.get('ldbd', [])
        fds_values = note_diff.get('fds', [])
        fds_d_values = note_diff.get('fds_d', [])
        fda_values = note_diff.get('fda', [])
        fda_d_values = note_diff.get('fda_d', [])
        rds_values = note_diff.get('rds', [])
        rds_d_values = note_diff.get('rds_d', [])
        rda_values = note_diff.get('rda', [])
        rda_d_values = note_diff.get('rda_d', [])
        lfds_values = note_diff.get('lfds', [])
        lfds_d_values = note_diff.get('lfds_d', [])
        lfda_values = note_diff.get('lfda', [])
        lfda_d_values = note_diff.get('lfda_d', [])
        lrds_values = note_diff.get('lrds', [])
        lrds_d_values = note_diff.get('lrds_d', [])
        lrda_values = note_diff.get('lrda', [])
        lrda_d_values = note_diff.get('lrda_d', [])
        distance_difficulty_values = note_diff.get('distance_difficulty', [])
        minimum_distance_sum_values = note_diff.get('minimum_distance_sum', [])
        jack_nps_v2_values = note_diff.get('jack_nps_v2', [])
        jack_interval_values = note_diff.get('jack_interval', [])
        jack_score_uniformity_values = note_diff.get('jack_score_uniformity', [])
        jack_acc_uniformity_values = note_diff.get('jack_acc_uniformity', [])
        vrs_values = note_diff.get('vrs', [])
        vra_values = note_diff.get('vra', [])
    elif total_diff and 'note_diff' in total_diff:
        nd = total_diff['note_diff']
        ldb_values = nd.get('ldb', [])
        ldbd_values = nd.get('ldbd', [])
        fds_values = nd.get('fds', [])
        fds_d_values = nd.get('fds_d', [])
        fda_values = nd.get('fda', [])
        fda_d_values = nd.get('fda_d', [])
        rds_values = nd.get('rds', [])
        rds_d_values = nd.get('rds_d', [])
        rda_values = nd.get('rda', [])
        rda_d_values = nd.get('rda_d', [])
        lfds_values = nd.get('lfds', [])
        lfds_d_values = nd.get('lfds_d', [])
        lfda_values = nd.get('lfda', [])
        lfda_d_values = nd.get('lfda_d', [])
        lrds_values = nd.get('lrds', [])
        lrds_d_values = nd.get('lrds_d', [])
        lrda_values = nd.get('lrda', [])
        lrda_d_values = nd.get('lrda_d', [])
        distance_difficulty_values = nd.get('distance_difficulty', [])
        minimum_distance_sum_values = nd.get('minimum_distance_sum', [])
        jack_nps_v2_values = nd.get('jack_nps_v2', [])
        jack_interval_values = nd.get('jack_interval', [])
        jack_score_uniformity_values = nd.get('jack_score_uniformity', [])
        jack_acc_uniformity_values = nd.get('jack_acc_uniformity', [])
        vrs_values = nd.get('vrs', [])
        vra_values = nd.get('vra', [])
    else:
        ldb_values = []
        ldbd_values = []
        fds_values = []
        fds_d_values = []
        fda_values = []
        fda_d_values = []
        rds_values = []
        rds_d_values = []
        rda_values = []
        rda_d_values = []
        lfds_values = []
        lfds_d_values = []
        lfda_values = []
        lfda_d_values = []
        lrds_values = []
        lrds_d_values = []
        lrda_values = []
        lrda_d_values = []
        distance_difficulty_values = []
        minimum_distance_sum_values = []
        jack_nps_v2_values = []
        jack_interval_values = []
        jack_score_uniformity_values = []
        jack_acc_uniformity_values = []
        vrs_values = []
        vra_values = []
    
    for i, note in enumerate(notes):
        t = round(note['time'], 3)  # ms 단위로 반올림
        
        # Local NPS: NPS v2가 있으면 사용, 없으면 기존 계산
        if nps_v2_values and i < len(nps_v2_values):
            local_nps = round(nps_v2_values[i], 2)  # NPS v2 값 (가중치 적용)
        else:
            # 기존 방식: ±500ms 윈도우 내 노트 카운트
            window_start = t - 0.5
            window_end = t + 0.499999999999
            local_nps = sum(1 for n in notes if window_start <= n['time'] <= window_end)
        

        # 새 메트릭
        j75 = j75_values[i] if i < len(j75_values) else 0
        j100 = j100_values[i] if i < len(j100_values) else 0
        j125 = j125_values[i] if i < len(j125_values) else 0
        j150 = j150_values[i] if i < len(j150_values) else 0
        score_diff = score_diff_values[i] if i < len(score_diff_values) else 0
        acc_diff = acc_diff_values[i] if i < len(acc_diff_values) else 0
        jack_diff_score = note_jack_diff_score[i] if i < len(note_jack_diff_score) else 0
        jack_diff_acc = note_jack_diff_acc[i] if i < len(note_jack_diff_acc) else 0
        
        # 새 지표
        ldb = ldb_values[i] if i < len(ldb_values) else 0
        ldbd = ldbd_values[i] if i < len(ldbd_values) else 0
        fds = fds_values[i] if i < len(fds_values) else 100.0
        fds_d = fds_d_values[i] if i < len(fds_d_values) else 0
        fda = fda_values[i] if i < len(fda_values) else 100.0
        fda_d = fda_d_values[i] if i < len(fda_d_values) else 0
        rds = rds_values[i] if i < len(rds_values) else 100.0
        rds_d = rds_d_values[i] if i < len(rds_d_values) else 0
        rda = rda_values[i] if i < len(rda_values) else 100.0
        rda_d = rda_d_values[i] if i < len(rda_d_values) else 0
        lfds = lfds_values[i] if i < len(lfds_values) else 100.0
        lfds_d = lfds_d_values[i] if i < len(lfds_d_values) else 0
        lfda = lfda_values[i] if i < len(lfda_values) else 100.0
        lfda_d = lfda_d_values[i] if i < len(lfda_d_values) else 0
        lrds = lrds_values[i] if i < len(lrds_values) else 100.0
        lrds_d = lrds_d_values[i] if i < len(lrds_d_values) else 0
        lrda = lrda_values[i] if i < len(lrda_values) else 100.0
        lrda_d = lrda_d_values[i] if i < len(lrda_d_values) else 0
        distance_difficulty = distance_difficulty_values[i] if i < len(distance_difficulty_values) else 0
        minimum_distance_sum = minimum_distance_sum_values[i] if i < len(minimum_distance_sum_values) else 0
        jack_nps_v2 = jack_nps_v2_values[i] if i < len(jack_nps_v2_values) else 0
        jack_interval = jack_interval_values[i] if i < len(jack_interval_values) else 0
        jack_score_uniformity = (
            jack_score_uniformity_values[i] if i < len(jack_score_uniformity_values) else 100.0
        )
        jack_acc_uniformity = jack_acc_uniformity_values[i] if i < len(jack_acc_uniformity_values) else 100.0
        vrs = vrs_values[i] if i < len(vrs_values) else 1.0
        vra = vra_values[i] if i < len(vra_values) else 1.0
        
        note_metrics.append({
            'note': note,
            'local_nps': local_nps,
            'nps_v2': nps_v2_values[i] if i < len(nps_v2_values) else local_nps,
            'j75': j75,
            'j100': j100,
            'j125': j125,
            'j150': j150,
            'score_diff': score_diff,
            'acc_diff': acc_diff,
            'jack_diff_score': jack_diff_score,
            'jack_diff_acc': jack_diff_acc,
            # 새 지표
            'ldb': ldb,
            'ldbd': ldbd,
            'fds': fds,
            'fds_d': fds_d,
            'fda': fda,
            'fda_d': fda_d,
            'rds': rds,
            'rds_d': rds_d,
            'rda': rda,
            'rda_d': rda_d,
            'lfds': lfds,
            'lfds_d': lfds_d,
            'lfda': lfda,
            'lfda_d': lfda_d,
            'lrds': lrds,
            'lrds_d': lrds_d,
            'lrda': lrda,
            'lrda_d': lrda_d,
            'distance_difficulty': distance_difficulty,
            'minimum_distance_sum': minimum_distance_sum,
            'jack_nps_v2': jack_nps_v2,
            'jack_interval': jack_interval,
            'jack_score_uniformity': jack_score_uniformity,
            'jack_acc_uniformity': jack_acc_uniformity,
            'vrs': vrs,
            'vra': vra,
        })
    
    return note_metrics


def format_hitsound_name(metric_dict, mode='local_nps', note_type='note'):
    """
    메트릭 값을 키음 이름 형식으로 변환
    
    Args:
        metric_dict (dict): 노트 메트릭
        mode (str): 표시할 메트릭 종류
        note_type (str): 노트 타입 ('note', 'ln_start', 'ln_end')
    
    Returns:
        str: 키음 파일명 (예: "n12.wav", "Hn12.wav" (LN 머리), "Tn12.wav" (LN 꼬리))
    """
    # 롱노트 머리/꼬리 접두어
    # H = Head (머리, ln_start)
    # T = Tail (꼬리, ln_end)
    prefix = ''
    if note_type == 'ln_start':
        prefix = 'H'  # Head (머리)
    elif note_type == 'ln_end':
        prefix = 'T'  # Tail (꼬리)
    
    if mode == 'local_nps':
        value = metric_dict['local_nps']
        return f"{prefix}n{value:.2f}.wav"
    elif mode == 'jack':
        value = metric_dict['jack']
        formatted = f"{value:.2f}"
        return f"{prefix}j{formatted}.wav"
    elif mode == 'chord':
        value = metric_dict['chord']
        return f"{prefix}c{value:.2f}.wav"
    elif mode == 'hand':
        value = metric_dict['hand']
        formatted = f"{value:.2f}"
        return f"{prefix}h{formatted}.wav"
    elif mode == 'nps_v2':
        value = metric_dict.get('nps_v2', metric_dict['local_nps'])
        return f"{prefix}v{value:.2f}.wav"
    elif mode == 'j75':
        value = metric_dict.get('j75', 0)
        return f"{prefix}j75_{value:.2f}.wav"
    elif mode == 'j100':
        value = metric_dict.get('j100', 0)
        return f"{prefix}j100_{value:.2f}.wav"
    elif mode == 'j125':
        value = metric_dict.get('j125', 0)
        return f"{prefix}j125_{value:.2f}.wav"
    elif mode == 'j150':
        value = metric_dict.get('j150', 0)
        return f"{prefix}j150_{value:.2f}.wav"
    elif mode == 'jack_nps_v2':
        value = metric_dict.get('jack_nps_v2', 0)
        return f"{prefix}jn{value:.2f}.wav"
    elif mode == 'jack_interval':
        value = metric_dict.get('jack_interval', 0)
        return f"{prefix}ji{value:.2f}.wav"
    elif mode == 'jack_score_uniformity':
        value = metric_dict.get('jack_score_uniformity', 0)
        return f"{prefix}jsu{value:.2f}.wav"
    elif mode == 'jack_acc_uniformity':
        value = metric_dict.get('jack_acc_uniformity', 0)
        return f"{prefix}jau{value:.2f}.wav"
    elif mode == 'score_diff':
        value = metric_dict.get('score_diff', 0)
        return f"{prefix}sd{value:.2f}.wav"
    elif mode == 'acc_diff':
        value = metric_dict.get('acc_diff', 0)
        return f"{prefix}ad{value:.2f}.wav"
    elif mode == 'jack_diff_score':
        value = metric_dict.get('jack_diff_score', 0)
        return f"{prefix}jds{value:.2f}.wav"
    elif mode == 'jack_diff_acc':
        value = metric_dict.get('jack_diff_acc', 0)
        return f"{prefix}jda{value:.2f}.wav"
    elif mode == 'ldb':
        value = metric_dict.get('ldb', 0)
        return f"{prefix}ldb{value:.2f}.wav"
    elif mode == 'ldbd':
        value = metric_dict.get('ldbd', 0)
        return f"{prefix}ldbd{value:.2f}.wav"
    elif mode == 'fds':
        value = metric_dict.get('fds', 100)
        return f"{prefix}fds{value:.2f}.wav"
    elif mode == 'fds_d':
        value = metric_dict.get('fds_d', 0)
        return f"{prefix}fds_d{value:.2f}.wav"
    elif mode == 'fda':
        value = metric_dict.get('fda', 100)
        return f"{prefix}fda{value:.2f}.wav"
    elif mode == 'fda_d':
        value = metric_dict.get('fda_d', 0)
        return f"{prefix}fda_d{value:.2f}.wav"
    elif mode == 'rds':
        value = metric_dict.get('rds', 100)
        return f"{prefix}rds{value:.2f}.wav"
    elif mode == 'rds_d':
        value = metric_dict.get('rds_d', 0)
        return f"{prefix}rds_d{value:.2f}.wav"
    elif mode == 'rda':
        value = metric_dict.get('rda', 100)
        return f"{prefix}rda{value:.2f}.wav"
    elif mode == 'rda_d':
        value = metric_dict.get('rda_d', 0)
        return f"{prefix}rda_d{value:.2f}.wav"
    elif mode == 'lfds':
        value = metric_dict.get('lfds', 100)
        return f"{prefix}lfds{value:.2f}.wav"
    elif mode == 'lfds_d':
        value = metric_dict.get('lfds_d', 0)
        return f"{prefix}lfds_d{value:.2f}.wav"
    elif mode == 'lfda':
        value = metric_dict.get('lfda', 100)
        return f"{prefix}lfda{value:.2f}.wav"
    elif mode == 'lfda_d':
        value = metric_dict.get('lfda_d', 0)
        return f"{prefix}lfda_d{value:.2f}.wav"
    elif mode == 'lrds':
        value = metric_dict.get('lrds', 100)
        return f"{prefix}lrds{value:.2f}.wav"
    elif mode == 'lrds_d':
        value = metric_dict.get('lrds_d', 0)
        return f"{prefix}lrds_d{value:.2f}.wav"
    elif mode == 'lrda':
        value = metric_dict.get('lrda', 100)
        return f"{prefix}lrda{value:.2f}.wav"
    elif mode == 'lrda_d':
        value = metric_dict.get('lrda_d', 0)
        return f"{prefix}lrda_d{value:.2f}.wav"
    elif mode == 'distance_difficulty':
        value = metric_dict.get('distance_difficulty', 0)
        return f"{prefix}dist{value:.2f}.wav"
    elif mode == 'minimum_distance_sum':
        value = metric_dict.get('minimum_distance_sum', 0)
        return f"{prefix}mdsum{value:.2f}.wav"
    elif mode == 'vrs':
        value = metric_dict.get('vrs', 1.0)
        return f"{prefix}vrs{value:.2f}.wav"
    elif mode == 'vra':
        value = metric_dict.get('vra', 1.0)
        return f"{prefix}vra{value:.2f}.wav"
    else:
        return "normal-hitnormal.wav"


def format_ln_hitsound_name(head_metric, tail_metric, mode='local_nps'):
    """
    롱노트용 키음 이름 생성 - 머리(H)와 꼬리(T) 메트릭 모두 표시
    
    Args:
        head_metric (dict): 롱노트 머리(ln_start) 메트릭
        tail_metric (dict): 롱노트 꼬리(ln_end) 메트릭
        mode (str): 표시할 메트릭 종류
    
    Returns:
        str: 키음 파일명 (예: "Hn12_Tn15.wav" - 머리 NPS=12, 꼬리 NPS=15)
    """
    if mode == 'local_nps':
        h_val = head_metric['local_nps']
        t_val = tail_metric['local_nps']
        return f"Hn{h_val:.2f}_Tn{t_val:.2f}.wav"
    elif mode == 'jack':
        h_val = head_metric['jack']
        t_val = tail_metric['jack']
        h_fmt = f"{h_val:.2f}"
        t_fmt = f"{t_val:.2f}"
        return f"Hj{h_fmt}_Tj{t_fmt}.wav"
    elif mode == 'chord':
        h_val = head_metric['chord']
        t_val = tail_metric['chord']
        return f"Hc{h_val:.2f}_Tc{t_val:.2f}.wav"
    elif mode == 'hand':
        h_val = head_metric['hand']
        t_val = tail_metric['hand']
        h_fmt = f"{h_val:.2f}"
        t_fmt = f"{t_val:.2f}"
        return f"Hh{h_fmt}_Th{t_fmt}.wav"
    elif mode == 'nps_v2':
        h_val = head_metric.get('nps_v2', head_metric['local_nps'])
        t_val = tail_metric.get('nps_v2', tail_metric['local_nps'])
        return f"Hv{h_val:.2f}_Tv{t_val:.2f}.wav"
    elif mode in ('j75', 'j100', 'j125', 'j150'):
        h_val = head_metric.get(mode, 0)
        t_val = tail_metric.get(mode, 0)
        return f"H{mode}_{h_val:.2f}_T{mode}_{t_val:.2f}.wav"
    elif mode == 'jack_nps_v2':
        h_val = head_metric.get('jack_nps_v2', 0)
        t_val = tail_metric.get('jack_nps_v2', 0)
        return f"Hjn{h_val:.2f}_Tjn{t_val:.2f}.wav"
    elif mode == 'jack_interval':
        h_val = head_metric.get('jack_interval', 0)
        t_val = tail_metric.get('jack_interval', 0)
        return f"Hji{h_val:.2f}_Tji{t_val:.2f}.wav"
    elif mode == 'jack_score_uniformity':
        h_val = head_metric.get('jack_score_uniformity', 0)
        t_val = tail_metric.get('jack_score_uniformity', 0)
        return f"Hjsu{h_val:.2f}_Tjsu{t_val:.2f}.wav"
    elif mode == 'jack_acc_uniformity':
        h_val = head_metric.get('jack_acc_uniformity', 0)
        t_val = tail_metric.get('jack_acc_uniformity', 0)
        return f"Hjau{h_val:.2f}_Tjau{t_val:.2f}.wav"
    elif mode == 'score_diff':
        h_val = head_metric.get('score_diff', 0)
        t_val = tail_metric.get('score_diff', 0)
        return f"Hsd{h_val:.2f}_Tsd{t_val:.2f}.wav"
    elif mode == 'acc_diff':
        h_val = head_metric.get('acc_diff', 0)
        t_val = tail_metric.get('acc_diff', 0)
        return f"Had{h_val:.2f}_Tad{t_val:.2f}.wav"
    elif mode == 'jack_diff_score':
        h_val = head_metric.get('jack_diff_score', 0)
        t_val = tail_metric.get('jack_diff_score', 0)
        return f"Hjds{h_val:.2f}_Tjds{t_val:.2f}.wav"
    elif mode == 'jack_diff_acc':
        h_val = head_metric.get('jack_diff_acc', 0)
        t_val = tail_metric.get('jack_diff_acc', 0)
        return f"Hjda{h_val:.2f}_Tjda{t_val:.2f}.wav"
    elif mode == 'ldb':
        h_val = head_metric.get('ldb', 0)
        t_val = tail_metric.get('ldb', 0)
        return f"Hldb{h_val:.2f}_Tldb{t_val:.2f}.wav"
    elif mode == 'ldbd':
        h_val = head_metric.get('ldbd', 0)
        t_val = tail_metric.get('ldbd', 0)
        return f"Hldbd{h_val:.2f}_Tldbd{t_val:.2f}.wav"
    elif mode == 'fds':
        h_val = head_metric.get('fds', 100)
        t_val = tail_metric.get('fds', 100)
        return f"Hfds{h_val:.2f}_Tfds{t_val:.2f}.wav"
    elif mode == 'fds_d':
        h_val = head_metric.get('fds_d', 0)
        t_val = tail_metric.get('fds_d', 0)
        return f"Hfds_d{h_val:.2f}_Tfds_d{t_val:.2f}.wav"
    elif mode == 'fda':
        h_val = head_metric.get('fda', 100)
        t_val = tail_metric.get('fda', 100)
        return f"Hfda{h_val:.2f}_Tfda{t_val:.2f}.wav"
    elif mode == 'fda_d':
        h_val = head_metric.get('fda_d', 0)
        t_val = tail_metric.get('fda_d', 0)
        return f"Hfda_d{h_val:.2f}_Tfda_d{t_val:.2f}.wav"
    elif mode == 'rds':
        h_val = head_metric.get('rds', 100)
        t_val = tail_metric.get('rds', 100)
        return f"Hrds{h_val:.2f}_Trds{t_val:.2f}.wav"
    elif mode == 'rds_d':
        h_val = head_metric.get('rds_d', 0)
        t_val = tail_metric.get('rds_d', 0)
        return f"Hrds_d{h_val:.2f}_Trds_d{t_val:.2f}.wav"
    elif mode == 'rda':
        h_val = head_metric.get('rda', 100)
        t_val = tail_metric.get('rda', 100)
        return f"Hrda{h_val:.2f}_Trda{t_val:.2f}.wav"
    elif mode == 'rda_d':
        h_val = head_metric.get('rda_d', 0)
        t_val = tail_metric.get('rda_d', 0)
        return f"Hrda_d{h_val:.2f}_Trda_d{t_val:.2f}.wav"
    elif mode == 'lfds':
        h_val = head_metric.get('lfds', 100)
        t_val = tail_metric.get('lfds', 100)
        return f"Hlfds{h_val:.2f}_Tlfds{t_val:.2f}.wav"
    elif mode == 'lfds_d':
        h_val = head_metric.get('lfds_d', 0)
        t_val = tail_metric.get('lfds_d', 0)
        return f"Hlfds_d{h_val:.2f}_Tlfds_d{t_val:.2f}.wav"
    elif mode == 'lfda':
        h_val = head_metric.get('lfda', 100)
        t_val = tail_metric.get('lfda', 100)
        return f"Hlfda{h_val:.2f}_Tlfda{t_val:.2f}.wav"
    elif mode == 'lfda_d':
        h_val = head_metric.get('lfda_d', 0)
        t_val = tail_metric.get('lfda_d', 0)
        return f"Hlfda_d{h_val:.2f}_Tlfda_d{t_val:.2f}.wav"
    elif mode == 'lrds':
        h_val = head_metric.get('lrds', 100)
        t_val = tail_metric.get('lrds', 100)
        return f"Hlrds{h_val:.2f}_Tlrds{t_val:.2f}.wav"
    elif mode == 'lrds_d':
        h_val = head_metric.get('lrds_d', 0)
        t_val = tail_metric.get('lrds_d', 0)
        return f"Hlrds_d{h_val:.2f}_Tlrds_d{t_val:.2f}.wav"
    elif mode == 'lrda':
        h_val = head_metric.get('lrda', 100)
        t_val = tail_metric.get('lrda', 100)
        return f"Hlrda{h_val:.2f}_Tlrda{t_val:.2f}.wav"
    elif mode == 'lrda_d':
        h_val = head_metric.get('lrda_d', 0)
        t_val = tail_metric.get('lrda_d', 0)
        return f"Hlrda_d{h_val:.2f}_Tlrda_d{t_val:.2f}.wav"
    elif mode == 'distance_difficulty':
        h_val = head_metric.get('distance_difficulty', 0)
        t_val = tail_metric.get('distance_difficulty', 0)
        return f"Hdist{h_val:.2f}_Tdist{t_val:.2f}.wav"
    elif mode == 'minimum_distance_sum':
        h_val = head_metric.get('minimum_distance_sum', 0)
        t_val = tail_metric.get('minimum_distance_sum', 0)
        return f"Hmdsum{h_val:.2f}_Tmdsum{t_val:.2f}.wav"
    elif mode == 'vrs':
        h_val = head_metric.get('vrs', 1.0)
        t_val = tail_metric.get('vrs', 1.0)
        return f"Hvrs{h_val:.2f}_Tvrs{t_val:.2f}.wav"
    elif mode == 'vra':
        h_val = head_metric.get('vra', 1.0)
        t_val = tail_metric.get('vra', 1.0)
        return f"Hvra{h_val:.2f}_Tvra{t_val:.2f}.wav"
    elif mode == 'all':
        # 모든 메트릭 표시 (간략화)
        h_n, h_j, h_c = head_metric['local_nps'], head_metric['jack'], head_metric['chord']
        t_n, t_j, t_c = tail_metric['local_nps'], tail_metric['jack'], tail_metric['chord']
        return f"Hn{h_n:.2f}j{h_j:.2f}_Tn{t_n:.2f}j{t_j:.2f}.wav"
    else:
        return "normal-hitnormal.wav"


def export_debug_osu(notes, original_file, output_path, metric_mode, key_count=None, nps_v2=None, jack_diff=None, total_diff=None):
    """
    디버그용 .osu 파일 생성
    
    Args:
        notes (list): 노트 리스트
        original_file (str): 원본 파일 경로
        output_path (str): 출력 파일 경로
        metric_mode (str): 표시할 메트릭 모드
        key_count (int): 키 개수 (None이면 노트의 열 번호에서 자동 감지)
        nps_v2 (dict): NPS v2 결과 (None이면 기존 NPS 사용)
        jack_diff (dict): Jack difficulty 결과
        total_diff (dict): Total difficulty 결과
    """
    # 노트별 메트릭 계산 (새 파라미터 전달)
    note_metrics = calculate_note_metrics(notes, nps_v2, jack_diff, total_diff)
    
    # key_count 자동 감지 (전달되지 않은 경우)
    if key_count is None:
        if notes:
            used_columns = set(n['column'] for n in notes)
            max_col = max(used_columns)
            min_col = min(used_columns)
            # DP: 열 9-16 사용 시 16키
            if max_col >= 9:
                key_count = 16
            # SP: 열 1-8 사용 시 8키
            else:
                key_count = 8
        else:
            key_count = 8  # 기본값
    
    # 원본 파일이 .osu라면 헤더 정보 가져오기
    header_lines = []
    hit_objects_started = False
    
    if original_file.lower().endswith('.osu'):
        try:
            with open(original_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.strip() == '[HitObjects]':
                        hit_objects_started = True
                        header_lines.append(line)
                        break
                    elif line.startswith("Version:"):
                        line = f"Version:{metric_mode}\n"
                    header_lines.append(line)
        except:
            # 파일 읽기 실패 시 기본 헤더 사용
            pass
    
    # 헤더가 없으면 기본 헤더 생성
    if not header_lines:
        header_lines = [
            "osu file format v14\n",
            "\n",
            "[General]\n",
            "AudioFilename: virtual\n",
            "AudioLeadIn: 0\n",
            "PreviewTime: 0\n",
            "Countdown: 0\n",
            "SampleSet: Normal\n",
            "StackLeniency: 0.7\n",
            "Mode: 3\n",
            "LetterboxInBreaks: 0\n",
            "\n",
            "[Difficulty]\n",
            "HPDrainRate: 8\n",
            f"CircleSize: {key_count}\n",  # 키 개수에 맞게 동적 설정
            "OverallDifficulty: 8\n",
            "ApproachRate: 5\n",
            "SliderMultiplier: 1.4\n",
            "SliderTickRate: 1\n",
            "\n",
            "[Metadata]\n",
            f"Title:Debug View - {metric_mode}\n",
            "TitleUnicode:Debug View\n",
            f"Artist:Metric: {metric_mode}\n",
            "ArtistUnicode:Debug\n",
            "Creator:Debug Tool\n",
            f"Version:Debug-{metric_mode}\n",
            "Source:\n",
            "Tags:debug metrics visualization\n",
            "\n",
            "[HitObjects]\n"
        ]
    
    # .osu 파일 작성
    with open(output_path, 'w', encoding='utf-8') as f:
        # 헤더 쓰기
        f.writelines(header_lines)
        
        # HitObjects 쓰기
        for i, nm in enumerate(note_metrics):
            note = nm['note']
            
            # 열(column) 가져오기
            column = note.get('column', 1)
            
            # x 좌표 계산: key_count에 맞게 변환
            # OSU 공식: column = floor(x * key_count / 512)
            # 역산: x = (col_0indexed + 0.5) * 512 / key_count
            #
            # 모든 키 모드에서 열이 1부터 시작하므로 1을 빼서 0-indexed로 변환
            # (BMS 파서의 모든 키 모드 매핑이 열 1부터 시작함)
            col_0indexed = column - 1
            
            # 음수 방지 (혹시 열 0이 있는 경우)
            if col_0indexed < 0:
                col_0indexed = 0
            
            # x 좌표 계산
            x = int((col_0indexed + 0.5) * 512 / key_count)
            y = 192  # 고정
            
            # 시간 (ms)
            time_ms = int(note['time'] * 1000)
            
            # 노트 타입
            note_type = note.get('type', 'note')
            
            # HitSound 파일명 생성 (롱노트 머리/꼬리 표시 포함)
            hitsound = format_hitsound_name(nm, metric_mode, note_type)
            
            if note_type == 'ln_start':
                # Long Note: x,y,time,type,hitSound,endTime:hitSample
                # 다음 ln_end 찾기 + 꼬리 메트릭도 가져오기
                end_time = time_ms + 100  # 기본값
                tail_metric = nm  # 기본값: 머리와 동일
                for j in range(i+1, len(note_metrics)):
                    next_note = note_metrics[j]['note']
                    if (next_note.get('type') == 'ln_end' and 
                        next_note.get('column') == note.get('column')):
                        end_time = int(next_note['time'] * 1000)
                        tail_metric = note_metrics[j]  # 꼬리 메트릭 저장
                        break
                
                # 머리 + 꼬리 메트릭 모두 표시하는 키음 이름 생성
                hitsound = format_ln_hitsound_name(nm, tail_metric, metric_mode)
                
                type_flags = 128  # LN
                f.write(f"{x},{y},{time_ms},{type_flags},0,{end_time}:0:0:0:0:{hitsound}\n")
            
            elif note_type == 'ln_end':
                # LN end는 이미 start에서 처리됨
                continue
            
            else:
                # Normal Note
                type_flags = 1  # Circle
                f.write(f"{x},{y},{time_ms},{type_flags},0,0:0:0:0:{hitsound}\n")
    
    print(f"✅ 디버그 OSU 파일 생성: {output_path}")
    print(f"   키 개수: {key_count}")
    print(f"   총 노트수: {len([n for n in notes if n.get('type') != 'ln_end'])}")


def export_multiple_modes(notes, original_file, output_dir, key_count=None, nps_v2=None, jack_diff=None, total_diff=None):
    """
    여러 메트릭 모드로 여러 파일 생성
    
    Args:
        notes (list): 노트 리스트
        original_file (str): 원본 파일 경로
        output_dir (str): 출력 디렉토리
        key_count (int): 키 개수 (None이면 자동 감지)
        nps_v2 (dict): NPS v2 결과 (None이면 기존 NPS 사용)
        jack_diff (dict): Jack difficulty 결과
        total_diff (dict): Total difficulty 결과
    """
    # 기존 모드 + 새 모드 - 글로벌 값 모드 제외
    modes = [
        'nps_v2', 'j75', 'j100', 'j125', 'j150',
        'jack_nps_v2', 'jack_interval', 'jack_score_uniformity', 'jack_acc_uniformity',
        'score_diff', 'acc_diff', 'jack_diff_score', 'jack_diff_acc',
        'ldb', 'ldbd', 'fds', 'fds_d', 'fda', 'fda_d', 'rds', 'rds_d', 'rda', 'rda_d',
        'lfds', 'lfds_d', 'lfda', 'lfda_d', 'lrds', 'lrds_d', 'lrda', 'lrda_d',
        'distance_difficulty', 'minimum_distance_sum', 'vrs', 'vra',
    ]
    
    basename = os.path.basename(original_file)
    name_without_ext = os.path.splitext(basename)[0]
    
    for mode in modes:
        output_file = os.path.join(output_dir, f"{name_without_ext}_DEBUG_{mode}.osu")
        export_debug_osu(notes, original_file, output_file, mode, key_count, nps_v2, jack_diff, total_diff)

