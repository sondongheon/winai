"""
Unified interface module for camera, microphone, TTS, and AI voice features.
"""

from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from runtime_logging import debug_log


def _optional_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


@dataclass
class DeviceState:
    name: str
    available: bool = False
    active: bool = False
    last_error: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class CameraInterface:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.cv2 = _optional_import("cv2")
        self.state = DeviceState(
            name="camera",
            available=self.cv2 is not None,
            last_error="" if self.cv2 else "OpenCV not installed",
        )
        self._capture: Any | None = None

    def start(self, camera_index: int = 0) -> bool:
        if self.cv2 is None:
            return False
        if self._capture is None:
            capture = self.cv2.VideoCapture(camera_index)
            if not capture.isOpened():
                self.state.last_error = f"Camera index {camera_index} unavailable"
                capture.release()
                return False
            self._capture = capture
        self.state.active = True
        self.state.details = {"camera_index": camera_index}
        debug_log(self.verbose, f"[InterfaceModule] camera connected: {camera_index}")
        return True

    def read_frame(self) -> Any | None:
        if self._capture is None:
            return None
        ok, frame = self._capture.read()
        if not ok:
            self.state.last_error = "Camera frame read failed"
            return None
        return frame

    def stop(self):
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self.state.active = False


class MicrophoneInterface:
    def __init__(self, audio_source: Any | None = None, verbose: bool = True):
        self.verbose = verbose
        self.audio_source = audio_source
        self.numpy = _optional_import("numpy")
        self.sounddevice = _optional_import("sounddevice")
        self.speech_recognition = _optional_import("speech_recognition")
        self._recognizer = self.speech_recognition.Recognizer() if self.speech_recognition else None
        self.state = DeviceState(
            name="microphone",
            available=audio_source is not None or self.sounddevice is not None,
            last_error="" if (audio_source is not None or self.sounddevice is not None) else "sounddevice not installed",
        )

    def connect(self) -> bool:
        if self.audio_source is not None:
            self.state.active = True
            self.state.details = {"source": getattr(self.audio_source, "source", "engine-audio")}
            return True
        if self.sounddevice is None:
            return False
        self.state.active = True
        self.state.details = {"source": "sounddevice"}
        return True

    def snapshot(self) -> dict[str, Any]:
        if self.audio_source is not None:
            return {
                "rms": getattr(self.audio_source, "rms", 0.0),
                "bands": list(getattr(self.audio_source, "band_levels", [])),
                "source": getattr(self.audio_source, "source", "unknown"),
            }
        return {"rms": 0.0, "bands": [], "source": self.state.details.get("source", "none")}

    def transcribe(self,
                   duration_sec: float = 4.0,
                   sample_rate: int = 16000,
                   language: str = "ko-KR") -> dict[str, Any]:
        sounddevice = self.sounddevice
        numpy_module = self.numpy
        speech_recognition = self.speech_recognition
        recognizer = self._recognizer

        if sounddevice is None:
            return {"success": False, "text": "", "error": "sounddevice not installed"}
        if numpy_module is None:
            return {"success": False, "text": "", "error": "numpy not installed"}
        if speech_recognition is None or recognizer is None:
            return {"success": False, "text": "", "error": "SpeechRecognition not installed"}

        frames = max(int(duration_sec * sample_rate), 1)

        try:
            self.state.active = True
            self.state.details["source"] = "sounddevice-transcribe"
            recording = sounddevice.rec(
                frames,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
            )
            sounddevice.wait()
            normalized = numpy_module.clip(recording.reshape(-1), -1.0, 1.0)
            pcm_bytes = (normalized * 32767).astype("int16").tobytes()
            audio_data = speech_recognition.AudioData(pcm_bytes, sample_rate, 2)
            text = recognizer.recognize_google(audio_data, language=language).strip()
            if not text:
                return {"success": False, "text": "", "error": "음성을 텍스트로 변환하지 못했습니다."}
            return {"success": True, "text": text, "error": ""}
        except speech_recognition.UnknownValueError:
            return {"success": False, "text": "", "error": "음성을 인식하지 못했습니다."}
        except speech_recognition.RequestError as error:
            return {"success": False, "text": "", "error": f"음성 인식 서비스 오류: {error}"}
        except Exception as error:
            self.state.last_error = str(error)
            return {"success": False, "text": "", "error": str(error)}

    def disconnect(self):
        self.state.active = False


class TTSInterface:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.pyttsx3 = _optional_import("pyttsx3")
        self._engine: Any | None = None
        self.state = DeviceState(
            name="tts",
            available=self.pyttsx3 is not None,
            last_error="" if self.pyttsx3 else "pyttsx3 not installed",
        )

    def connect(self) -> bool:
        if self.pyttsx3 is None:
            return False
        if self._engine is None:
            self._engine = self.pyttsx3.init()
        self.state.active = True
        return True

    def speak(self, text: str, async_mode: bool = True) -> bool:
        if not text:
            return False
        if not self.connect():
            return False

        engine = self._engine
        if engine is None:
            return False

        def runner():
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as error:
                self.state.last_error = str(error)

        if async_mode:
            threading.Thread(target=runner, daemon=True).start()
        else:
            runner()
        return True

    def disconnect(self):
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception as error:
                self.state.last_error = str(error)
        self.state.active = False

    def stop(self):
        if self._engine is None:
            return False
        try:
            self._engine.stop()
            self.state.active = False
            return True
        except Exception as error:
            self.state.last_error = str(error)
            return False


class AIVoiceInterface:
    def __init__(self,
                 llm_connector: Any | None = None,
                 tts_interface: TTSInterface | None = None,
                 verbose: bool = True):
        self.verbose = verbose
        self.llm = llm_connector
        self.tts = tts_interface
        self.state = DeviceState(
            name="ai_voice",
            available=llm_connector is not None,
            last_error="" if llm_connector is not None else "LLM connector missing",
        )

    def attach(self, llm_connector: Any | None = None, tts_interface: TTSInterface | None = None):
        if llm_connector is not None:
            self.llm = llm_connector
            self.state.available = True
            self.state.last_error = ""
        if tts_interface is not None:
            self.tts = tts_interface

    def chat(self,
             user_input: str,
             context: Optional[dict[str, Any]] = None,
             speak: bool = False) -> dict[str, Any]:
        if self.llm is None:
            return {"success": False, "text": "", "error": "LLM connector missing"}

        response = self.llm.chat(user_input, context=context)
        if speak and response.success and self.tts is not None:
            self.tts.speak(response.text, async_mode=True)
        return {
            "success": response.success,
            "text": response.text,
            "error": response.error,
            "model": response.model,
            "elapsed": response.elapsed,
        }


class InterfaceModule:
    def __init__(self,
                 dialogue_engine: Any | None = None,
                 llm_connector: Any | None = None,
                 image_engine: Any | None = None,
                 verbose: bool = True):
        self.verbose = verbose
        self.dialogue = dialogue_engine
        self.llm = llm_connector
        self.image = image_engine

        audio_source = getattr(image_engine, "_audio", None)
        self.camera = CameraInterface(verbose=verbose)
        self.microphone = MicrophoneInterface(audio_source=audio_source, verbose=verbose)
        self.tts = TTSInterface(verbose=verbose)
        self.ai_voice = AIVoiceInterface(llm_connector=llm_connector, tts_interface=self.tts, verbose=verbose)

        self.last_ai_response = ""
        debug_log(self.verbose, "[InterfaceModule] camera/microphone/tts/ai_voice initialized")

    def attach(self,
               dialogue_engine: Any | None = None,
               llm_connector: Any | None = None,
               image_engine: Any | None = None):
        if dialogue_engine is not None:
            self.dialogue = dialogue_engine
        if llm_connector is not None:
            self.llm = llm_connector
            self.ai_voice.attach(llm_connector=llm_connector)
        if image_engine is not None:
            self.image = image_engine
            self.microphone.audio_source = getattr(image_engine, "_audio", None)
            self.microphone.state.available = self.microphone.audio_source is not None or self.microphone.sounddevice is not None

    def connect_all(self):
        self.microphone.connect()
        self.tts.connect()

    def capture_camera_frame(self) -> Any | None:
        if not self.camera.state.active:
            self.camera.start()
        return self.camera.read_frame()

    def microphone_snapshot(self) -> dict[str, Any]:
        if not self.microphone.state.active:
            self.microphone.connect()
        return self.microphone.snapshot()

    def transcribe_microphone(self,
                              duration_sec: float = 4.0,
                              language: str = "ko-KR") -> dict[str, Any]:
        if not self.microphone.state.active:
            self.microphone.connect()
        return self.microphone.transcribe(duration_sec=duration_sec, language=language)

    def speak_text(self, text: str) -> bool:
        if self.image is not None:
            self.image.set_speaking(True, intensity=0.9)
        ok = self.tts.speak(text, async_mode=True)
        if self.image is not None:
            self.image.set_speaking(False)
        return ok

    def stop_tts(self) -> bool:
        if self.image is not None:
            self.image.set_speaking(False)
        return self.tts.stop()

    def ask_ai_voice(self,
                     user_input: str,
                     context: Optional[dict[str, Any]] = None,
                     speak: bool = True) -> dict[str, Any]:
        if self.image is not None:
            self.image.set_speaking(True, intensity=1.0)
        result = self.ai_voice.chat(user_input, context=context, speak=speak)
        self.last_ai_response = result.get("text", "")
        if self.image is not None:
            self.image.set_speaking(False)
        return result

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "camera": self.camera.state.__dict__.copy(),
            "microphone": self.microphone.state.__dict__.copy(),
            "tts": self.tts.state.__dict__.copy(),
            "ai_voice": self.ai_voice.state.__dict__.copy(),
            "last_ai_response": self.last_ai_response,
        }

    def handle(self, event: Any):
        event_type = event.etype
        payload = event.payload

        if event_type == "INTERFACE_CAMERA_START":
            self.camera.start(payload.get("camera_index", 0))
        elif event_type == "INTERFACE_CAMERA_STOP":
            self.camera.stop()
        elif event_type == "INTERFACE_TTS_SPEAK":
            self.speak_text(payload.get("text", ""))
        elif event_type == "INTERFACE_TTS_STOP":
            self.stop_tts()
        elif event_type == "INTERFACE_AI_VOICE":
            self.ask_ai_voice(
                payload.get("input", ""),
                context=payload.get("context"),
                speak=payload.get("speak", True),
            )
        elif event_type == "INTERFACE_STATUS":
            callback = payload.get("callback")
            if callback:
                callback(self.status_snapshot())

    def shutdown(self):
        self.camera.stop()
        self.microphone.disconnect()
        self.tts.disconnect()
