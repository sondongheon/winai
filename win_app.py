"""
Windows desktop application shell for the WinAI engine.
"""

from __future__ import annotations

import base64
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext
from typing import Callable, cast

from app_settings import AppSettings
from dialogue_engine import DialogueEngine
from dialogue_engine import TurnResult
from main_engine import MainEngine


class WinAIDesktopApp:
    def __init__(self,
                 engine_factory: Callable[[AppSettings], MainEngine],
                 initial_settings: AppSettings):
        self._engine_factory = engine_factory
        self._settings = initial_settings
        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._engine: MainEngine | None = None
        self._dialogue: DialogueEngine | None = None
        self._image = None
        self._memory = None
        self._interface = None
        self._camera_after_id: str | None = None
        self._camera_preview_image: tk.PhotoImage | None = None

        self.root = tk.Tk()
        self.root.title("WinAI Desktop")
        self.root.geometry("980x820")
        self.root.minsize(760, 640)
        self.root.configure(bg="#0f172a")
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

        self.status_var = tk.StringVar(value="엔진 초기화 중...")
        self.connection_var = tk.StringVar(value="LLM 상태 확인 중...")
        self.visual_var = tk.StringVar(value="시각화 패널 준비 중...")
        self.db_path_var = tk.StringVar(value=self._settings.db_path)
        self.llm_url_var = tk.StringVar(value=self._settings.llm_url)
        self.llm_model_var = tk.StringVar(value=self._settings.llm_model)
        self.db_label_var = tk.StringVar()
        self.interface_var = tk.StringVar(value="인터페이스 초기화 중...")
        self.camera_var = tk.StringVar(value="카메라 대기 중...")

        self._build_layout()
        self._boot_engine()
        self.root.after(100, self._drain_ui_queue)

    def _build_layout(self):
        palette = {
            "bg": "#0f172a",
            "panel": "#111827",
            "panel_alt": "#1e293b",
            "border": "#334155",
            "text": "#e2e8f0",
            "muted": "#94a3b8",
            "accent": "#22c55e",
            "accent_dim": "#16a34a",
            "user": "#38bdf8",
            "assistant": "#f8fafc",
            "warning": "#f59e0b",
        }

        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        header = tk.Frame(self.root, bg=palette["bg"], padx=24, pady=18)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title = tk.Label(
            header,
            text="WinAI Desktop",
            font=("Malgun Gothic", 24, "bold"),
            bg=palette["bg"],
            fg=palette["text"],
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = tk.Label(
            header,
            text="메모리 엔진 + LLM + 시각화 엔진을 Windows 앱으로 묶은 데스크톱 셸",
            font=("Malgun Gothic", 10),
            bg=palette["bg"],
            fg=palette["muted"],
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(6, 0))

        shell = tk.Frame(self.root, bg=palette["bg"], padx=24, pady=0)
        shell.grid(row=1, column=0, sticky="nsew")
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=3)
        shell.grid_columnconfigure(1, weight=2)

        left_panel = tk.Frame(shell, bg=palette["bg"])
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left_panel.grid_rowconfigure(0, weight=0)
        left_panel.grid_rowconfigure(1, weight=0)
        left_panel.grid_rowconfigure(2, weight=1)
        left_panel.grid_columnconfigure(0, weight=1)

        visual_panel = tk.Frame(
            left_panel,
            bg=palette["panel"],
            highlightbackground=palette["border"],
            highlightthickness=1,
        )
        visual_panel.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        visual_panel.grid_columnconfigure(0, weight=1)
        visual_panel.grid_rowconfigure(1, weight=1)

        visual_header = tk.Label(
            visual_panel,
            text="Visualization",
            anchor="w",
            padx=18,
            pady=14,
            font=("Segoe UI Semibold", 12),
            bg=palette["panel_alt"],
            fg=palette["text"],
        )
        visual_header.grid(row=0, column=0, sticky="ew")

        visual_host = tk.Frame(
            visual_panel,
            bg="#020617",
            height=240,
        )
        visual_host.grid(row=1, column=0, sticky="ew", padx=16, pady=(16, 8))
        visual_host.grid_propagate(False)
        self.visual_host = visual_host

        visual_status = tk.Label(
            visual_panel,
            textvariable=self.visual_var,
            anchor="w",
            justify="left",
            padx=18,
            pady=0,
            font=("Malgun Gothic", 9),
            bg=palette["panel"],
            fg=palette["muted"],
        )
        visual_status.grid(row=2, column=0, sticky="ew", pady=(0, 14))

        interface_panel = tk.Frame(
            left_panel,
            bg=palette["panel"],
            highlightbackground=palette["border"],
            highlightthickness=1,
        )
        interface_panel.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        interface_panel.grid_columnconfigure(0, weight=1)
        interface_panel.grid_columnconfigure(1, weight=1)

        interface_header = tk.Label(
            interface_panel,
            text="Interface",
            anchor="w",
            padx=18,
            pady=14,
            font=("Segoe UI Semibold", 12),
            bg=palette["panel_alt"],
            fg=palette["text"],
        )
        interface_header.grid(row=0, column=0, columnspan=2, sticky="ew")

        camera_panel = tk.Frame(interface_panel, bg=palette["panel"], padx=16, pady=16)
        camera_panel.grid(row=1, column=0, sticky="nsew")
        camera_panel.grid_columnconfigure(0, weight=1)

        camera_title = tk.Label(
            camera_panel,
            text="Camera Preview",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            bg=palette["panel"],
            fg=palette["text"],
        )
        camera_title.grid(row=0, column=0, sticky="ew")

        self.camera_preview = tk.Label(
            camera_panel,
            text="카메라 프리뷰 대기 중",
            anchor="center",
            justify="center",
            bg="#020617",
            fg=palette["muted"],
            width=34,
            height=10,
        )
        self.camera_preview.grid(row=1, column=0, sticky="ew", pady=(10, 10))

        camera_status = tk.Label(
            camera_panel,
            textvariable=self.camera_var,
            anchor="w",
            justify="left",
            bg=palette["panel"],
            fg=palette["muted"],
            font=("Malgun Gothic", 9),
        )
        camera_status.grid(row=2, column=0, sticky="ew")

        camera_buttons = tk.Frame(camera_panel, bg=palette["panel"])
        camera_buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        camera_buttons.grid_columnconfigure(0, weight=1)
        camera_buttons.grid_columnconfigure(1, weight=1)

        self.camera_start_button = tk.Button(
            camera_buttons,
            text="카메라 시작",
            command=self._start_camera_preview,
            font=("Malgun Gothic", 10),
            bg="#334155",
            fg=palette["text"],
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.camera_start_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.camera_stop_button = tk.Button(
            camera_buttons,
            text="카메라 정지",
            command=self._stop_camera_preview,
            font=("Malgun Gothic", 10),
            bg="#475569",
            fg=palette["text"],
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.camera_stop_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        voice_panel = tk.Frame(interface_panel, bg=palette["panel"], padx=16, pady=16)
        voice_panel.grid(row=1, column=1, sticky="nsew")
        voice_panel.grid_columnconfigure(0, weight=1)

        voice_title = tk.Label(
            voice_panel,
            text="Voice Controls",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
            bg=palette["panel"],
            fg=palette["text"],
        )
        voice_title.grid(row=0, column=0, sticky="ew")

        voice_status = tk.Label(
            voice_panel,
            textvariable=self.interface_var,
            anchor="w",
            justify="left",
            bg=palette["panel"],
            fg=palette["muted"],
            font=("Malgun Gothic", 9),
            wraplength=280,
        )
        voice_status.grid(row=1, column=0, sticky="ew", pady=(10, 10))

        self.voice_prompt_entry = tk.Entry(
            voice_panel,
            font=("Malgun Gothic", 10),
            bg="#0f172a",
            fg=palette["text"],
            insertbackground=palette["text"],
            relief=tk.FLAT,
        )
        self.voice_prompt_entry.grid(row=2, column=0, sticky="ew", ipady=8)
        self.voice_prompt_entry.insert(0, "음성으로 답할 질문을 입력하세요")

        voice_buttons = tk.Frame(voice_panel, bg=palette["panel"])
        voice_buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        for column in range(2):
            voice_buttons.grid_columnconfigure(column, weight=1)

        self.ai_voice_button = tk.Button(
            voice_buttons,
            text="AI 보이스 답변",
            command=self._run_ai_voice,
            font=("Malgun Gothic", 10, "bold"),
            bg="#22c55e",
            fg="#052e16",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.ai_voice_button.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))

        self.tts_last_button = tk.Button(
            voice_buttons,
            text="마지막 응답 읽기",
            command=self._speak_last_response,
            font=("Malgun Gothic", 10),
            bg="#38bdf8",
            fg="#082f49",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.tts_last_button.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))

        self.tts_stop_button = tk.Button(
            voice_buttons,
            text="TTS 중지",
            command=self._stop_tts,
            font=("Malgun Gothic", 10),
            bg="#ef4444",
            fg="#fff1f2",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.tts_stop_button.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        self.qwen_button = tk.Button(
            voice_buttons,
            text="현재 qwen2.5:7b 연결",
            command=self._use_local_qwen_preset,
            font=("Malgun Gothic", 10),
            bg="#a78bfa",
            fg="#1e1b4b",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        self.qwen_button.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        chat_panel = tk.Frame(
            left_panel,
            bg=palette["panel"],
            highlightbackground=palette["border"],
            highlightthickness=1,
        )
        chat_panel.grid(row=2, column=0, sticky="nsew")
        chat_panel.grid_rowconfigure(1, weight=1)
        chat_panel.grid_columnconfigure(0, weight=1)

        chat_header = tk.Label(
            chat_panel,
            text="Conversation",
            anchor="w",
            padx=18,
            pady=14,
            font=("Segoe UI Semibold", 12),
            bg=palette["panel_alt"],
            fg=palette["text"],
        )
        chat_header.grid(row=0, column=0, sticky="ew")

        self.chat_log = scrolledtext.ScrolledText(
            chat_panel,
            wrap=tk.WORD,
            font=("Consolas", 11),
            padx=18,
            pady=18,
            bg="#020617",
            fg=palette["text"],
            insertbackground=palette["text"],
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.chat_log.grid(row=1, column=0, sticky="nsew")
        self.chat_log.configure(state=tk.DISABLED)
        self.chat_log.tag_configure("system", foreground=palette["muted"], spacing3=10)
        self.chat_log.tag_configure("user", foreground=palette["user"], spacing3=10)
        self.chat_log.tag_configure("assistant", foreground=palette["assistant"], spacing3=14)
        self.chat_log.tag_configure("error", foreground="#fca5a5", spacing3=14)

        composer = tk.Frame(chat_panel, bg=palette["panel"], padx=16, pady=16)
        composer.grid(row=2, column=0, sticky="ew")
        composer.grid_columnconfigure(0, weight=1)

        input_entry = tk.Text(
            composer,
            font=("Malgun Gothic", 11),
            bg="#0f172a",
            fg=palette["text"],
            insertbackground=palette["text"],
            relief=tk.FLAT,
            wrap=tk.WORD,
            height=4,
            undo=True,
        )
        input_entry.grid(row=0, column=0, sticky="ew")
        input_entry.bind("<Return>", self._submit_from_event)
        input_entry.bind("<Control-Return>", self._submit_from_event)
        self.input_entry = input_entry

        mic_button = tk.Button(
            composer,
            text="마이크 전송",
            command=self._submit_microphone_message,
            font=("Malgun Gothic", 10),
            bg="#334155",
            fg=palette["text"],
            relief=tk.FLAT,
            padx=14,
            pady=10,
            cursor="hand2",
        )
        mic_button.grid(row=0, column=1, padx=(12, 0))
        self.mic_button = mic_button

        send_button = tk.Button(
            composer,
            text="전송",
            command=self._submit_message,
            font=("Malgun Gothic", 10, "bold"),
            bg=palette["accent"],
            fg="#052e16",
            activebackground=palette["accent_dim"],
            activeforeground="#052e16",
            relief=tk.FLAT,
            padx=18,
            pady=10,
            cursor="hand2",
        )
        send_button.grid(row=0, column=2, padx=(12, 0))
        self.send_button = send_button

        side_panel = tk.Frame(
            shell,
            bg=palette["panel"],
            highlightbackground=palette["border"],
            highlightthickness=1,
            padx=18,
            pady=18,
        )
        side_panel.grid(row=0, column=1, sticky="nsew")
        side_panel.grid_columnconfigure(0, weight=1)

        info_title = tk.Label(
            side_panel,
            text="Runtime",
            font=("Segoe UI Semibold", 12),
            bg=palette["panel"],
            fg=palette["text"],
        )
        info_title.grid(row=0, column=0, sticky="w")

        self.status_label = tk.Label(
            side_panel,
            textvariable=self.status_var,
            justify="left",
            anchor="w",
            wraplength=220,
            font=("Malgun Gothic", 10),
            bg=palette["panel"],
            fg=palette["muted"],
        )
        self.status_label.grid(row=1, column=0, sticky="ew", pady=(12, 18))

        self.connection_label = tk.Label(
            side_panel,
            textvariable=self.connection_var,
            justify="left",
            anchor="w",
            wraplength=220,
            font=("Malgun Gothic", 10),
            bg=palette["panel"],
            fg=palette["warning"],
        )
        self.connection_label.grid(row=2, column=0, sticky="ew", pady=(0, 18))

        settings_title = tk.Label(
            side_panel,
            text="Settings",
            font=("Segoe UI Semibold", 12),
            bg=palette["panel"],
            fg=palette["text"],
        )
        settings_title.grid(row=3, column=0, sticky="w", pady=(0, 10))

        settings_form = tk.Frame(side_panel, bg=palette["panel_alt"], padx=14, pady=14)
        settings_form.grid(row=4, column=0, sticky="ew", pady=(0, 18))
        settings_form.grid_columnconfigure(0, weight=1)

        self._build_setting_field(settings_form, 0, "LLM URL", self.llm_url_var)
        self._build_setting_field(settings_form, 2, "Model", self.llm_model_var)
        self._build_setting_field(settings_form, 4, "DB Path", self.db_path_var)

        button_row = tk.Frame(settings_form, bg=palette["panel_alt"])
        button_row.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        button_row.grid_columnconfigure(0, weight=1)
        button_row.grid_columnconfigure(1, weight=1)

        apply_button = tk.Button(
            button_row,
            text="적용 후 재시작",
            command=self._apply_settings,
            font=("Malgun Gothic", 10, "bold"),
            bg="#38bdf8",
            fg="#082f49",
            activebackground="#0ea5e9",
            activeforeground="#082f49",
            relief=tk.FLAT,
            padx=12,
            pady=9,
            cursor="hand2",
        )
        apply_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.apply_button = apply_button

        refresh_button = tk.Button(
            button_row,
            text="연결 새로고침",
            command=self._refresh_connection_status,
            font=("Malgun Gothic", 10),
            bg="#334155",
            fg=palette["text"],
            activebackground="#475569",
            activeforeground=palette["text"],
            relief=tk.FLAT,
            padx=12,
            pady=9,
            cursor="hand2",
        )
        refresh_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        tips = tk.Label(
            side_panel,
            text=(
                "실행 전 체크\n"
                "- 설정 적용 시 엔진이 재시작됩니다\n"
                "- OpenGL 가능 시 패널 내부에 임베드됩니다\n"
                "- 지원되지 않으면 캔버스 시각화로 대체됩니다"
            ),
            justify="left",
            anchor="nw",
            font=("Malgun Gothic", 10),
            bg=palette["panel_alt"],
            fg=palette["text"],
            padx=14,
            pady=14,
        )
        tips.grid(row=5, column=0, sticky="ew")

        footer = tk.Frame(self.root, bg=palette["bg"], padx=24, pady=14)
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        db_label = tk.Label(
            footer,
            textvariable=self.db_label_var,
            font=("Consolas", 9),
            bg=palette["bg"],
            fg=palette["muted"],
        )
        db_label.grid(row=0, column=0, sticky="w")

    def _build_setting_field(self, parent: tk.Frame, row: int, label: str, variable: tk.StringVar):
        heading = tk.Label(
            parent,
            text=label,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
            bg=parent["bg"],
            fg="#cbd5e1",
        )
        heading.grid(row=row, column=0, sticky="ew")

        entry = tk.Entry(
            parent,
            textvariable=variable,
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#e2e8f0",
            insertbackground="#e2e8f0",
            relief=tk.FLAT,
        )
        entry.grid(row=row + 1, column=0, sticky="ew", ipady=8, pady=(6, 0))

    def _boot_engine(self):
        self._shutdown_engine()

        try:
            self._engine = self._engine_factory(self._settings)
        except Exception as error:
            messagebox.showerror("WinAI", f"엔진 초기화 실패\n\n{error}")
            self.root.destroy()
            return

        self._dialogue = self._engine.dialogue
        self._image = self._engine.image
        self._memory = self._engine.memory_engine
        self._interface = getattr(self._engine, "interface", None)

        if self._dialogue is None:
            messagebox.showerror("WinAI", "DialogueEngine이 연결되지 않았습니다.")
            self.root.destroy()
            return

        self._dialogue.on_response = self._handle_turn_result
        self._start_visualization_panel()
        self._warm_up_state()
        self._update_connection_status()
        self._update_db_label()
        self._update_interface_status()
        self._append_chat("system", "WinAI Desktop이 준비되었습니다. 메시지를 입력하세요.")
        self.status_var.set("준비 완료. 입력을 기다리는 중입니다.")
        self.input_entry.focus_set()

    def _start_visualization_panel(self):
        if self._image is None:
            self.visual_var.set("시각화 엔진이 없습니다.")
            return

        for child in self.visual_host.winfo_children():
            child.destroy()

        self.root.update_idletasks()
        width = max(self.visual_host.winfo_width(), 320)
        height = max(self.visual_host.winfo_height(), 220)

        if self._image.start(
            parent_window_id=self.visual_host.winfo_id(),
            width=width,
            height=height,
        ):
            audio_source = "마이크 입력" if self._image._audio.source == "microphone" else "시뮬레이션 오디오"
            self.visual_var.set(f"OpenGL 시각화 활성\n오디오: {audio_source}")
            return

        fallback_canvas = tk.Canvas(self.visual_host, bg="#020617", relief=tk.FLAT)
        fallback_canvas.pack(fill=tk.BOTH, expand=True)
        if self._image.start(width=width, height=height, tk_canvas=fallback_canvas):
            audio_source = "마이크 입력" if self._image._audio.source == "microphone" else "시뮬레이션 오디오"
            self.visual_var.set(
                f"캔버스 시각화 활성\n오디오: {audio_source}"
            )
            return

        self.visual_var.set(
            f"시각화 비활성화: {self._image.last_error or '사용 가능한 렌더러 없음'}"
        )

    def _warm_up_state(self):
        if self._engine is None:
            return
        from main_engine import Event

        self._engine.emit(Event(
            source="desktop_app",
            target="memory_engine",
            etype="MEMORY_SAVE_FACT",
            payload={
                "key": "system_ready",
                "value": True,
                "qstate": "TRUE",
                "confidence": 1.0,
            },
        ))
        self._engine.tick()
        self._engine.emit(Event(
            source="desktop_app",
            target="memory_engine",
            etype="CACHE_SET",
            payload={
                "key": "system_status",
                "value": "READY",
                "slot": "focus",
                "qstate": "TRUE",
            },
        ))
        self._engine.tick()

    def _update_connection_status(self):
        llm = self._engine.llm if self._engine else None
        status = llm.inspect_connection(timeout_sec=3) if llm else None
        if status and status.connected:
            self.connection_var.set(
                "LLM 연결됨\n"
                f"설정 URL: {status.configured_url}\n"
                f"응답 URL: {status.reachable_url}\n"
                f"응답 포트: {status.response_port}\n"
                f"MODEL: {status.model}"
            )
            self.connection_label.configure(fg="#86efac")
        else:
            lines = [
                "LLM 연결 실패",
                f"설정 URL: {status.configured_url if status else '-'}",
                f"요청 MODEL: {status.model if status else '-'}",
            ]
            if status and status.response_port and status.installed_models:
                preview = ", ".join(status.installed_models[:3])
                lines.append(f"설정 포트({status.response_port}) 모델: {preview}")
            if status and status.alternate_url:
                lines.append(f"대체 응답 URL: {status.alternate_url}")
                if status.alternate_model_found:
                    lines.append(f"같은 모델이 대체 포트({status.alternate_response_port})에 있습니다")
                elif status.alternate_models:
                    preview = ", ".join(status.alternate_models[:3])
                    lines.append(f"대체 포트 모델: {preview}")
            if status and status.error:
                lines.append(f"오류: {status.error}")
            lines.append("앱은 열리지만 응답은 폴백 메시지로 동작합니다.")
            self.connection_var.set("\n".join(lines))
            self.connection_label.configure(fg="#fca5a5")

    def _update_interface_status(self):
        interface = self._interface
        if interface is None:
            self.interface_var.set("인터페이스 모듈이 연결되지 않았습니다.")
            self.camera_var.set("카메라 상태를 알 수 없습니다.")
            return

        snapshot = interface.status_snapshot()
        mic = snapshot["microphone"]
        tts = snapshot["tts"]
        camera = snapshot["camera"]
        self.interface_var.set(
            f"마이크: {'활성' if mic['active'] else '대기'} / {mic['details'].get('source', 'none')}\n"
            f"TTS: {'사용 가능' if tts['available'] else '미설치'}\n"
            f"AI Voice: {'연결됨' if snapshot['ai_voice']['available'] else '미연결'}"
        )
        self.camera_var.set(
            f"카메라: {'활성' if camera['active'] else '대기'}\n"
            f"상태: {camera['last_error'] or ('사용 가능' if camera['available'] else 'OpenCV 미설치')}"
        )

    def _refresh_connection_status(self):
        self.status_var.set("연결 상태를 다시 확인하는 중...")
        self._update_connection_status()
        self.status_var.set("연결 상태 확인 완료")

    def _update_db_label(self):
        db_path = Path(self._settings.db_path).resolve()
        self.db_label_var.set(f"메모리 DB: {db_path}")

    def _apply_settings(self):
        if self.send_button.cget("state") == tk.DISABLED:
            messagebox.showinfo("WinAI", "응답 생성 중에는 설정을 변경할 수 없습니다.")
            return

        llm_url = self.llm_url_var.get().strip()
        llm_model = self.llm_model_var.get().strip()
        db_path = self.db_path_var.get().strip()
        if not llm_url or not llm_model or not db_path:
            messagebox.showwarning("WinAI", "URL, 모델명, DB 경로를 모두 입력하세요.")
            return

        self._settings = AppSettings.from_sources(
            llm_url=llm_url,
            llm_model=llm_model,
            db_path=db_path,
        )
        self._append_chat("system", "설정을 적용하고 엔진을 다시 시작합니다.")
        self.status_var.set("설정 적용 중...")
        self._boot_engine()

    def _use_local_qwen_preset(self):
        self.llm_url_var.set("http://localhost:11434")
        self.llm_model_var.set("qwen2.5:7b")
        self._append_chat("system", "현재 로컬 qwen2.5:7b 프리셋을 적용했습니다. 필요하면 '적용 후 재시작'을 누르세요.")
        self.status_var.set("qwen2.5:7b 프리셋 적용 완료")

    def _submit_from_event(self, event):
        del event
        self._submit_message()
        return "break"

    def _submit_message(self):
        if self._dialogue is None:
            return

        user_input = self._get_input_text().strip()
        if not user_input:
            return

        self._clear_input_text()
        self._start_user_turn(user_input, user_label="You")

    def _start_user_turn(self, user_input: str, user_label: str = "You"):
        if self._dialogue is None:
            return

        dialogue = self._dialogue

        self._append_chat("user", f"{user_label}: {user_input}")
        self.status_var.set("응답 생성 중...")
        self.send_button.configure(state=tk.DISABLED)
        self.mic_button.configure(state=tk.DISABLED)
        self.input_entry.configure(state=tk.DISABLED)

        if self._image:
            self._image.set_speaking(True, intensity=0.8)

        threading.Thread(
            target=self._process_turn,
            args=(dialogue, user_input),
            daemon=True,
        ).start()

    def _submit_microphone_message(self):
        if self._interface is None:
            messagebox.showwarning("WinAI", "인터페이스 모듈이 연결되지 않았습니다.")
            return
        interface = self._interface
        if self.send_button.cget("state") == tk.DISABLED:
            return

        self.status_var.set("마이크 입력을 듣는 중... 4초 내에 말씀하세요.")
        self.send_button.configure(state=tk.DISABLED)
        self.mic_button.configure(state=tk.DISABLED)
        self.input_entry.configure(state=tk.DISABLED)

        def runner():
            try:
                result = interface.transcribe_microphone(duration_sec=4.0, language="ko-KR")
                self._ui_queue.put(("microphone_text", result))
            except Exception as error:
                self._ui_queue.put(("error", str(error)))

        threading.Thread(target=runner, daemon=True).start()

    def _run_ai_voice(self):
        if self._interface is None:
            messagebox.showwarning("WinAI", "인터페이스 모듈이 연결되지 않았습니다.")
            return

        interface = self._interface

        prompt = self.voice_prompt_entry.get().strip() or self._get_input_text().strip()
        if not prompt:
            messagebox.showinfo("WinAI", "AI 보이스에 보낼 질문을 입력하세요.")
            return

        self.status_var.set("AI 보이스 응답 생성 중...")
        self.ai_voice_button.configure(state=tk.DISABLED)
        self.input_entry.configure(state=tk.DISABLED)
        self._append_chat("user", f"Voice: {prompt}")

        context = self._memory.collect_context(recent_n=6) if self._memory is not None else None

        def runner():
            try:
                result = interface.ask_ai_voice(prompt, context=context, speak=True)
                self._ui_queue.put(("ai_voice", result))
            except Exception as error:
                self._ui_queue.put(("error", str(error)))

        threading.Thread(target=runner, daemon=True).start()

    def _speak_last_response(self):
        if self._interface is None:
            return
        text = self._interface.last_ai_response or self._get_input_text().strip()
        if not text:
            messagebox.showinfo("WinAI", "읽을 텍스트가 없습니다.")
            return
        if self._interface.speak_text(text):
            self.status_var.set("TTS 재생 중...")
            self._update_interface_status()
        else:
            messagebox.showwarning("WinAI", "TTS 엔진을 사용할 수 없습니다.")
            self._update_interface_status()

    def _stop_tts(self):
        if self._interface is None:
            return
        self._interface.stop_tts()
        self.status_var.set("TTS 중지 요청 완료")
        self._update_interface_status()

    def _start_camera_preview(self):
        if self._interface is None:
            return
        if not self._interface.camera.start():
            self._update_interface_status()
            self.camera_preview.configure(text="카메라를 시작할 수 없습니다.", image="")
            return
        self._update_interface_status()
        self.camera_preview.configure(text="카메라 연결 중...")
        self._schedule_camera_preview()

    def _schedule_camera_preview(self):
        self._camera_after_id = self.root.after(120, self._update_camera_preview)

    def _update_camera_preview(self):
        self._camera_after_id = None
        if self._interface is None or not self._interface.camera.state.active:
            return

        frame = self._interface.capture_camera_frame()
        if frame is None:
            self.camera_preview.configure(text="카메라 프레임을 읽지 못했습니다.", image="")
            self._update_interface_status()
            return

        cv2_module = getattr(self._interface.camera, "cv2", None)
        if cv2_module is None:
            self.camera_preview.configure(text="OpenCV가 없어 프리뷰를 그릴 수 없습니다.", image="")
            return

        resized = cv2_module.resize(frame, (320, 180))
        ok, png_buffer = cv2_module.imencode(".png", resized)
        if not ok:
            self.camera_preview.configure(text="카메라 인코딩 실패", image="")
            return

        image_data = base64.b64encode(png_buffer.tobytes()).decode("ascii")
        photo = tk.PhotoImage(data=image_data)
        self._camera_preview_image = photo
        self.camera_preview.configure(image=photo, text="")
        self._schedule_camera_preview()

    def _stop_camera_preview(self):
        if self._camera_after_id is not None:
            self.root.after_cancel(self._camera_after_id)
            self._camera_after_id = None
        if self._interface is not None:
            self._interface.camera.stop()
        self._camera_preview_image = None
        self.camera_preview.configure(image="", text="카메라 프리뷰 대기 중")
        self._update_interface_status()

    def _process_turn(self, dialogue: DialogueEngine, user_input: str):
        try:
            dialogue.process(user_input)
        except Exception as error:
            self._ui_queue.put(("error", str(error)))

    def _handle_turn_result(self, result: TurnResult):
        self._ui_queue.put(("result", result))

    def _drain_ui_queue(self):
        while True:
            try:
                item_type, payload = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            if item_type == "result":
                self._render_turn_result(cast(TurnResult, payload))
            elif item_type == "ai_voice":
                self._render_ai_voice_result(cast(dict, payload))
            elif item_type == "microphone_text":
                self._render_microphone_text(cast(dict, payload))
            elif item_type == "error":
                self._render_error(str(payload))

        self.root.after(100, self._drain_ui_queue)

    def _render_turn_result(self, result: TurnResult):
        if self._image:
            self._image.set_speaking(False)
            self._image.set_emotion(result.emotion.value)

        tag = "assistant" if result.success else "error"
        prefix = "AI" if result.success else "AI 오류"
        self._append_chat(tag, f"{prefix}: {result.llm_response}")
        self.status_var.set(
            f"마지막 응답: {result.intent.value} / {result.emotion.value} / {result.elapsed}초"
        )
        self.send_button.configure(state=tk.NORMAL)
        self.mic_button.configure(state=tk.NORMAL)
        self.input_entry.configure(state=tk.NORMAL)
        self.input_entry.focus_set()
        self._update_interface_status()

    def _render_microphone_text(self, result: dict):
        if result.get("success"):
            recognized_text = str(result.get("text", "")).strip()
            if recognized_text:
                self._set_input_text(recognized_text)
                self.status_var.set("마이크 인식 완료. 채팅으로 전송합니다.")
                self._start_user_turn(recognized_text, user_label="Mic")
                return
            self._append_chat("error", "Mic 오류: 인식된 텍스트가 없습니다.")
            self.status_var.set("마이크 인식 실패")
        else:
            self._append_chat("error", f"Mic 오류: {result.get('error', 'unknown')}")
            self.status_var.set("마이크 인식 실패")

        self.send_button.configure(state=tk.NORMAL)
        self.mic_button.configure(state=tk.NORMAL)
        self.input_entry.configure(state=tk.NORMAL)
        self.input_entry.focus_set()
        self._update_interface_status()

    def _render_ai_voice_result(self, result: dict):
        if self._image:
            self._image.set_speaking(False)

        if result.get("success"):
            self._append_chat("assistant", f"AI Voice: {result.get('text', '')}")
            self.status_var.set(f"AI 보이스 완료 / {result.get('elapsed', 0)}초")
        else:
            self._append_chat("error", f"AI Voice 오류: {result.get('error', 'unknown')}")
            self.status_var.set("AI 보이스 오류")

        self.ai_voice_button.configure(state=tk.NORMAL)
        self.input_entry.configure(state=tk.NORMAL)
        self.input_entry.focus_set()
        self._update_interface_status()

    def _render_error(self, error_message: str):
        if self._image:
            self._image.set_speaking(False)

        self._append_chat("error", f"AI 오류: {error_message}")
        self.status_var.set("오류 발생. 로그를 확인하세요.")
        self.send_button.configure(state=tk.NORMAL)
        self.mic_button.configure(state=tk.NORMAL)
        self.ai_voice_button.configure(state=tk.NORMAL)
        self.input_entry.configure(state=tk.NORMAL)
        self.input_entry.focus_set()
        self._update_interface_status()

    def _append_chat(self, tag: str, text: str):
        self.chat_log.configure(state=tk.NORMAL)
        self.chat_log.insert(tk.END, text + "\n\n", tag)
        self.chat_log.configure(state=tk.DISABLED)
        self.chat_log.see(tk.END)

    def _get_input_text(self) -> str:
        return self.input_entry.get("1.0", tk.END).rstrip("\n")

    def _set_input_text(self, text: str):
        self.input_entry.configure(state=tk.NORMAL)
        self.input_entry.delete("1.0", tk.END)
        self.input_entry.insert("1.0", text)

    def _clear_input_text(self):
        self.input_entry.configure(state=tk.NORMAL)
        self.input_entry.delete("1.0", tk.END)

    def _shutdown_engine(self):
        self._stop_camera_preview()
        if self._image is not None:
            try:
                self._image.stop()
            except Exception:
                pass
        if self._interface is not None:
            try:
                self._interface.shutdown()
            except Exception:
                pass
        if self._memory is not None:
            try:
                self._memory.sql.close()
            except Exception:
                pass

        self._engine = None
        self._dialogue = None
        self._image = None
        self._memory = None
        self._interface = None

    def _handle_close(self):
        self._shutdown_engine()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def launch_desktop_app(engine_factory: Callable[[AppSettings], MainEngine],
                       initial_settings: AppSettings):
    app = WinAIDesktopApp(engine_factory=engine_factory,
                         initial_settings=initial_settings)
    app.run()