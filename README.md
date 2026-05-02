# WinAI

WinAI는 Windows 데스크톱 환경에서 로컬 LLM, 메모리 DB, 음성 입출력, 카메라 프리뷰, 시각화 모듈을 함께 실행하는 AI 앱입니다.

이 저장소는 자체 웹 서버를 띄우는 프로젝트가 아니라, 로컬 Ollama 서버에 연결하는 Windows 데스크톱 애플리케이션입니다. 엔트리 포인트는 `main.py`이며, 기본 실행 모드는 Tkinter 기반 GUI입니다. 필요하면 콘솔 모드도 사용할 수 있습니다.

## 현재 기준 구성

- Ollama 기본 URL: `http://localhost:11434`
- 기본 모델: `qwen2.5:7b`
- 메모리 DB: `memory.db`
- 실행 스크립트: `run.bat`
- 앱 엔트리 포인트: `main.py`

## 주요 파일

- `main.py`: 전체 시스템 조립, GUI/콘솔 모드 진입점
- `win_app.py`: Windows 데스크톱 UI
- `llm_connector.py`: Ollama 호환 `/api/chat`, `/api/tags` 연결
- `memory_engine.py`: SQLite 기반 메모리 저장소
- `dialogue_engine.py`: 입력 분류, 감정 추출, 메모리/LLM 연결
- `interface_module.py`: 카메라, 마이크, TTS, AI 보이스 인터페이스
- `image_engine.py`: 오디오 반응형 시각화
- `app_settings.py`: 기본 URL, 모델, DB 경로 설정

## 요구 사항

- Windows
- Python 가상환경 `.venv`
- 로컬 Ollama 실행 중
- `qwen2.5:7b` 모델 설치

`requirements.txt`에 포함된 주요 패키지:

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

Ollama 서버도 먼저 실행되어 있어야 합니다.

```powershell
ollama serve
ollama list
```

## 실행

기본 GUI 실행:

```powershell
.\run.bat
```

직접 실행:

```powershell
.\.venv\Scripts\python.exe main.py
```

콘솔 모드 실행:

```powershell
.\.venv\Scripts\python.exe main.py --console
```

## 설정

기본 설정값은 `app_settings.py`에 있습니다.

- `WINAI_LLM_URL=http://localhost:11434`
- `WINAI_LLM_MODEL=qwen2.5:7b`
- `WINAI_DB_PATH=memory.db`

실행 인자로도 덮어쓸 수 있습니다.

```powershell
.\.venv\Scripts\python.exe main.py --llm-url http://localhost:11434 --llm-model qwen2.5:7b --db-path memory.db
```

`llm_connector.py`는 설정된 Ollama URL만 사용하며, 현재 프로젝트 기준 포트는 `11434`로 통일되어 있습니다.

## 동작 방식

1. `main.py`가 `MainEngine`, `MemoryEngine`, `LLMConnector`, `DialogueEngine`, `ImageEngine`, `InterfaceModule`을 조립합니다.
2. GUI 모드에서는 `win_app.py`가 대화창, 연결 상태, 카메라 프리뷰, 음성 기능, 시각화 상태를 보여줍니다.
3. 사용자 입력은 `dialogue_engine.py`에서 의도와 감정을 분류한 뒤 메모리 컨텍스트와 함께 LLM으로 전달됩니다.
4. 대화와 학습 정보는 `memory.db`에 SQLite 형태로 저장됩니다.

## 빌드

`build_windows.ps1`는 PyInstaller 기반으로 실행 파일을 생성합니다.

```powershell
.\build_windows.ps1
```

출력 경로:

```text
.\dist\WinAI\WinAI.exe
```

## 주의 사항

- 마이크 기능은 `sounddevice`, `SpeechRecognition`, 로컬 오디오 장치 상태에 따라 동작이 달라질 수 있습니다.
- 카메라 기능은 `opencv-python`과 사용 가능한 카메라 장치가 필요합니다.
- TTS는 `pyttsx3` 기반입니다.
- 시각화는 OpenGL 환경에 따라 임베드 렌더러 또는 대체 표시 방식으로 동작할 수 있습니다.
- 실행 중 `memory.db` 파일이 생성되며, 대화/기억 데이터가 로컬에 저장됩니다.

## 문제 해결

Ollama 연결 확인:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

모델이 없으면:

```powershell
ollama pull qwen2.5:7b
```

가상환경 실행이 안 되면 `run.bat`의 Python 경로가 실제 `.venv` 위치와 일치하는지 확인하세요.

## 라이선스

이 프로젝트는 `PolyForm Noncommercial 1.0.0`을 따릅니다.

- 개인용, 연구용, 취미용, 기타 비상업적 사용 허용
- 상업적 사용 금지
- 자세한 조건은 [LICENSE](/c:/Users/sondh/winai/LICENSE) 파일 참고
