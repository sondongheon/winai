"""
main.py
Windows desktop entry point and console fallback.
"""

from __future__ import annotations

import argparse

from app_settings import AppSettings
from main_engine import MainEngine, Event
from dialogue_engine import DialogueEngine
from image_engine import ImageEngine, OutputMode
from interface_module import InterfaceModule
from internet_search import InternetSearchEngine
from llm_connector import LLMConnector
from memory_engine import MemoryEngine
from runtime_logging import debug_log
from win_app import launch_desktop_app


def build_system(
    db_path: str = "memory.db",
    start_image: bool = True,
    llm_url: str | None = None,
    llm_model: str | None = None,
    verbose: bool = True,
) -> MainEngine:
    """시스템 초기화 및 모듈 연결"""

    # 1. 엔진 생성
    engine = MainEngine(verbose=verbose)
    memory = MemoryEngine(db_path=db_path, verbose=verbose)
    llm = LLMConnector(url=llm_url, model=llm_model, verbose=verbose)
    search = InternetSearchEngine(verbose=verbose)
    dialogue = DialogueEngine(main_engine=engine, verbose=verbose)
    image = ImageEngine(mode=OutputMode.WAVE_GL, verbose=verbose)
    interface = InterfaceModule(
        dialogue_engine=dialogue,
        llm_connector=llm,
        image_engine=image,
        verbose=verbose,
    )

    # 2. 메인엔진에 메모리엔진 등록 + 직접 참조 연결
    engine.connect_memory_engine(memory)
    engine.connect_llm_connector(llm)
    dialogue.attach(memory_engine=engine.memory_engine,
                    llm_connector=engine.llm,
                    search_engine=search)
    engine.connect_dialogue_engine(dialogue)
    engine.connect_image_engine(image)
    engine.register("interface_module", interface)
    engine.interface = interface
    if start_image:
        image.start()
    interface.connect_all()

    debug_log(verbose, "[System] 메인엔진 ↔ 메모리엔진 ↔ LLM ↔ Dialogue ↔ Image 연결 완료")
    return engine


def build_system_from_settings(settings: AppSettings,
                               start_image: bool = True,
                               verbose: bool = True) -> MainEngine:
    return build_system(
        db_path=settings.db_path,
        start_image=start_image,
        llm_url=settings.llm_url,
        llm_model=settings.llm_model,
        verbose=verbose,
    )


def initialize_runtime_state(engine: MainEngine):
    memory = engine.memory_engine
    dialogue = engine.dialogue
    if memory is None:
        raise RuntimeError("MemoryEngine 연결이 완료되지 않았습니다.")
    if dialogue is None:
        raise RuntimeError("DialogueEngine 연결이 완료되지 않았습니다.")

    # ── 연결 확인: 메모리 읽기/쓰기 테스트 ──

    # 메인엔진 → 이벤트 발행 → 메모리엔진 처리
    engine.emit(Event(
        source="main_engine",
        target="memory_engine",
        etype="MEMORY_SAVE_FACT",
        payload={
            "key": "system_ready",
            "value": True,
            "qstate": "TRUE",
            "confidence": 1.0
        }
    ))
    engine.tick()

    engine.emit(Event(
        source="main_engine",
        target="memory_engine",
        etype="CACHE_SET",
        payload={
            "key": "system_status",
            "value": "IDLE",
            "slot": "focus",
            "qstate": "TRUE"
        }
    ))
    engine.tick()

    # 컨텍스트 수집 확인
    ctx = memory.collect_context()
    debug_log(engine.verbose, f"\n[연결 확인] 캐시 활성 셀: {list(ctx['cache_snapshot'].keys())}")
    fact = memory.sql.get_fact("system_ready")
    debug_log(engine.verbose, f"[연결 확인] system_ready = {fact['value']} ({fact['qstate']})")

    return memory, dialogue


def run_console_app(settings: AppSettings):
    engine = build_system_from_settings(settings, verbose=True)
    memory, dialogue = initialize_runtime_state(engine)

    # 전체 상태 출력
    engine.status()
    memory.status()

    dialogue.on_response = lambda r: print(f"AI: {r.llm_response}")

    print("[System] 콘솔 모드 시작 — 종료하려면 'exit' 또는 'quit' 입력\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("[System] 콘솔 모드를 종료합니다.")
            break
        if not user_input:
            continue
        dialogue.process(user_input)


def run_windows_app(settings: AppSettings):
    def factory(active_settings: AppSettings) -> MainEngine:
        engine = build_system_from_settings(active_settings, start_image=False, verbose=False)
        initialize_runtime_state(engine)
        return engine

    launch_desktop_app(factory, settings)


def main():
    parser = argparse.ArgumentParser(description="Run WinAI as a Windows desktop app.")
    parser.add_argument(
        "--console",
        action="store_true",
        help="Run the legacy console chat loop instead of the desktop app.",
    )
    parser.add_argument(
        "--llm-url",
        default=None,
        help="Override the Ollama-compatible LLM base URL.",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="Override the model name used for chat.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override the SQLite database path used by the memory engine.",
    )
    args = parser.parse_args()
    settings = AppSettings.from_sources(
        llm_url=args.llm_url,
        llm_model=args.llm_model,
        db_path=args.db_path,
    )

    if args.console:
        run_console_app(settings)
        return

    run_windows_app(settings)


if __name__ == "__main__":
    main()
