# WinAI

Windows 데스크톱 UI에서 로컬 LLM, 메모리 DB, 음성/카메라/시각화 모듈을 묶어 실행하는 AI 앱입니다.

이 저장소 자체가 HTTP 서버를 띄우는 구조는 아니고, 로컬 Ollama 서버에 연결하는 데스크톱 애플리케이션입니다. 엔트리 포인트는 `main.py`이며 기본 실행은 Tkinter 기반 GUI, 옵션으로 콘솔 모드도 지원합니다.

## 현재 확인한 실행 상태

- Ollama 서버 `http://localhost:11434` 응답 확인
- `qwen2.5:7b` 모델 설치 확인
- `http://localhost:11435` 는 현재 응답하지 않음
- 기본 실행 스크립트 `run.bat` 는 `11434` 와 `qwen2.5:7b` 를 사용

## 주요 구성

- `main.py`: 앱 엔트리 포인트, GUI/콘솔 모드 선택
- `win_app.py`: Windows 데스크톱 UI
- `llm_connector.py`: Ollama 호환 `/api/chat`, `/api/tags` 연결
- `memory_engine.py`: SQLite 기반 메모리 저장소 (`memory.db`)
- `dialogue_engine.py`: 입력 분류, 감정 추출, 메모리/검색/LLM 연결
- `interface_module.py`: 카메라, 마이크, TTS, AI 음성 인터페이스
- `image_engine.py`: 오디오 반응형 시각화

## 요구 사항

- Windows
- Python 가상환경 `.venv`
- 로컬 Ollama 실행 중
- 기본 모델: `qwen2.5:7b`

`requirements.txt`

- `numpy`
- `opencv-python`
- `pygame`
- `PyOpenGL`
- `PyOpenGL_accelerate`
- `pyttsx3`
- `requests`
- `sounddevice`
- `SpeechRecognition`

## 설치

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Ollama 서버도 먼저 켜져 있어야 합니다.

예시:

```powershell
ollama serve
ollama list
```

## 실행

기본 GUI 실행:

```powershell
.\run.bat
```

또는 직접 실행:

```powershell
.\.venv\Scripts\python.exe main.py
```

콘솔 모드 실행:

```powershell
.\.venv\Scripts\python.exe main.py --console
```

## 설정

`app_settings.py` 기준 기본값:

- `WINAI_LLM_URL=http://localhost:11434`
- `WINAI_LLM_MODEL=qwen2.5:7b`
- `WINAI_DB_PATH=memory.db`

실행 시 인자로도 덮어쓸 수 있습니다.

```powershell
.\.venv\Scripts\python.exe main.py --llm-url http://localhost:11434 --llm-model qwen2.5:7b --db-path memory.db
```

참고:

- `llm_connector.py` 는 기본 URL 접속 실패 시 `11434`, `11435` 후보 포트를 다시 확인하는 로직이 있습니다.
- 현재 로컬 확인 기준 실제 응답 포트는 `11434` 입니다.

## 동작 방식 요약

1. `main.py` 가 `MainEngine`, `MemoryEngine`, `LLMConnector`, `DialogueEngine`, `ImageEngine`, `InterfaceModule` 을 조립합니다.
2. GUI 모드에서는 `win_app.py` 가 엔진 상태, 대화, 카메라 미리보기, 음성 기능을 보여줍니다.
3. 대화 입력은 `dialogue_engine.py` 에서 의도/감정을 분류하고 메모리 컨텍스트를 수집한 뒤 LLM으로 전달됩니다.
4. 메모리는 `memory.db` 에 SQLite로 저장됩니다.

## 빌드

`build_windows.ps1` 는 PyInstaller로 실행 파일을 만듭니다.

```powershell
.\build_windows.ps1
```

출력:

```text
.\dist\WinAI\WinAI.exe
```

## 주의 사항

- 마이크 기능은 `sounddevice`, `SpeechRecognition` 설치와 로컬 오디오 장치 상태에 영향을 받습니다.
- 카메라 기능은 `opencv-python` 과 사용 가능한 카메라 장치가 필요합니다.
- TTS는 `pyttsx3` 기반입니다.
- 시각화는 OpenGL 관련 패키지와 환경에 따라 동작 여부가 달라질 수 있습니다.

## 문제 해결

Ollama 연결이 안 될 때:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

모델이 없으면:

```powershell
ollama pull qwen2.5:7b
```

가상환경으로 실행이 안 되면 `run.bat` 안의 Python 경로가 실제 `.venv` 위치와 맞는지 확인하세요.
