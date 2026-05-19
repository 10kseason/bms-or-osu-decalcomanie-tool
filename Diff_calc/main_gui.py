from __future__ import annotations

import csv
import hashlib
import json
import os
import queue
import sys
import threading
import time
import multiprocessing

IS_MP_WORKER = __name__ == "__mp_main__" or multiprocessing.current_process().name != "MainProcess"

if not IS_MP_WORKER:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    import tkinter.font as tkfont

    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
else:  # multiprocessing child process: keep imports minimal/safe
    tk = None
    ttk = None
    filedialog = None
    messagebox = None
    tkfont = None
    plt = None
    FigureCanvasTkAgg = None

import bms_parser
import debug_osu_export
import new_calc
import osu_parser

"""config.yaml에서 판정 프리셋 목록 동적 로드 + 자동 옵션 추가"""
import yaml

version = "1.0.0"

def _batch_key_label(key_count, mode_name):
    if mode_name == "10+2K":
        return "10K2S"
    if mode_name == "DP16":
        return "14K2S"
    if mode_name == "5+1":
        return "5K1S"
    if mode_name == "7+1":
        return "7K1S"
    if isinstance(key_count, int):
        if key_count == 12:
            return "10K2S"
        if key_count == 16:
            return "14K2S"
        return f"{key_count}K"
    return None


def _extract_title_from_header(header, fallback=""):
    if not isinstance(header, dict):
        return fallback or ""
    for key in ("Title", "TITLE", "title", "TitleUnicode"):
        value = header.get(key)
        if value:
            return str(value).strip()
    return fallback or ""


def _extract_artist_from_header(header, fallback=""):
    if not isinstance(header, dict):
        return fallback or ""
    for key in ("ArtistUnicode", "Artist", "ARTIST", "artist"):
        value = header.get(key)
        if value:
            return str(value).strip()
    return fallback or ""


def _extract_version_from_header(header):
    if not isinstance(header, dict):
        return ""
    for key in ("Version", "VERSION", "version"):
        value = header.get(key)
        if value:
            return str(value).strip()
    return ""


def _extract_name_diff_from_header(header, is_osu: bool):
    if not isinstance(header, dict):
        return ""
    if is_osu:
        return _extract_version_from_header(header)
    for key in ("SUBTITLE", "SUB_TITLE", "PLAYLEVEL", "DIFFICULTY"):
        value = header.get(key)
        if value:
            if key == "PLAYLEVEL":
                return "[LV."+ str(value).strip() +"]"
            else:
                return str(value).strip()
    return ""


def _build_display_title(header, fallback, is_osu: bool):
    title = _extract_title_from_header(header, fallback)
    if is_osu:
        version = _extract_version_from_header(header)
        if version:
            return f"{title} [{version}]"
    return title


def _compute_file_hashes(path):
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5.update(chunk)
                sha256.update(chunk)
    except Exception:
        return "", ""
    return md5.hexdigest(), sha256.hexdigest()


def _resolve_preset_name_from_header(judgment_preset_value, header, is_osu: bool):
    preset_name = str(judgment_preset_value or "").strip()
    if not preset_name.startswith("auto_"):
        return preset_name

    header = header or {}

    if is_osu:
        od = 8.0
        try:
            od = float(header.get("OverallDifficulty", 8.0))
        except Exception:
            od = 8.0

        if preset_name == "auto_stable":
            return f"osu_od_interpolate_{od}"
        return f"osu_lazer_od_interpolate_{od}"

    rank_value = None
    try:
        rank_value = header.get("RANK", header.get("rank"))
        rank_value = int(str(rank_value).strip())
    except Exception:
        rank_value = None

    if rank_value == 0:
        return "qwilight_bms_vh"
    if rank_value == 1:
        return "qwilight_bms_hd"
    if rank_value == 2:
        return "qwilight_bms_nm"
    return "qwilight_bms_ez"


def analyze_file_summary_mp(
    path,
    selected_filters,
    judgment_preset_value,
    life_gauge_value,
    note_line_random,
    zero_poor_mode=False,
    config=None,
):

    ext = os.path.splitext(path)[1].lower()
    file_name = os.path.basename(path)
    title = file_name
    title_raw = file_name
    artist = ""
    name_diff = ""
    md5_hash, sha256_hash = _compute_file_hashes(path)

    try:
        if ext == ".osu":
            parser = osu_parser.OsuParser(path)
            is_osu = True
        else:
            parser = bms_parser.BMSParser(path)
            is_osu = False

        notes = parser.parse()
        duration = getattr(parser, "duration", 0.0) or 0.0
        duration = duration if duration > 0 else 1.0
        key_count = getattr(parser, "key_count", None)
        mode_name = getattr(parser, "detected_mode", None)
        header = getattr(parser, "header", {}) if hasattr(parser, "header") else {}
        title_raw = _extract_title_from_header(header, file_name)
        title = _build_display_title(header, file_name, is_osu=is_osu)
        artist = _extract_artist_from_header(header, "")
        name_diff = _extract_name_diff_from_header(header, is_osu=is_osu)

        key_label = _batch_key_label(key_count, mode_name)
        if selected_filters and key_label not in selected_filters:
            return {
                "file_path": path,
                "file_name": file_name,
                "title": title,
                "key_count": key_count,
                "mode_name": mode_name,
                "key_label": key_label,
                "status": "Skipped",
                "reason": "Key filter",
                "md5": md5_hash,
                "sha256": sha256_hash,
                "title_raw": title_raw,
                "artist": artist,
                "is_osu": is_osu,
            }

        if not notes:
            return {
                "file_path": path,
                "file_name": file_name,
                "title": title,
                "key_count": key_count,
                "mode_name": mode_name,
                "key_label": key_label,
                "status": "Error",
                "error": "No notes",
                "md5": md5_hash,
                "sha256": sha256_hash,
                "title_raw": title_raw,
                "artist": artist,
                "name_diff": name_diff,
                "is_osu": is_osu,
            }


        preset_name = _resolve_preset_name_from_header(judgment_preset_value, header, is_osu=is_osu)
        total_diff = new_calc.calculate_total_difficulty(
            notes,
            duration,
            key_mode=key_count or 7,
            preset_name=preset_name,
            mode_name=mode_name,
            random_placement=bool(note_line_random),
            life_gauge=life_gauge_value,
            zero_poor_mode=bool(zero_poor_mode),
            config=config,
        )

        circus_rating = total_diff.get("circus_rating") if isinstance(total_diff, dict) else None
        try:
            circus_rating = float(circus_rating)
        except (TypeError, ValueError):
            circus_rating = 0.0

        revive_lv = total_diff.get("revive_lv") if isinstance(total_diff, dict) else None
        try:
            revive_lv = int(revive_lv)
        except (TypeError, ValueError):
            revive_lv = 0
        return {
            "file_path": path,
            "file_name": file_name,
            "title": title,
            "key_count": key_count,
            "mode_name": mode_name,
            "key_label": key_label,
            "status": "Success",
            "level": circus_rating,
            "revive_lv": revive_lv,
            "avg_nps": float(total_diff.get('global_nps')),
            "peak_nps": int(total_diff.get("peak_nps")),
            "notes": int(len(notes)),
            "duration": float(duration),
            "md5": md5_hash,
            "sha256": sha256_hash,
            "title_raw": title_raw,
            "artist": artist,
            "name_diff": name_diff,
            "is_osu": is_osu,
        }
    except Exception as e:
        return {
            "file_path": path,
            "file_name": file_name,
            "title": title,
            "status": "Error",
            "error": str(e),
            "md5": md5_hash,
            "sha256": sha256_hash,
            "title_raw": title_raw,
            "artist": artist,
            "name_diff": name_diff,
            "is_osu": is_osu,
        }


def batch_worker_process(
    task_queue,
    result_queue,
    selected_filters,
    judgment_preset_value,
    life_gauge_value,
    note_line_random,
    zero_poor_mode,
    config
):
    while True:
        path = task_queue.get()
        if path is None:
            break
        try:
            result = analyze_file_summary_mp(
                path,
                selected_filters,
                judgment_preset_value,
                life_gauge_value,
                note_line_random,
                zero_poor_mode,
                config
            )
        except Exception as e:
            result = {
                "file_path": path,
                "file_name": os.path.basename(path),
                "status": "Error",
                "error": str(e),
            }
        try:
            result_queue.put(result)
        except Exception:
            # If the parent process is gone or the queue is broken, exit.
            break


class BMSCalculatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Revive Difficulty Calculator " + version)
        self.root.geometry("1200x720")

        self.is_dev_mode = "--dev" in sys.argv
        if self.is_dev_mode:
            self.root.title("Revive Difficulty Calculator (Developer Mode)")

        # ------------------------------
        # Single analysis state
        # ------------------------------
        self.file_path = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        self.debug_mode_var = tk.BooleanVar(value=False)
        self.judgment_preset_var = tk.StringVar(value="auto_stable")
        self.life_gauge_var = tk.StringVar(value="Score % Acc %")
        self.random_placement_var = tk.BooleanVar(value=False)  # Note Line Random (기존 Random 옵션)
        self.zero_poor_mode_var = tk.BooleanVar(value=False)
        self.graph_data_var = tk.StringVar(value="note_score_diff")

        self.card_est_level_var = tk.StringVar(value="--")
        self.card_revive_level_var = tk.StringVar(value="--")
        self.card_total_notes_var = tk.StringVar(value="--")
        self.card_key_counter_var = tk.StringVar(value="--")
        self.card_global_nps_var = tk.StringVar(value="--")
        self.card_peak_nps_var = tk.StringVar(value="--")
        self.main_file_name_var = tk.StringVar(value="")

        self.last_notes = None
        self.last_total_diff = None
        self.last_file_path = None
        self.last_key_count = None
        self.last_mode_name = None
        self.last_duration = None
        self.last_preset_name = None
        self.last_header = {}
        self.last_bpm_definitions = None
        self.last_sv_list = None

        self.file_total_notes = None

        # ------------------------------
        # Batch analysis state
        # ------------------------------
        self.batch_folder_var = tk.StringVar(value="")
        self.batch_recursive_var = tk.BooleanVar(value=True)
        self.batch_progress_text_var = tk.StringVar(value="Ready")
        self.batch_progress_var = tk.DoubleVar(value=0.0)
        # self.batch_double_threads_var = tk.BooleanVar(value=False)
        self.cpu_core_text_var = tk.StringVar(value=f"CPU Cores : {os.cpu_count() or 4}")
        self.batch_key_filter_vars = {
            "4K": tk.BooleanVar(value=False),
            "5K": tk.BooleanVar(value=False),
            "5K1S": tk.BooleanVar(value=False),
            "6K": tk.BooleanVar(value=False),
            "7K": tk.BooleanVar(value=False),
            "7K1S": tk.BooleanVar(value=False),
            "8K": tk.BooleanVar(value=False),
            "9K": tk.BooleanVar(value=False),
            "10K": tk.BooleanVar(value=False),
            "10K2S": tk.BooleanVar(value=False),
            "14K": tk.BooleanVar(value=False),
            "14K2S": tk.BooleanVar(value=False),
            "18K": tk.BooleanVar(value=False),
        }

        self._batch_cancel_event = threading.Event()
        self._batch_queue = queue.Queue()
        self._batch_thread = None
        self._batch_results = []
        self._batch_total = 0
        self._batch_done = 0
        self._batch_running = False

        self._analysis_seq = 0
        self._recalc_in_progress = False
        self._recalc_pending = False
        self._recalc_token = 0
        self._recalc_thread = None
        self._file_title_fit_after = None

        self._create_widgets()

    # ------------------------------
    # Config / presets
    # ------------------------------
    def load_judgment_presets(self):
        auto_options = ["auto_stable", "auto_lazer"]

        if config and "judgment_presets" in config:
            preset_keys = list(config["judgment_presets"].keys())
            return auto_options + preset_keys

        return auto_options + ["qwilight_bms_ez", "osu_od8"]

    # ------------------------------
    # UI
    # ------------------------------
    def _create_widgets(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

        self.tab_single = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_single, text="단일 분석 (Single)")
        self._create_single_tab(self.tab_single)

        self.tab_batch = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_batch, text="일괄 분석 (Batch)")
        self._create_batch_tab(self.tab_batch)

        status_bar = ttk.Frame(self.root)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(status_bar, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew")

        self.status_spinner = ttk.Progressbar(status_bar, mode="indeterminate", length=90)
        self.status_spinner.grid(row=0, column=1, sticky="e", padx=(6, 6), pady=2)
        self.status_spinner.grid_remove()

        if hasattr(self, "main_file_name_var") and self.main_file_name_var is not None:
            try:
                self.main_file_name_var.trace_add("write", lambda *_args: self._schedule_file_title_fit())
            except Exception:
                pass

    def _on_notebook_tab_changed(self, _event=None):
        # Batch 분석에서는 Debug Mode를 사용하지 않도록 고정
        try:
            selected = self.notebook.select()
            tab_text = self.notebook.tab(selected, "text") or ""
        except Exception:
            return

        if "일괄" in tab_text or "Batch" in tab_text:
            try:
                if bool(self.debug_mode_var.get()):
                    self.debug_mode_var.set(False)
                    self._on_debug_mode_toggle()
            except Exception:
                pass

    def _create_single_tab(self, parent):
        container = ttk.Frame(parent, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(container)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        main_area = ttk.Frame(container)
        main_area.grid(row=0, column=1, sticky="nsew")
        main_area.columnconfigure(0, weight=1)
        main_area.rowconfigure(2, weight=1)

        # Sidebar: file + calculate
        file_frame = ttk.Frame(sidebar)
        file_frame.pack(fill=tk.X)
        ttk.Label(file_frame, text="File:").grid(row=0, column=0, sticky="w")
        ttk.Entry(file_frame, textvariable=self.file_path, width=36).grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Button(file_frame, text="Browse", command=self.browse_file).grid(row=1, column=1, padx=(6, 0), pady=(2, 0))
        file_frame.columnconfigure(0, weight=1)

        ttk.Button(sidebar, text="Calculate", command=self.calculate).pack(fill=tk.X, pady=(10, 10))

        options = ttk.LabelFrame(sidebar, text="Options", padding=10)
        options.pack(fill=tk.X)

        ttk.Checkbutton(
            options,
            text="🔧 Debug Mode",
            variable=self.debug_mode_var,
            command=self._on_debug_mode_toggle,
        ).pack(anchor="w")

        self.debug_osu_button = ttk.Button(options, text="🔍 Debug OSU", command=self.export_debug_osu)

        ttk.Label(options, text="Judgement System").pack(anchor="w", pady=(10, 0))
        preset_combo = ttk.Combobox(
            options,
            textvariable=self.judgment_preset_var,
            values=self.load_judgment_presets(),
            state="readonly",
        )
        preset_combo.pack(fill=tk.X, pady=(2, 0))

        ttk.Label(options, text="Target").pack(anchor="w", pady=(10, 0))
        gauge_list = [
            "Score % Acc %",
            "Full Combo",
            "Perfect Play",
        ]
        gauge_combo = ttk.Combobox(options, textvariable=self.life_gauge_var, values=gauge_list, state="readonly")
        gauge_combo.pack(fill=tk.X, pady=(2, 0))

        ttk.Checkbutton(
            options,
            text="Note Line Random",
            variable=self.random_placement_var,
        ).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(
            options,
            text="0Poor Mode",
            variable=self.zero_poor_mode_var,
        ).pack(anchor="w", pady=(2, 0))

        ttk.Label(options, text="Graph Data").pack(anchor="w", pady=(10, 0))
        graph_data_list = [
            "note_score_diff",
            "note_acc_diff",
            "note_jack_diff_score",
            "note_jack_diff_acc",
            "j75",
            "j100",
            "j125",
            "j150",
            "jack_nps_v2",
            "jack_interval",
            "jack_score_uniformity",
            "jack_acc_uniformity",
            "fds",
            "fda",
            "rds",
            "rda",
            "lfds",
            "lfda",
            "lrds",
            "lrda",
            "distance_difficulty",
            "minimum_distance_sum",
            "vrs",
            "vra",
            "ldb",
            "ldbd",
            "nps",
            "nps_v2",
            "sv_list",
        ]
        graph_combo = ttk.Combobox(options, textvariable=self.graph_data_var, values=graph_data_list, state="readonly")
        graph_combo.pack(fill=tk.X, pady=(2, 0))
        graph_combo.bind("<<ComboboxSelected>>", lambda _event: self.update_graph())

        # File title (large)
        file_title_frame = tk.Frame(main_area, bg="#ffffff", highlightbackground="#d0d0d0", highlightthickness=1)
        file_title_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        file_title_frame.columnconfigure(0, weight=1)
        self.file_title_frame = file_title_frame
        self.file_title_font = tkfont.Font(family="Arial", size=18, weight="bold")
        self.file_title_label = tk.Label(
            file_title_frame,
            textvariable=self.main_file_name_var,
            bg="#ffffff",
            fg="#000000",
            font=self.file_title_font,
            anchor="center",
            justify="center",
        )
        self.file_title_label.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        file_title_frame.bind("<Configure>", self._schedule_file_title_fit)

        # Cards
        cards_frame = ttk.Frame(main_area)
        cards_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for i in range(3):
            cards_frame.columnconfigure(i, weight=1, uniform="cards")
        cards_frame.rowconfigure(0, weight=1)
        cards_frame.rowconfigure(1, weight=1)

        def make_card(title, value_var, value_font=("Arial", 24, "bold"), justify="center", anchor="center"):
            card = tk.Frame(cards_frame, bg="#ffffff", highlightbackground="#d0d0d0", highlightthickness=1)
            tk.Label(card, text=title, bg="#ffffff", fg="#444444", font=("Arial", 12)).pack(pady=(10, 0))
            tk.Label(
                card,
                textvariable=value_var,
                bg="#ffffff",
                fg="#000000",
                font=value_font,
                justify=justify,
                anchor=anchor,
            ).pack(pady=(2, 10), fill=tk.BOTH, expand=True)
            return card

        make_card("Circus Rating", self.card_est_level_var).grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        make_card("Revive Level", self.card_revive_level_var).grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        make_card("Total Notes", self.card_total_notes_var).grid(row=0, column=2, sticky="nsew", padx=6, pady=6)
        make_card("Key Counter", self.card_key_counter_var).grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        make_card("Avg NPS", self.card_global_nps_var).grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        make_card("Peak NPS", self.card_peak_nps_var).grid(row=1, column=2, sticky="nsew", padx=6, pady=6)

        # Graph
        graph_frame = ttk.Frame(main_area, padding=10)
        graph_frame.grid(row=2, column=0, sticky="nsew")
        graph_frame.columnconfigure(0, weight=1)
        graph_frame.rowconfigure(0, weight=1)

        self.fig, self.ax_sd = plt.subplots(figsize=(9, 4.8), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        # Debug details (hidden unless debug mode)
        self.debug_details_frame = ttk.LabelFrame(main_area, text="Details (Debug)", padding=10)
        self.debug_details_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.debug_details_frame.columnconfigure(0, weight=1)
        self.debug_details_frame.rowconfigure(0, weight=1)
        self.result_text = tk.Text(self.debug_details_frame, height=10, font=("Consolas", 10))
        self.result_text.grid(row=0, column=0, sticky="nsew")

        self._on_debug_mode_toggle()

    def _create_batch_tab(self, parent):
        container = ttk.Frame(parent, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(container)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        main_area = ttk.Frame(container)
        main_area.grid(row=0, column=1, sticky="nsew")
        main_area.columnconfigure(0, weight=1)
        main_area.rowconfigure(0, weight=1)

        ttk.Label(sidebar, text="일괄 분석", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 10))

        folder_frame = ttk.LabelFrame(sidebar, text="Folder", padding=10)
        folder_frame.pack(fill=tk.X)
        ttk.Button(folder_frame, text="Select Folder", command=self.select_batch_folder).pack(fill=tk.X)
        ttk.Entry(folder_frame, textvariable=self.batch_folder_var).pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(folder_frame, text="하위 폴더 포함 (Recursive)", variable=self.batch_recursive_var).pack(
            anchor="w", pady=(8, 0)
        )

        filter_frame = ttk.LabelFrame(sidebar, text="Key Filter", padding=10)
        filter_frame.pack(fill=tk.X, pady=(10, 0))

        filter_order = ["4K", "5K", "5K1S", "6K", "7K", "7K1S", "8K", "9K", "10K", "10K2S", "14K", "14K2S", "18K"]
        for idx, key in enumerate(filter_order):
            r = idx // 2
            c = idx % 2
            ttk.Checkbutton(filter_frame, text=key, variable=self.batch_key_filter_vars[key]).grid(
                row=r, column=c, sticky="w", padx=(0, 10), pady=2
            )

        ttk.Label(sidebar, textvariable=self.cpu_core_text_var).pack(anchor="w", pady=(10, 0))
        # ttk.Checkbutton(sidebar, text="x2 Thread", variable=self.batch_double_threads_var).pack(
        #     anchor="w", pady=(4, 0)
        # )

        self.batch_start_button = ttk.Button(sidebar, text="Start Batch Analysis", command=self.start_batch_analysis)
        self.batch_start_button.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(sidebar, textvariable=self.batch_progress_text_var).pack(anchor="w", pady=(10, 0))
        ttk.Progressbar(
            sidebar, orient="horizontal", mode="determinate", maximum=100.0, variable=self.batch_progress_var
        ).pack(fill=tk.X, pady=(6, 0))

        self.batch_stop_button = ttk.Button(sidebar, text="Stop", command=self.stop_batch_analysis, state="disabled")
        self.batch_stop_button.pack(fill=tk.X, pady=(8, 0))

        # Table
        columns = ("title", "key_counter", "level", "revive_lv", "avg_nps", "peak_nps", "notes", "status", "message")
        self.batch_tree = ttk.Treeview(main_area, columns=columns, show="headings")
        self.batch_tree.heading("title", text="Title", command=lambda: self._sort_batch_tree("title", False))
        self.batch_tree.heading("key_counter", text="Key Counter", command=lambda: self._sort_batch_tree("key_counter", False))
        self.batch_tree.heading("level", text="Circus Rating", command=lambda: self._sort_batch_tree("level", False))
        self.batch_tree.heading("revive_lv", text="Revive Lv", command=lambda: self._sort_batch_tree("revive_lv", False))
        self.batch_tree.heading("avg_nps", text="Avg NPS", command=lambda: self._sort_batch_tree("avg_nps", False))
        self.batch_tree.heading("peak_nps", text="Peak NPS", command=lambda: self._sort_batch_tree("peak_nps", False))
        self.batch_tree.heading("notes", text="Notes", command=lambda: self._sort_batch_tree("notes", False))
        self.batch_tree.heading("status", text="Status", command=lambda: self._sort_batch_tree("status", False))
        self.batch_tree.heading("message", text="Message", command=lambda: self._sort_batch_tree("message", False))

        self.batch_tree.column("title", width=540, anchor="w")
        self.batch_tree.column("key_counter", width=120, anchor="center")
        self.batch_tree.column("level", width=120, anchor="center")
        self.batch_tree.column("revive_lv", width=100, anchor="center")
        self.batch_tree.column("avg_nps", width=100, anchor="center")
        self.batch_tree.column("peak_nps", width=100, anchor="center")
        self.batch_tree.column("notes", width=100, anchor="center")
        self.batch_tree.column("status", width=100, anchor="center")
        self.batch_tree.column("message", width=100, anchor="center")

        y_scroll = ttk.Scrollbar(main_area, orient="vertical", command=self.batch_tree.yview)
        x_scroll = ttk.Scrollbar(main_area, orient="horizontal", command=self.batch_tree.xview)
        self.batch_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.batch_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        export_frame = ttk.Frame(main_area)
        export_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        export_frame.columnconfigure(0, weight=1)
        self.batch_export_button = ttk.Button(
            export_frame, text="Export Results (CSV/JSON)", command=self.export_batch_results, state="disabled"
        )
        self.batch_export_button.grid(row=0, column=0, sticky="ew")

    def _on_debug_mode_toggle(self):
        debug = bool(self.debug_mode_var.get())

        # Debug OSU button in sidebar
        if debug:
            if not self.debug_osu_button.winfo_ismapped():
                self.debug_osu_button.pack(fill=tk.X, pady=(8, 0))
        else:
            if self.debug_osu_button.winfo_ismapped():
                self.debug_osu_button.pack_forget()

        # Debug details frame
        if hasattr(self, "debug_details_frame"):
            if debug:
                self.debug_details_frame.grid()
            else:
                self.debug_details_frame.grid_remove()

    def _on_preset_inputs_changed(self, _event=None):
        print("_on_preset_inputs_changed")
        if self.last_notes is None or self.last_duration is None:
            return
        self._recalculate_total_difficulty()

    def _schedule_file_title_fit(self, _event=None):
        if not hasattr(self, "root") or self.root is None:
            return
        if self._file_title_fit_after is not None:
            try:
                self.root.after_cancel(self._file_title_fit_after)
            except Exception:
                pass
            self._file_title_fit_after = None
        try:
            self._file_title_fit_after = self.root.after(50, self._fit_file_title_font)
        except Exception:
            self._file_title_fit_after = None

    def _fit_file_title_font(self):
        self._file_title_fit_after = None

        label = getattr(self, "file_title_label", None)
        frame = getattr(self, "file_title_frame", None)
        font = getattr(self, "file_title_font", None)
        if label is None or frame is None or font is None:
            return

        text = ""
        try:
            text = str(self.main_file_name_var.get() or "")
        except Exception:
            text = ""

        if not text:
            label.configure(wraplength=0)
            return

        width = 0
        try:
            width = int(frame.winfo_width())
        except Exception:
            width = 0
        if width <= 1:
            try:
                width = int(label.winfo_width())
            except Exception:
                width = 0

        available = max(0, width - 40)
        if available <= 0:
            label.configure(wraplength=0)
            return

        base_size = 18
        min_size = 10
        chosen = min_size
        for size in range(base_size, min_size - 1, -1):
            try:
                font.configure(size=size)
                if font.measure(text) <= available:
                    chosen = size
                    break
            except Exception:
                chosen = min_size
                break

        try:
            font.configure(size=chosen)
        except Exception:
            pass

        wraplength = 0
        try:
            if font.measure(text) > available:
                wraplength = available
        except Exception:
            wraplength = available

        try:
            label.configure(wraplength=wraplength)
        except Exception:
            pass

    def _set_recalc_indicator(self, active: bool):
        spinner = getattr(self, "status_spinner", None)
        if spinner is None:
            return
        try:
            if active:
                spinner.grid()
                spinner.start(12)
            else:
                spinner.stop()
                spinner.grid_remove()
        except Exception:
            pass

    def _recalculate_total_difficulty(self):
        return
    
    # ------------------------------
    # Single analysis actions
    # ------------------------------
    def browse_file(self):
        filename = filedialog.askopenfilename(
            filetypes=[
                ("Rhythm Game Files", "*.bms *.bme *.bml *.osu *.pms"),
                ("BMS Files", "*.bms *.bme *.bml *.pms"),
                ("Osu Files", "*.osu"),
                ("All Files", "*.*"),
            ]
        )
        if filename:
            self.file_path.set(filename)

    def _resolve_preset_name_from_header(self, header, is_osu: bool):
        preset_name = self.judgment_preset_var.get()
        if not preset_name.startswith("auto_"):
            return preset_name

        header = header or {}

        if is_osu:
            od = 8.0
            try:
                od = float(header.get("OverallDifficulty", 8.0))
            except Exception:
                od = 8.0

            if preset_name == "auto_stable":
                return f"osu_od_interpolate_{od}"
            return f"osu_lazer_od_interpolate_{od}"

        # BMS: #RANK 기반 프리셋 선택
        rank_value = None
        try:
            rank_value = header.get("RANK", header.get("rank"))
            rank_value = int(str(rank_value).strip())
        except Exception:
            rank_value = None

        if rank_value == 0:
            return "qwilight_bms_vh"
        if rank_value == 1:
            return "qwilight_bms_hd"
        if rank_value == 2:
            return "qwilight_bms_nm"
        return "qwilight_bms_ez"


    def calculate(self):
        path = self.file_path.get().strip()
        if not path:
            messagebox.showerror("Error", "Please select a file.")
            return

        self._analysis_seq += 1

        self.status_var.set("Parsing...")
        self.card_est_level_var.set("--")
        self.card_revive_level_var.set("--")
        self.card_total_notes_var.set("--")
        self.card_key_counter_var.set("--")
        self.card_global_nps_var.set("--")
        self.card_peak_nps_var.set("--")
        self.root.update()

        try:
            t_total_start = time.time()
            total_diff = None

            # 1) Parse
            t_parse_start = time.time()
            is_osu = path.lower().endswith(".osu")
            if is_osu:
                parser = osu_parser.OsuParser(path)
                notes = parser.parse()
                duration = parser.duration
            else:
                parser = bms_parser.BMSParser(path)
                notes = parser.parse()
                duration = parser.duration

            t_parse_end = time.time()
            print(f"[TIMER] Parsing: {(t_parse_end - t_parse_start) * 1000:.2f} ms")

            if not notes:
                messagebox.showwarning("Warning", "No notes found in file.")
                self.status_var.set("Ready")
                return

            self.file_total_notes = len(notes)
            if hasattr(parser, "header"):
                self.last_header = dict(parser.header) if isinstance(parser.header, dict) else {}
            else:
                self.last_header = {}
            self.last_bpm_definitions = getattr(parser, "bpm_definitions", None)
            self.last_sv_list = getattr(parser, "sv_list", None)

            # Store for debug export / graph
            self.last_notes = notes
            self.last_file_path = path
            self.last_key_count = getattr(parser, "key_count", None)
            self.last_mode_name = getattr(parser, "detected_mode", None)
            self.last_duration = duration

            # Update cards
            self.card_total_notes_var.set(f"{len(notes):,}")
            file_name = os.path.basename(path)
            self.main_file_name_var.set(file_name)
            key_label = _batch_key_label(self.last_key_count, self.last_mode_name)
            if key_label is None:
                key_label = f"{self.last_key_count}K" if self.last_key_count is not None else "--"
            self.card_key_counter_var.set(key_label)

            # 4) Total difficulty for graph
            self.status_var.set("Computing Total Difficulty...")
            self.root.update()
            t_total_diff_start = time.time()
            preset_name = self._resolve_preset_name_from_header(self.last_header, is_osu=is_osu)
            total_diff = new_calc.calculate_total_difficulty(
                notes,
                duration,
                key_mode=self.last_key_count or 7,
                preset_name=preset_name,
                mode_name=self.last_mode_name,
                random_placement=self.random_placement_var.get(),
                life_gauge=self.life_gauge_var.get(),
                sv_list=self.last_sv_list,
                zero_poor_mode=bool(self.zero_poor_mode_var.get()),
                config=config,
                create_multiprocessing_workers=True,
            )
            self.last_total_diff = total_diff
            self.last_preset_name = preset_name
            t_total_diff_end = time.time()
            print(f"[TIMER] Total Difficulty: {(t_total_diff_end - t_total_diff_start) * 1000:.2f} ms")

            self.card_global_nps_var.set(f"{total_diff.get('global_nps'):.2f}")
            self.card_peak_nps_var.set(str(total_diff.get("peak_nps")))
            self.card_est_level_var.set(f"{total_diff.get('circus_rating'):.2f}")
            self.card_revive_level_var.set(str(total_diff.get("revive_lv")))

            # 5) Plot
            self._plot_graph(total_diff, notes)

            # Debug text
            if self.debug_mode_var.get():
                debug_text = self._build_debug_text(
                    path=path,
                    key_count=self.last_key_count,
                    mode_name=self.last_mode_name,
                    duration=duration,
                    total_diff=total_diff,
                )
                self.result_text.delete("1.0", tk.END)
                self.result_text.insert(tk.END, debug_text)

            t_total_end = time.time()
            print(f"[TIMER] Total: {(t_total_end - t_total_start) * 1000:.2f} ms")
            self.status_var.set("Calculation Complete.")

        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status_var.set("Error occurred.")
            print(e)

    def _build_debug_text(self, path, key_count, mode_name, duration, total_diff):
        base = os.path.basename(path)
        key_count = key_count if key_count is not None else "?"
        pred_global_nps = total_diff.get("global_nps", 0.0)
        pred_peak_nps = total_diff.get("peak_nps", 0)

        lines = []
        lines.append("═" * 60)
        lines.append(f"File        : {base}")
        md5_hash, sha256_hash = ("", "")
        if path:
            md5_hash, sha256_hash = _compute_file_hashes(path)
        if md5_hash or sha256_hash:
            lines.append(f"MD5         : {md5_hash or '-'}")
            lines.append(f"SHA256      : {sha256_hash or '-'}")
        lines.append(f"Key Mode    : {key_count}K" + (f" ({mode_name})" if mode_name else ""))
        try:
            total_notes = int(self.file_total_notes or 0)
        except Exception:
            total_notes = 0
        lines.append(f"Notes       : {total_notes:,}")
        lines.append(f"Length      : {duration:.2f}s")
        lines.append("")
        header = self.last_header if isinstance(self.last_header, dict) else {}
        file_od = header.get("OverallDifficulty")
        file_hp = header.get("HPDrainRate")
        if file_od is not None or file_hp is not None:
            lines.append("─ Osu File Params")
            if file_od is not None:
                try:
                    lines.append(f"OD          : {float(file_od):.2f}")
                except Exception:
                    lines.append(f"OD          : {file_od}")
            if file_hp is not None:
                try:
                    lines.append(f"HP          : {float(file_hp):.2f}")
                except Exception:
                    lines.append(f"HP          : {file_hp}")
            lines.append("")
        if isinstance(total_diff, dict) and total_diff.get("circus_rating") is not None:
            lines.append("─ Circus Rating")
            lines.append(f"Rating      : {float(total_diff.get('circus_rating')):.9}")
            if total_diff.get("revive_lv") is not None:
                lines.append(f"Revive Lv   : {int(total_diff.get('revive_lv'))}")
            lines.append("")

        lines.append("─ Level (new_calc linear)")
        lines.append(f"Avg NPS     : {pred_global_nps:.2f}")
        lines.append(f"Peak NPS    : {pred_peak_nps}")

        if total_diff:
            score = total_diff.get("score_diff_l5_avg")
            acc = total_diff.get("acc_diff_l5_avg")
            lines.append("")
            lines.append("─ Total Difficulty (summary)")
            if score is not None:
                lines.append(f"Score Diff  : {score:.4f}")
            if acc is not None:
                lines.append(f"Acc Diff    : {acc:.4f}")

            if isinstance(total_diff, dict):
                score_sum = total_diff.get("score_diff_l5_sum")
                acc_sum = total_diff.get("acc_diff_l5_sum")
                target_type = total_diff.get("target_type")
            else:
                score_sum = acc_sum = None
                target_type = None

            lines.append("")
            lines.append("─ Total Difficulty (L5)")
            if score_sum is not None:
                lines.append(f"Score L5 Sum: {float(score_sum):.9f}")
            if score is not None:
                lines.append(f"Score L5 Avg: {float(score):.9f}")
            if acc_sum is not None:
                lines.append(f"Acc L5 Sum  : {float(acc_sum):.9f}")
            if acc is not None:
                lines.append(f"Acc L5 Avg  : {float(acc):.9f}")
            if target_type is not None:
                target_label = {
                    "score_acc": "Score % Acc %",
                    "full_combo": "Full Combo",
                    "perfect_play": "Perfect Play",
                }.get(str(target_type), target_type)
                lines.append(f"Target      : {target_label}")

            jack_diff = total_diff.get("jack_diff") if isinstance(total_diff, dict) else None
            if isinstance(jack_diff, dict):
                lines.append("")
                lines.append("─ Jack Difficulty")
                # jack_score = jack_diff.get("jack_diff_score")
                # jack_acc = jack_diff.get("jack_diff_acc")
                # if jack_score is not None:
                #     lines.append(f"Jack Score  : {float(jack_score):.4f}")
                # if jack_acc is not None:
                #     lines.append(f"Jack Acc    : {float(jack_acc):.4f}")

                def _safe_max(values):
                    try:
                        return max(values) if values else None
                    except Exception:
                        return None

                j150 = _safe_max(jack_diff.get("j150", []))
                j125 = _safe_max(jack_diff.get("j125", []))
                j100 = _safe_max(jack_diff.get("j100", []))
                j75 = _safe_max(jack_diff.get("j75", []))
                if j150 is not None or j125 is not None or j100 is not None or j75 is not None:
                    lines.append("")
                    lines.append(f"j150 (max)  : {float(j150 or 0.0):.2f} ms  # stamina")
                    lines.append(f"j125 (max)  : {float(j125 or 0.0):.2f} ms  # speed")
                    lines.append(f"j100 (max)  : {float(j100 or 0.0):.2f} ms  # talent")
                    lines.append(f"j75  (max)  : {float(j75 or 0.0):.2f} ms  # impossible")

            nps_v2 = total_diff.get("nps_v2") if isinstance(total_diff, dict) else None
            if isinstance(nps_v2, dict):
                lines.append("")
                lines.append("─ NPS v2")

            note_diff = total_diff.get("note_diff") if isinstance(total_diff, dict) else None
            time_deltas = note_diff.get("time_deltas") if isinstance(note_diff, dict) else None
            type_time_delta = note_diff.get("type_time_delta") if isinstance(note_diff, dict) else None

            if isinstance(note_diff, dict):
                lines.append("")
                lines.append("─ Flex/Read Difficulty (all stats)")

                # Averages (as stored)
                avg_keys = sorted(k for k in note_diff.keys() if k.startswith("avg_"))
                if avg_keys:
                    lines.append("")
                    lines.append("Averages")
                    for k in avg_keys:
                        try:
                            lines.append(f"{k:16s}: {float(note_diff.get(k, 0.0)):.4f}")
                        except Exception:
                            lines.append(f"{k:16s}: {note_diff.get(k)}")

                # Weights / settings
                lines.append("")
                lines.append("Weights")
                for k in ("fd_weight", "rd_weight", "lfd_weight", "lrd_weight", "distance_weight"):
                    if k in note_diff:
                        lines.append(f"{k:16s}: {note_diff.get(k)}")

            if isinstance(time_deltas, dict):
                def _safe_int(value):
                    try:
                        return int(value)
                    except Exception:
                        return 0

                def _format_metric(metric):
                    pr = _safe_int(time_deltas.get(f"time_delta_{metric}_plus_rice", 0))
                    mr = _safe_int(time_deltas.get(f"time_delta_{metric}_minus_rice", 0))
                    ph = _safe_int(time_deltas.get(f"time_delta_{metric}_plus_head", 0))
                    mh = _safe_int(time_deltas.get(f"time_delta_{metric}_minus_head", 0))
                    pt = _safe_int(time_deltas.get(f"time_delta_{metric}_plus_tail", 0))
                    mt = _safe_int(time_deltas.get(f"time_delta_{metric}_minus_tail", 0))
                    return f"rice +{pr}/-{mr}, head +{ph}/-{mh}, tail +{pt}/-{mt}"

                lines.append("")
                lines.append("─ Time Delta (ms)")
                if type_time_delta is not None:
                    lines.append(f"Type        : {type_time_delta}")
                lines.append(f"Score       : {_format_metric('score')}")
                lines.append(f"Acc         : {_format_metric('acc')}")

            if isinstance(total_diff, dict):
                jd_score_rice = total_diff.get("judge_difficulty_score_rice")
                jd_score_head = total_diff.get("judge_difficulty_score_head")
                jd_score_tail = total_diff.get("judge_difficulty_score_tail")
                jd_acc_rice = total_diff.get("judge_difficulty_acc_rice")
                jd_acc_head = total_diff.get("judge_difficulty_acc_head")
                jd_acc_tail = total_diff.get("judge_difficulty_acc_tail")

                if (
                    jd_score_rice is not None
                    or jd_score_head is not None
                    or jd_score_tail is not None
                    or jd_acc_rice is not None
                    or jd_acc_head is not None
                    or jd_acc_tail is not None
                ):
                    lines.append("")
                    lines.append("─ Judge Difficulty (calc)")
                    if jd_score_rice is not None:
                        lines.append(
                            f"Rice        : score {float(jd_score_rice):.4f}  acc {float(jd_acc_rice):.4f}"
                        )
                    if jd_score_head is not None:
                        lines.append(
                            f"Head        : score {float(jd_score_head):.4f}  acc {float(jd_acc_head):.4f}"
                        )
                    if jd_score_tail is not None:
                        lines.append(
                            f"Tail        : score {float(jd_score_tail):.4f}  acc {float(jd_acc_tail):.4f}"
                        )

            # Verbose debug details (backup/main_gui.py style)
            lines.append("")
            lines.append("🔧 Debug Details (verbose)")
            lines.append("═" * 50)

            # Note type distribution
            notes = self.last_notes if isinstance(self.last_notes, list) else []
            note_types = {}
            for note in notes:
                try:
                    note_type = note.get("type", "unknown")
                except Exception:
                    note_type = "unknown"
                note_types[note_type] = note_types.get(note_type, 0) + 1

            lines.append("")
            lines.append("📝 Note Types")
            lines.append("─" * 50)
            if notes:
                for ntype, count in sorted(note_types.items()):
                    percentage = (count / len(notes) * 100) if notes else 0.0
                    lines.append(f"  {ntype:15s}: {count:5,d} ({percentage:5.2f}%)")
            else:
                lines.append("  (no notes loaded)")

            # Parser info
            lines.append("")
            lines.append("📄 Parser Info")
            lines.append("─" * 50)
            header = self.last_header if isinstance(self.last_header, dict) else {}
            if header:
                lines.append("  Header:")
                for key, value in list(header.items())[:10]:
                    lines.append(f"    {key}: {value}")
            else:
                lines.append("  (no header)")

            bpm_defs = self.last_bpm_definitions
            if isinstance(bpm_defs, dict) and bpm_defs:
                lines.append("")
                lines.append(f"  BPM Definitions: {len(bpm_defs)}")
                for bpm_key, bpm_val in list(bpm_defs.items())[:5]:
                    lines.append(f"    {bpm_key}: {bpm_val}")

        return "\n".join(lines)

    # ------------------------------
    # Debug OSU export
    # ------------------------------
    def export_debug_osu(self):
        """디버그용 OSU 파일 내보내기"""
        if self.last_notes is None:
            messagebox.showwarning("경고", "먼저 파일을 계산해주세요.\n(Calculate 버튼 클릭)")
            return

        output_dir = filedialog.askdirectory(title="디버그 OSU 파일 저장 위치 선택")
        if not output_dir:
            return

        try:
            self.status_var.set("디버그 OSU 파일 생성 중...")
            self.root.update()

            nps_v2_result = None
            jack_diff_result = None
            total_diff_result = None


            total_diff_result = self.last_total_diff
            nps_v2_result = total_diff_result.get("nps_v2")
            jack_diff_result = total_diff_result.get("jack_diff")

            debug_osu_export.export_multiple_modes(
                self.last_notes,
                self.last_file_path,
                output_dir,
                key_count=self.last_key_count,
                nps_v2=nps_v2_result,
                jack_diff=jack_diff_result,
                total_diff=total_diff_result,
            )

            self.status_var.set("디버그 OSU 파일 생성 완료!")
            messagebox.showinfo(
                "완료",
                f"디버그 OSU 파일이 생성되었습니다!\n\n"
                f"위치: {output_dir}\n"
                f"오스 에디터에서 열어서 확인하세요!",
            )
        except Exception as e:
            messagebox.showerror("오류", f"디버그 파일 생성 실패:\n{str(e)}")
            self.status_var.set("오류 발생")

    # ------------------------------
    # Graph
    # ------------------------------
    def _plot_graph(self, total_diff, notes):
        self.ax_sd.clear()
        self.ax_sd.set_yscale("linear")

        graph_data_key = self.graph_data_var.get()
        graph_values = None
        data_label = graph_data_key

        if total_diff is None:
            total_diff = self.last_total_diff

        if graph_data_key == "sv_list":
            sv_list = []
            if isinstance(total_diff, dict):
                sv_list = total_diff.get("sv_list") or []
            if sv_list:
                x_values = []
                y_values = []
                for entry in sv_list:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        continue
                    try:
                        x_values.append(float(entry[0]) / 1000.0)
                        y_values.append(float(entry[1]))
                    except Exception:
                        continue
                if x_values and y_values:
                    self.ax_sd.scatter(x_values, y_values, c="blue", s=8, alpha=0.7)
                    self.ax_sd.set_title("sv_list over Time")
                    self.ax_sd.set_xlabel("Time (s)")
                    self.ax_sd.set_ylabel("Beat Length (ms)")
                    try:
                        self.ax_sd.set_yscale("log", base=2)
                    except TypeError:
                        self.ax_sd.set_yscale("log", basey=2)
                else:
                    self.ax_sd.set_title("No sv_list Data")
            else:
                self.ax_sd.set_title("No sv_list Data")

            self.fig.tight_layout(pad=2.0)
            self.canvas.draw()
            return

        if total_diff is not None:
            if graph_data_key == "nps_v2" and "nps_v2" in total_diff:
                if isinstance(total_diff["nps_v2"], dict):
                    graph_values = total_diff["nps_v2"].get("nps_v2", [])
                else:
                    graph_values = total_diff["nps_v2"]
            elif graph_data_key in total_diff and isinstance(total_diff[graph_data_key], list):
                graph_values = total_diff.get(graph_data_key, [])
            elif "jack_diff" in total_diff and graph_data_key in total_diff["jack_diff"]:
                graph_values = total_diff["jack_diff"].get(graph_data_key, [])
            elif "note_diff" in total_diff and graph_data_key in total_diff["note_diff"]:
                graph_values = total_diff["note_diff"].get(graph_data_key, [])

        line_keys = set()

        if graph_values and len(graph_values) > 0:
            if graph_data_key in line_keys:
                x_values = list(range(len(graph_values)))
                self.ax_sd.plot(x_values, graph_values, c="blue", linewidth=1)
                self.ax_sd.set_title(f"{data_label} per Index")
                self.ax_sd.set_xlabel("Index (i)")
                self.ax_sd.set_ylabel(data_label)
            else:
                if not notes:
                    self.ax_sd.set_title(f"No {data_label} Data")
                    self.ax_sd.set_ylabel(data_label)
                else:
                    note_times = [n["time"] for n in notes[: len(graph_values)]]
                    self.ax_sd.scatter(note_times, graph_values, c="blue", s=1, alpha=0.6)
                    self.ax_sd.set_title(f"{data_label} per Note")
                    self.ax_sd.set_xlabel("Time (s)")
                    self.ax_sd.set_ylabel(data_label)
        else:
            self.ax_sd.set_title(f"No {data_label} Data")

        self.fig.tight_layout(pad=2.0)
        self.canvas.draw()

    def update_graph(self):
        if self.last_notes is None:
            return
        self._plot_graph(self.last_total_diff, self.last_notes)

    # ------------------------------
    # Batch analysis
    # ------------------------------
    def select_batch_folder(self):
        folder = filedialog.askdirectory(title="분석할 폴더 선택")
        if folder:
            self.batch_folder_var.set(folder)

    def _iter_batch_files(self, folder: str, recursive: bool):
        exts = {".bms", ".bme", ".bml", ".pms", ".osu"}
        if recursive:
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    if os.path.splitext(name)[1].lower() in exts:
                        yield os.path.join(root, name)
        else:
            for name in os.listdir(folder):
                full = os.path.join(folder, name)
                if os.path.isfile(full) and os.path.splitext(name)[1].lower() in exts:
                    yield full

    def _selected_key_filters(self):
        return {k for k, v in self.batch_key_filter_vars.items() if v.get()}

    def _key_label(self, key_count, mode_name):
        return _batch_key_label(key_count, mode_name)

    def _sort_batch_tree(self, col, reverse: bool):
        def to_number(value: str):
            try:
                return float(str(value).strip())
            except Exception:
                return float("-inf")

        numeric_cols = {"level", "revive_lv", "avg_nps", "peak_nps", "notes"}
        items = [(self.batch_tree.set(k, col), k) for k in self.batch_tree.get_children("")]

        if col in numeric_cols:
            items.sort(key=lambda t: to_number(t[0]), reverse=reverse)
        else:
            items.sort(key=lambda t: str(t[0]).lower(), reverse=reverse)

        for index, (_val, k) in enumerate(items):
            self.batch_tree.move(k, "", index)

        self.batch_tree.heading(col, command=lambda: self._sort_batch_tree(col, not reverse))

    def start_batch_analysis(self):
        if self._batch_running:
            return

        # Batch 분석에서는 Debug Mode를 사용하지 않도록 고정
        try:
            if bool(self.debug_mode_var.get()):
                self.debug_mode_var.set(False)
                self._on_debug_mode_toggle()
        except Exception:
            pass

        folder = self.batch_folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "유효한 폴더를 선택해주세요.")
            return

        files = sorted(self._iter_batch_files(folder, recursive=self.batch_recursive_var.get()))
        if not files:
            messagebox.showwarning("Warning", "폴더에서 처리할 파일을 찾지 못했습니다.")
            return

        for item in self.batch_tree.get_children():
            self.batch_tree.delete(item)

        self._batch_results = []
        self._batch_total = len(files)
        self._batch_done = 0
        self._batch_cancel_event.clear()
        self._batch_running = True

        self.batch_export_button.config(state="disabled")
        self.batch_start_button.config(state="disabled")
        self.batch_stop_button.config(state="normal")

        self.batch_progress_var.set(0.0)
        self.batch_progress_text_var.set(f"Processing: 0/{self._batch_total} files (0%)")

        selected_filters = self._selected_key_filters()
        judgment_preset_value = self.judgment_preset_var.get()
        life_gauge_value = self.life_gauge_var.get()
        note_line_random = bool(self.random_placement_var.get())
        zero_poor_mode = bool(self.zero_poor_mode_var.get())
        # double_threads = bool(self.batch_double_threads_var.get())

        self._batch_thread = threading.Thread(
            target=self._run_batch_worker,
            args=(
                files,
                selected_filters,
                judgment_preset_value,
                life_gauge_value,
                note_line_random,
                zero_poor_mode,
            ),
            daemon=True,
        )
        self._batch_thread.start()
        self.root.after(100, self._poll_batch_queue)

    def stop_batch_analysis(self):
        if not self._batch_running:
            return
        self._batch_cancel_event.set()
        self.batch_progress_text_var.set("Stopping...")
        self.batch_stop_button.config(state="disabled")

    def _run_batch_worker(
        self,
        files,
        selected_filters,
        judgment_preset_value,
        life_gauge_value,
        note_line_random,
        zero_poor_mode,
    ):
        cpu_workers = os.cpu_count() or 4
        base_workers = max(1, min(cpu_workers, len(files)))
        # if double_threads:
        #     workers = min(base_workers * 2, cpu_workers * 2, len(files))
        # else:
        workers = base_workers

        ctx = multiprocessing.get_context("spawn")
        task_queue = ctx.Queue()
        result_queue = ctx.Queue()

        for path in files:
            task_queue.put(path)
        for _ in range(workers):
            task_queue.put(None)

        processes = []
        try:
            for _ in range(workers):
                p = ctx.Process(
                    target=batch_worker_process,
                    args=(
                        task_queue,
                        result_queue,
                        selected_filters,
                        judgment_preset_value,
                        life_gauge_value,
                        note_line_random,
                        zero_poor_mode,
                        config
                    ),
                    daemon=True,
                )
                p.start()
                processes.append(p)

            expected = len(files)
            received = 0
            while received < expected:
                if self._batch_cancel_event.is_set():
                    break
                try:
                    item = result_queue.get(timeout=0.1)
                except queue.Empty:
                    # If all workers died unexpectedly, avoid hanging forever.
                    alive = False
                    for p in processes:
                        try:
                            if p.is_alive():
                                alive = True
                                break
                        except Exception:
                            continue
                    if not alive:
                        # Drain any remaining results, then stop.
                        while True:
                            try:
                                item = result_queue.get_nowait()
                            except queue.Empty:
                                break
                            received += 1
                            self._batch_queue.put(item)
                        break
                    continue
                received += 1
                self._batch_queue.put(item)
        finally:
            if self._batch_cancel_event.is_set():
                for p in processes:
                    try:
                        if p.is_alive():
                            p.terminate()
                    except Exception:
                        pass

            for p in processes:
                try:
                    p.join(timeout=5)
                except Exception:
                    pass

            for p in processes:
                try:
                    if p.is_alive():
                        p.terminate()
                        p.join(timeout=1)
                except Exception:
                    pass

            self._batch_queue.put({"type": "done"})


    def _poll_batch_queue(self):
        try:
            while True:
                item = self._batch_queue.get_nowait()
                if isinstance(item, dict) and item.get("type") == "done":
                    self._finish_batch()
                    return

                self._batch_done += 1
                self._batch_results.append(item)

                status = item.get("status", "")
                title = item.get("title") or item.get("file_name", "") or ""
                name_diff = item.get("name_diff", "")
                is_osu = item.get("is_osu", True)
                if not is_osu:
                    title = title + " " + name_diff
                key_label = item.get("key_label")
                if not key_label:
                    key_count = item.get("key_count")
                    mode_name = item.get("mode_name")
                    key_label = _batch_key_label(key_count, mode_name)
                key_label = key_label or ""
                message = ""
                level_str = ""
                revive_str = ""
                avg_nps_str = ""
                peak_nps_str = ""
                notes_str = ""

                if status == "Success":
                    try:
                        level_str = f"{float(item.get('level', 0.0)):.2f}"
                    except Exception:
                        level_str = ""
                    try:
                        revive_str = str(int(item.get("revive_lv", 0)))
                    except Exception:
                        revive_str = ""
                    try:
                        avg_nps_str = f"{float(item.get('avg_nps', 0.0)):.2f}"
                    except Exception:
                        avg_nps_str = ""
                    try:
                        peak_nps_str = str(int(item.get("peak_nps", 0)))
                    except Exception:
                        peak_nps_str = ""
                    try:
                        notes_str = str(int(item.get("notes", 0)))
                    except Exception:
                        notes_str = ""
                elif status == "Skipped":
                    message = str(item.get("reason", "") or "")
                elif status == "Error":
                    message = str(item.get("error", "") or "")

                self.batch_tree.insert(
                    "",
                    "end",
                    values=(
                        title,
                        key_label,
                        level_str,
                        revive_str,
                        avg_nps_str,
                        peak_nps_str,
                        notes_str,
                        status,
                        message,
                    ),
                )

                percent = int((self._batch_done / self._batch_total) * 100) if self._batch_total else 0
                self.batch_progress_var.set(float(percent))
                self.batch_progress_text_var.set(f"Processing: {self._batch_done}/{self._batch_total} files ({percent}%)")
        except queue.Empty:
            pass

        self.root.after(100, self._poll_batch_queue)

    def _finish_batch(self):
        self._batch_running = False
        self.batch_start_button.config(state="normal")
        self.batch_stop_button.config(state="disabled")

        success_count = sum(1 for r in self._batch_results if r.get("status") == "Success")
        error_count = sum(1 for r in self._batch_results if r.get("status") == "Error")
        skipped_count = sum(1 for r in self._batch_results if r.get("status") == "Skipped")
        canceled_count = sum(1 for r in self._batch_results if r.get("status") == "Canceled")
        self.batch_progress_text_var.set(
            f"Done: {success_count} success / {error_count} error / {skipped_count} skipped / {canceled_count} canceled / {self._batch_total} scanned"
        )

        if self._batch_results:
            self.batch_export_button.config(state="normal")

    def export_batch_results(self):
        if not self._batch_results:
            messagebox.showwarning("Warning", "내보낼 결과가 없습니다.")
            return

        export_rows = [row for row in self._batch_results if row.get("status") == "Success"]
        if not export_rows:
            messagebox.showwarning("Warning", "내보낼 성공 결과가 없습니다.")
            return

        out_dir = filedialog.askdirectory(title="내보낼 폴더 선택 (CSV/JSON)")
        if not out_dir:
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(out_dir, f"batch_results_{timestamp}.csv")
        json_path = os.path.join(out_dir, f"batch_results_{timestamp}.json")

        fields = [
            "file_name",
            "title",
            "file_path",
            "status",
            "level",
            "revive_lv",
            "avg_nps",
            "peak_nps",
            "notes",
            "duration",
            "key_count",
            "mode_name",
            "key_label",
            "reason",
            "error",
        ]

        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for row in export_rows:
                    writer.writerow({k: row.get(k, "") for k in fields})

            with open(json_path, "w", encoding="utf-8") as f:
                json_payload = []
                for row in export_rows:
                    revive_lv = row.get("revive_lv", "")
                    level_value = ""
                    if revive_lv not in (None, ""):
                        try:
                            level_value = str(int(revive_lv))
                        except Exception:
                            level_value = str(revive_lv)
                    title_raw = row.get("title_raw") or row.get("title") or row.get("file_name") or ""
                    json_payload.append(
                        {
                            "level": level_value,
                            "md5": row.get("md5", "") or "",
                            "sha256": row.get("sha256", "") or "",
                            "title": title_raw,
                            "artist": row.get("artist", "") or "",
                            "name_diff": row.get("name_diff", "") or "",
                        }
                    )
                json.dump(json_payload, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("완료", f"내보내기 완료:\n{csv_path}\n{json_path}")
        except Exception as e:
            messagebox.showerror("오류", f"내보내기 실패:\n{e}")



if __name__ == "__main__":

    def on_closing():
        # 필요하다면 여기서 정리 작업 수행 (예: 파일 닫기, 스레드 종료)
        print("프로그램 종료 중...")
        root.destroy()  # GUI 창 닫기
        sys.exit()      # 프로세스 종료

    def resource_path(relative_path):
        # 실행 파일로 빌드된 경우 (sys.frozen) 경로 설정
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        # 개발 중인 경우 (직접 실행)
        return os.path.join(os.path.abspath('.'), relative_path)

    config_path = resource_path("config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)



    multiprocessing.freeze_support()
    root = tk.Tk()
    root.protocol("WM_DELETE_WINDOW", on_closing)

    img = tk.PhotoImage(file=resource_path("icon.png"))
    root.iconphoto(False, img)
    app = BMSCalculatorApp(root)
    root.mainloop()
