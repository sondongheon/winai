"""
IMAGE ENGINE
─────────────────────────────────────────────
출력 모드 선택 가능
  WAVE_GL   : 기본 — 음성파동 + 수학함수 + OpenGL
  SPRITE    : 추후 — 스프라이트 2D (미구현 슬롯)
  GAME_CHAR : 추후 — 게임형 캐릭터 (미구현 슬롯)
"""

import math
import importlib
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import numpy as np

from runtime_logging import debug_log


Color = tuple[float, float, float]


def _import_module(name: str) -> Any:
    return importlib.import_module(name)


def _lerp_color(current: Color, target: Color, speed: float) -> Color:
    return (
        current[0] + (target[0] - current[0]) * speed,
        current[1] + (target[1] - current[1]) * speed,
        current[2] + (target[2] - current[2]) * speed,
    )


class OutputMode(Enum):
    WAVE_GL = "WAVE_GL"
    SPRITE = "SPRITE"
    GAME_CHAR = "GAME_CHAR"


@dataclass
class VisualParams:
    color_primary: Color = (0.4, 0.8, 1.0)
    color_secondary: Color = (0.2, 0.4, 0.8)
    color_glow: Color = (0.1, 0.3, 0.6)
    base_amplitude: float = 0.3
    frequency_a: float = 3.0
    frequency_b: float = 2.0
    phase_shift: float = 0.0
    noise_scale: float = 0.02
    noise_speed: float = 1.0
    wave_sensitivity: float = 1.0
    wave_layers: int = 3


EMOTION_PRESETS: dict[str, VisualParams] = {
    "HAPPY": VisualParams(
        color_primary=(1.0, 0.85, 0.2),
        color_secondary=(1.0, 0.5, 0.1),
        color_glow=(0.8, 0.3, 0.0),
        base_amplitude=0.38,
        frequency_a=3.0,
        frequency_b=2.0,
        noise_scale=0.03,
        noise_speed=1.5,
        wave_sensitivity=1.3,
    ),
    "SAD": VisualParams(
        color_primary=(0.3, 0.4, 0.9),
        color_secondary=(0.1, 0.2, 0.6),
        color_glow=(0.05, 0.1, 0.4),
        base_amplitude=0.22,
        frequency_a=2.0,
        frequency_b=3.0,
        noise_scale=0.01,
        noise_speed=0.5,
        wave_sensitivity=0.7,
    ),
    "ANGRY": VisualParams(
        color_primary=(1.0, 0.15, 0.1),
        color_secondary=(0.8, 0.0, 0.0),
        color_glow=(0.5, 0.0, 0.0),
        base_amplitude=0.42,
        frequency_a=5.0,
        frequency_b=4.0,
        noise_scale=0.06,
        noise_speed=3.0,
        wave_sensitivity=1.8,
    ),
    "ANXIOUS": VisualParams(
        color_primary=(0.9, 0.6, 0.1),
        color_secondary=(0.7, 0.3, 0.0),
        color_glow=(0.4, 0.2, 0.0),
        base_amplitude=0.28,
        frequency_a=4.0,
        frequency_b=5.0,
        noise_scale=0.05,
        noise_speed=2.5,
        wave_sensitivity=1.5,
    ),
    "CURIOUS": VisualParams(
        color_primary=(0.5, 1.0, 0.7),
        color_secondary=(0.2, 0.8, 0.5),
        color_glow=(0.1, 0.5, 0.3),
        base_amplitude=0.33,
        frequency_a=3.0,
        frequency_b=4.0,
        noise_scale=0.025,
        noise_speed=1.2,
        wave_sensitivity=1.1,
    ),
    "TIRED": VisualParams(
        color_primary=(0.5, 0.5, 0.6),
        color_secondary=(0.3, 0.3, 0.4),
        color_glow=(0.1, 0.1, 0.2),
        base_amplitude=0.18,
        frequency_a=1.5,
        frequency_b=2.0,
        noise_scale=0.008,
        noise_speed=0.3,
        wave_sensitivity=0.5,
    ),
    "NEUTRAL": VisualParams(),
}


class AudioCapture:
    CHUNK = 1024
    RATE = 22050
    BANDS = 8

    def __init__(self):
        self.band_levels = np.zeros(self.BANDS)
        self.rms = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.verbose = True
        self.source = "microphone"

    def start(self):
        try:
            _import_module("sounddevice")
            self._running = True
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            self.source = "microphone"
            debug_log(self.verbose, "[AudioCapture] 마이크 캡처 시작")
        except Exception as error:
            self.source = "simulation"
            debug_log(self.verbose, f"[AudioCapture] 시작 실패: {error} — 시뮬레이션 모드")
            self._start_simulation()

    def _capture_loop(self):
        sd = _import_module("sounddevice")

        def callback(indata, frames, time_info, status):
            samples = indata[:, 0]
            self.rms = float(np.sqrt(np.mean(samples ** 2)))
            fft_vals = np.abs(np.fft.rfft(samples))
            band_size = len(fft_vals) // self.BANDS
            for i in range(self.BANDS):
                self.band_levels[i] = np.mean(
                    fft_vals[i * band_size:(i + 1) * band_size]
                ) / 100.0

        with sd.InputStream(channels=1, samplerate=self.RATE,
                            blocksize=self.CHUNK, callback=callback):
            while self._running:
                time.sleep(0.01)

    def _start_simulation(self):
        def sim_loop():
            time_pos = 0.0
            while True:
                time_pos += 0.05
                self.rms = abs(math.sin(time_pos * 0.7)) * 0.1
                for index in range(self.BANDS):
                    self.band_levels[index] = (
                        abs(math.sin(time_pos * (index + 1) * 0.3)) * 0.3
                        + np.random.uniform(0, 0.05)
                    )
                time.sleep(0.03)

        threading.Thread(target=sim_loop, daemon=True).start()

    def stop(self):
        self._running = False


class WaveGLRenderer:
    def __init__(self,
                 audio: AudioCapture,
                 width: int = 400,
                 height: int = 400,
                 parent_window_id: int | None = None):
        self.audio = audio
        self.width = width
        self.height = height
        self.parent_window_id = parent_window_id
        self.params = VisualParams()
        self._target = VisualParams()
        self._t = 0.0
        self._speak_intensity = 0.0
        self._running = False

    def _lerp_params(self, speed: float = 0.05):
        current, target = self.params, self._target

        def lerp(start: float, end: float) -> float:
            return start + (end - start) * speed

        current.base_amplitude = lerp(current.base_amplitude, target.base_amplitude)
        current.frequency_a = lerp(current.frequency_a, target.frequency_a)
        current.frequency_b = lerp(current.frequency_b, target.frequency_b)
        current.noise_scale = lerp(current.noise_scale, target.noise_scale)
        current.noise_speed = lerp(current.noise_speed, target.noise_speed)
        current.wave_sensitivity = lerp(current.wave_sensitivity, target.wave_sensitivity)
        current.color_primary = _lerp_color(current.color_primary, target.color_primary, speed)
        current.color_secondary = _lerp_color(current.color_secondary, target.color_secondary, speed)

    def set_emotion(self, emotion: str):
        self._target = EMOTION_PRESETS.get(emotion, VisualParams())
        print(f"[WaveGL] 감정 변경: {emotion}")

    def set_speaking(self, is_speaking: bool, intensity: float = 1.0):
        self._speak_intensity = intensity if is_speaking else 0.0

    def _lissajous_point(self, time_value: float) -> tuple[float, float]:
        params = self.params
        x_pos = params.base_amplitude * math.sin(params.frequency_a * time_value + params.phase_shift)
        y_pos = params.base_amplitude * math.sin(params.frequency_b * time_value)
        return x_pos, y_pos

    def _noise_offset(self, seed: float) -> float:
        params = self.params
        return (
            math.sin(seed * 1.7 + self._t * params.noise_speed)
            * math.cos(seed * 2.3 + self._t * params.noise_speed * 0.7)
            * params.noise_scale
        )

    def _wave_offset(self, point_index: int, band_index: int) -> float:
        del point_index
        level = self.audio.band_levels[band_index % self.audio.BANDS]
        return level * self.params.wave_sensitivity * 0.15

    def _draw_base_form(self):
        gl = _import_module("OpenGL.GL")

        steps = 360
        red, green, blue = self.params.color_primary
        gl.glColor4f(red, green, blue, 0.9)
        gl.glBegin(gl.GL_LINE_LOOP)
        for index in range(steps):
            time_value = (index / steps) * 2 * math.pi
            x_pos, y_pos = self._lissajous_point(time_value)
            x_pos += self._noise_offset(index * 0.1)
            y_pos += self._noise_offset(index * 0.1 + 100)
            gl.glVertex2f(x_pos, y_pos)
        gl.glEnd()

    def _draw_wave_layers(self):
        gl = _import_module("OpenGL.GL")

        for layer in range(self.params.wave_layers):
            alpha = 0.6 - layer * 0.15
            scale = 1.0 + layer * 0.12
            red, green, blue = self.params.color_secondary
            gl.glColor4f(red, green, blue, alpha)
            gl.glBegin(gl.GL_LINE_STRIP)
            steps = 256
            for index in range(steps + 1):
                time_value = (index / steps) * 2 * math.pi
                x_pos, y_pos = self._lissajous_point(time_value)
                x_pos *= scale
                y_pos *= scale
                wave = self._wave_offset(index, (index * self.audio.BANDS // steps))
                speak = self._speak_intensity * 0.1 * math.sin(time_value * 8 + self._t * 5)
                x_pos += wave * math.cos(time_value) + speak
                y_pos += wave * math.sin(time_value) + speak
                gl.glVertex2f(x_pos, y_pos)
            gl.glEnd()

    def _draw_glow(self):
        gl = _import_module("OpenGL.GL")

        red, green, blue = self.params.color_glow
        gl.glColor4f(red, green, blue, 0.15 + self.audio.rms * 0.3)
        gl.glBegin(gl.GL_TRIANGLE_FAN)
        gl.glVertex2f(0, 0)
        steps = 60
        for index in range(steps + 1):
            time_value = (index / steps) * 2 * math.pi
            x_pos, y_pos = self._lissajous_point(time_value)
            gl.glVertex2f(x_pos * 0.8, y_pos * 0.8)
        gl.glEnd()

    def _draw_reaction_particles(self):
        gl = _import_module("OpenGL.GL")

        if self.audio.rms < 0.05:
            return
        gl.glPointSize(2.0)
        red, green, blue = self.params.color_primary
        gl.glColor4f(red, green, blue, self.audio.rms * 2)
        gl.glBegin(gl.GL_POINTS)
        for index in range(20):
            angle = (index / 20) * 2 * math.pi + self._t
            distance = 0.45 + self.audio.rms * 0.5
            gl.glVertex2f(
                math.cos(angle) * distance + self._noise_offset(index),
                math.sin(angle) * distance + self._noise_offset(index + 50),
            )
        gl.glEnd()

    def run(self):
        pygame = _import_module("pygame")
        gl = _import_module("OpenGL.GL")
        glu = _import_module("OpenGL.GLU")

        if self.parent_window_id is not None:
            os.environ["SDL_WINDOWID"] = str(self.parent_window_id)

        pygame.init()
        flags = pygame.OPENGL | pygame.DOUBLEBUF
        if self.parent_window_id is None:
            flags |= pygame.NOFRAME
        pygame.display.set_mode((self.width, self.height), flags)
        pygame.display.set_caption("AI")

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glLineWidth(1.5)
        gl.glViewport(0, 0, self.width, self.height)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        glu.gluOrtho2D(-1, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()

        clock = pygame.time.Clock()
        self.audio.start()
        print("[WaveGL] 렌더 루프 시작")

        self._running = True
        while self._running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._running = False

            self._t += 0.016
            self._lerp_params()

            gl.glClearColor(0.05, 0.05, 0.08, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

            self._draw_glow()
            self._draw_wave_layers()
            self._draw_base_form()
            self._draw_reaction_particles()

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()
        self.audio.stop()

    def stop(self):
        self._running = False


class CanvasRenderer:
    def __init__(self, audio: AudioCapture, canvas: Any):
        self.audio = audio
        self.canvas = canvas
        self.params = VisualParams()
        self._target = VisualParams()
        self._t = 0.0
        self._speak_intensity = 0.0
        self._running = False

    def set_emotion(self, emotion: str):
        self._target = EMOTION_PRESETS.get(emotion, VisualParams())

    def set_speaking(self, is_speaking: bool, intensity: float = 1.0):
        self._speak_intensity = intensity if is_speaking else 0.0

    def _lerp_params(self, speed: float = 0.08):
        current, target = self.params, self._target

        def lerp(start: float, end: float) -> float:
            return start + (end - start) * speed

        current.base_amplitude = lerp(current.base_amplitude, target.base_amplitude)
        current.frequency_a = lerp(current.frequency_a, target.frequency_a)
        current.frequency_b = lerp(current.frequency_b, target.frequency_b)
        current.noise_scale = lerp(current.noise_scale, target.noise_scale)
        current.noise_speed = lerp(current.noise_speed, target.noise_speed)
        current.wave_sensitivity = lerp(current.wave_sensitivity, target.wave_sensitivity)
        current.color_primary = _lerp_color(current.color_primary, target.color_primary, speed)
        current.color_secondary = _lerp_color(current.color_secondary, target.color_secondary, speed)
        current.color_glow = _lerp_color(current.color_glow, target.color_glow, speed)

    @staticmethod
    def _rgb(color: Color) -> str:
        return "#%02x%02x%02x" % tuple(max(0, min(255, int(channel * 255))) for channel in color)

    def start(self):
        self._running = True
        self.audio.start()
        self._tick()

    def stop(self):
        self._running = False
        self.audio.stop()

    def _tick(self):
        if not self._running:
            return

        width = max(self.canvas.winfo_width(), 240)
        height = max(self.canvas.winfo_height(), 180)
        center_x = width / 2
        center_y = height / 2

        self._t += 0.05
        self._lerp_params()
        self.canvas.delete("all")
        self.canvas.configure(bg="#020617", highlightthickness=0)

        glow_radius = min(width, height) * (0.24 + self.audio.rms * 0.9)
        for scale, alpha in ((1.4, 0.18), (1.1, 0.25), (0.8, 0.35)):
            radius = glow_radius * scale
            self.canvas.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                fill=self._rgb(self.params.color_glow),
                outline="",
                stipple="gray50" if alpha < 0.3 else "gray25",
            )

        line_points: list[float] = []
        bands = max(1, len(self.audio.band_levels))
        for index in range(72):
            phase = index / 71
            x_pos = phase * width
            band_level = self.audio.band_levels[index % bands]
            amplitude = height * (0.08 + self.params.base_amplitude * 0.4)
            wave = math.sin((phase * math.pi * self.params.frequency_a) + self._t * 2.5)
            detail = math.cos((phase * math.pi * self.params.frequency_b) - self._t * 1.7)
            speak = self._speak_intensity * math.sin(phase * math.pi * 12 + self._t * 7)
            y_offset = (wave + detail * 0.5 + speak * 0.8) * amplitude
            y_offset += band_level * height * 0.12 * self.params.wave_sensitivity
            y_pos = center_y + y_offset
            line_points.extend((x_pos, y_pos))

        self.canvas.create_line(
            *line_points,
            fill=self._rgb(self.params.color_secondary),
            width=3,
            smooth=True,
        )

        orb_radius = min(width, height) * (0.14 + self.audio.rms * 0.25)
        self.canvas.create_oval(
            center_x - orb_radius,
            center_y - orb_radius,
            center_x + orb_radius,
            center_y + orb_radius,
            fill=self._rgb(self.params.color_primary),
            outline="",
        )

        self.canvas.after(33, self._tick)


class ImageEngine:
    def __init__(self, mode: OutputMode = OutputMode.WAVE_GL, verbose: bool = True):
        self.verbose = verbose
        self.mode = mode
        self._audio = AudioCapture()
        self._audio.verbose = verbose
        self._renderer: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self.available = True
        self.last_error = ""
        self.render_backend = "none"
        debug_log(self.verbose, f"[ImageEngine] 초기화 — 모드: {mode.value}")

    def start(self,
              parent_window_id: int | None = None,
              width: int = 400,
              height: int = 400,
              tk_canvas: Any | None = None):
        if self.mode == OutputMode.WAVE_GL:
            try:
                _import_module("pygame")
                _import_module("OpenGL.GL")
                _import_module("OpenGL.GLU")
            except Exception as error:
                if tk_canvas is not None:
                    self._renderer = CanvasRenderer(self._audio, tk_canvas)
                    self._renderer.start()
                    self.available = True
                    self.last_error = f"OpenGL unavailable: {error}"
                    self.render_backend = "canvas"
                    debug_log(self.verbose, f"[ImageEngine] 캔버스 시각화 사용: {error}")
                    return True

                self.available = False
                self.last_error = str(error)
                self.render_backend = "disabled"
                debug_log(self.verbose, f"[ImageEngine] 시각화 비활성화: {error}")
                return False

            self._renderer = WaveGLRenderer(
                self._audio,
                width=width,
                height=height,
                parent_window_id=parent_window_id,
            )
            self._thread = threading.Thread(target=self._run_renderer, daemon=True)
            self._thread.start()
            self.available = True
            self.last_error = ""
            self.render_backend = "opengl"
            return True
        elif self.mode == OutputMode.SPRITE:
            debug_log(self.verbose, "[ImageEngine] SPRITE 모드 — 추후 구현")
        elif self.mode == OutputMode.GAME_CHAR:
            debug_log(self.verbose, "[ImageEngine] GAME_CHAR 모드 — 추후 구현")
        return False

    def _run_renderer(self):
        if self._renderer is None:
            return
        try:
            self._renderer.run()
        except Exception as error:
            debug_log(self.verbose, f"[ImageEngine] 렌더러 시작 실패: {error}")

    def set_emotion(self, emotion: str):
        if self._renderer:
            self._renderer.set_emotion(emotion)

    def set_speaking(self, is_speaking: bool, intensity: float = 1.0):
        if self._renderer:
            self._renderer.set_speaking(is_speaking, intensity)

    def stop(self):
        if self._renderer and hasattr(self._renderer, "stop"):
            self._renderer.stop()
        self._renderer = None

    def set_mode(self, mode: OutputMode):
        debug_log(self.verbose, f"[ImageEngine] 모드 변경: {self.mode.value} → {mode.value}")
        self.mode = mode

    def handle(self, event):
        event_type = event.etype
        payload = event.payload

        if event_type == "IMAGE_SET_EMOTION":
            self.set_emotion(payload.get("emotion", "NEUTRAL"))
        elif event_type == "IMAGE_SPEAKING":
            self.set_speaking(
                payload.get("is_speaking", False),
                payload.get("intensity", 1.0),
            )
        elif event_type == "IMAGE_SET_MODE":
            mode_str = payload.get("mode", "WAVE_GL")
            self.set_mode(OutputMode[mode_str])


if __name__ == "__main__":
    engine = ImageEngine(mode=OutputMode.WAVE_GL)
    engine.start()
