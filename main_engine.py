"""
MAIN ENGINE - 4진 논리 메모리 구조 기반
TRUE / FALSE / SUPER(중첩) / COEXIST(공존)
"""

import uuid
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional

from runtime_logging import debug_log


# ─────────────────────────────────────────
# 1. 4진 논리 타입 정의
# ─────────────────────────────────────────

class QVal(Enum):
    TRUE    = "TRUE"     # 확실히 참
    FALSE   = "FALSE"    # 확실히 거짓
    SUPER   = "SUPER"    # 중첩 (참+거짓 동시 가능)
    COEXIST = "COEXIST"  # 공존 (맥락 의존, 둘 다 유효)


# ─────────────────────────────────────────
# 2. 4진 메모리 셀 (기본 저장 단위)
# ─────────────────────────────────────────

@dataclass
class QCell:
    key:       str
    value:     Any
    qstate:    QVal         = QVal.SUPER     # 초기 상태는 중첩
    confidence: float       = 0.0            # 0.0 ~ 1.0
    context:   list[str]    = field(default_factory=list)  # 공존 맥락 태그
    timestamp: float        = field(default_factory=time.time)

    def resolve(self) -> str:
        """현재 상태를 사람이 읽을 수 있는 형태로 출력"""
        return (
            f"[{self.qstate.value}] {self.key} = {self.value} "
            f"(신뢰도: {self.confidence:.2f}) "
            f"맥락: {self.context if self.context else '없음'}"
        )


# ─────────────────────────────────────────
# 3. 4진 논리 판단 함수
# ─────────────────────────────────────────

class QJudge:
    """두 QCell 또는 값을 받아 4진 판단 반환"""

    @staticmethod
    def judge(a: QCell, b: QCell) -> QVal:
        # 둘 다 TRUE → TRUE
        if a.qstate == QVal.TRUE and b.qstate == QVal.TRUE:
            return QVal.TRUE
        # 둘 다 FALSE → FALSE
        if a.qstate == QVal.FALSE and b.qstate == QVal.FALSE:
            return QVal.FALSE
        # 한쪽 TRUE, 한쪽 FALSE → SUPER (중첩, 판단 보류)
        if {a.qstate, b.qstate} == {QVal.TRUE, QVal.FALSE}:
            return QVal.SUPER
        # 맥락이 다르면 COEXIST
        if a.context and b.context and set(a.context) != set(b.context):
            return QVal.COEXIST
        # 그 외 → SUPER
        return QVal.SUPER

    @staticmethod
    def collapse(cell: QCell, evidence: float) -> QVal:
        """
        증거값(evidence: -1.0 ~ 1.0)으로 중첩 상태 붕괴
        양수 → TRUE 방향, 음수 → FALSE 방향
        """
        if cell.qstate not in (QVal.SUPER, QVal.COEXIST):
            return cell.qstate  # 이미 확정된 상태

        threshold = 0.7
        if evidence >= threshold:
            return QVal.TRUE
        elif evidence <= -threshold:
            return QVal.FALSE
        else:
            return QVal.SUPER   # 아직 중첩 유지


# ─────────────────────────────────────────
# 4. 4진 메모리 저장소
# ─────────────────────────────────────────

class QMemory:
    """런타임 4진 메모리 (인메모리, 추후 메모리엔진 모듈과 연동)"""

    def __init__(self):
        self._store: dict[str, QCell] = {}

    def set(self, key: str, value: Any,
            qstate: QVal = QVal.SUPER,
            confidence: float = 0.5,
            context: Optional[list[str]] = None) -> QCell:
        cell = QCell(
            key=key,
            value=value,
            qstate=qstate,
            confidence=confidence,
            context=context or []
        )
        self._store[key] = cell
        return cell

    def get(self, key: str) -> Optional[QCell]:
        return self._store.get(key)

    def update_state(self, key: str, evidence: float) -> Optional[QVal]:
        """증거를 주입해서 상태 업데이트"""
        cell = self._store.get(key)
        if not cell:
            return None
        new_state = QJudge.collapse(cell, evidence)
        cell.qstate = new_state
        cell.confidence = abs(evidence)
        cell.timestamp = time.time()
        return new_state

    def dump(self):
        """전체 메모리 상태 출력"""
        print("\n── QMemory 상태 ──────────────────")
        for cell in self._store.values():
            print(" ", cell.resolve())
        print("──────────────────────────────────\n")


# ─────────────────────────────────────────
# 5. 이벤트 객체
# ─────────────────────────────────────────

@dataclass
class Event:
    source:   str
    target:   str
    etype:    str                            # 이벤트 타입
    payload:  dict      = field(default_factory=dict)
    priority: int       = 2                  # 1=긴급 2=일반 3=백그라운드
    event_id: str       = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float    = field(default_factory=time.time)


# ─────────────────────────────────────────
# 6. 메인엔진
# ─────────────────────────────────────────

class MainEngine:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.memory   = QMemory()
        self.memory_engine: Any | None = None
        self.llm: Any | None = None
        self.dialogue: Any | None = None
        self.image: Any | None = None
        self.interface: Any | None = None
        self.modules: dict[str, Any] = {}    # 연결된 모듈들
        self.event_queue: list[Event] = []
        self._running = False
        self.register("main_engine", self)
        debug_log(self.verbose, "[MainEngine] 초기화 완료 — 4진 논리 메모리 활성")

    # ── 모듈 등록 ──────────────────────────
    def register(self, name: str, module: Any):
        self.modules[name] = module
        debug_log(self.verbose, f"[MainEngine] 모듈 등록: {name}")

    def connect_memory_engine(self, memory_engine: Any,
                              module_name: str = "memory_engine") -> Any:
        """메모리엔진을 등록하고 메인엔진에 직접 참조를 노출한다."""
        self.register(module_name, memory_engine)
        self.memory_engine = memory_engine
        debug_log(self.verbose, "[MainEngine] 메모리엔진 연결 완료")
        return memory_engine

    def connect_llm_connector(self, llm_connector: Any,
                              module_name: str = "llm_connector") -> Any:
        """LLM 커넥터를 등록하고 메인엔진에 직접 참조를 노출한다."""
        self.register(module_name, llm_connector)
        self.llm = llm_connector
        debug_log(self.verbose, "[MainEngine] LLM 커넥터 연결 완료")
        return llm_connector

    def connect_dialogue_engine(self, dialogue_engine: Any,
                                module_name: str = "dialogue_engine") -> Any:
        """대화엔진을 등록하고 메인엔진에 직접 참조를 노출한다."""
        self.register(module_name, dialogue_engine)
        self.dialogue = dialogue_engine
        debug_log(self.verbose, "[MainEngine] 대화엔진 연결 완료")
        return dialogue_engine

    def connect_image_engine(self, image_engine: Any,
                             module_name: str = "image_engine") -> Any:
        """이미지엔진을 등록하고 메인엔진에 직접 참조를 노출한다."""
        self.register(module_name, image_engine)
        self.image = image_engine
        debug_log(self.verbose, "[MainEngine] 이미지엔진 연결 완료")
        return image_engine

    # ── 이벤트 발행 ────────────────────────
    def emit(self, event: Event):
        self.event_queue.append(event)
        self.event_queue.sort(key=lambda e: e.priority)  # 우선순위 정렬

    # ── 이벤트 처리 (1틱) ──────────────────
    def tick(self):
        if not self.event_queue:
            return

        event = self.event_queue.pop(0)
        debug_log(self.verbose, f"[MainEngine] 이벤트 처리: [{event.etype}] {event.source} → {event.target}")

        # 타겟 모듈로 디스패치
        target = self.modules.get(event.target)
        if target and hasattr(target, "handle"):
            target.handle(event)
        else:
            debug_log(self.verbose, f"  ※ 타겟 모듈 없음: {event.target} (큐 대기)")

    # ── 판단 출력 ──────────────────────────
    def judge_and_output(self, key: str, evidence: float) -> dict:
        """
        메모리의 특정 키에 증거를 주입하고 판단 결과 반환
        외부(대화판단엔진 등)에서 턴을 넘길 때 호출
        """
        new_state = self.memory.update_state(key, evidence)
        cell = self.memory.get(key)

        result = {
            "key":       key,
            "qstate":    new_state.value if new_state else "NOT_FOUND",
            "confidence": cell.confidence if cell else 0.0,
            "value":     cell.value if cell else None,
            "context":   cell.context if cell else [],
        }
        debug_log(self.verbose, f"[MainEngine] 판단 출력: {result}")
        return result

    def handle(self, event: Event):
        if event.etype == "TURN_COMPLETE":
            debug_log(self.verbose, f"[MainEngine] 턴 완료 수신: {event.payload.get('llm_response', '')}")
        else:
            debug_log(self.verbose, f"[MainEngine] 처리하지 않는 이벤트: {event.etype}")

    # ── 상태 보고 ──────────────────────────
    def status(self):
        self.memory.dump()
        print(f"  등록 모듈: {list(self.modules.keys())}")
        print(f"  대기 이벤트: {len(self.event_queue)}개\n")


# ─────────────────────────────────────────
# 7. 실행 테스트
# ─────────────────────────────────────────

if __name__ == "__main__":
    engine = MainEngine()

    # 메모리에 초기값 설정 (중첩 상태로 시작)
    engine.memory.set("user_trust",    value=0.5,  qstate=QVal.SUPER,    confidence=0.5)
    engine.memory.set("task_complete", value=False, qstate=QVal.FALSE,   confidence=0.9)
    engine.memory.set("user_emotion",  value="unknown", qstate=QVal.COEXIST,
                      context=["대화중", "대기중"])

    # 증거 주입 → 상태 붕괴 판단
    engine.judge_and_output("user_trust", evidence=0.85)    # → TRUE
    engine.judge_and_output("user_emotion", evidence=-0.3)  # → 중첩 유지

    # 이벤트 발행 테스트
    engine.emit(Event(
        source="dialogue_engine",
        target="image_engine",
        etype="EMOTION_CHANGE",
        payload={"emotion": "CURIOUS", "intensity": 0.7},
        priority=2
    ))

    engine.tick()       # 이벤트 1개 처리
    engine.status()     # 전체 상태 출력