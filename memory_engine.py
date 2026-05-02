"""
MEMORY ENGINE
─────────────────────────────────────────────
[SQLite]  장기기억 — 대화이력, 유저프로필, 학습된 사실
          단기기억 — 최근 N턴 대화 (슬라이딩 윈도우)
[Cache]   휘발성   — 현재 생각, 판단 중간값, 감정상태
          프로세스 종료 시 자동 소멸
─────────────────────────────────────────────
"""

import sqlite3
import time
import json
import re
from datetime import datetime
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from enum import Enum

from runtime_logging import debug_log


# ─────────────────────────────────────────
# 공통: 4진 상태 (메인엔진과 공유)
# ─────────────────────────────────────────

class QVal(Enum):
    TRUE    = "TRUE"
    FALSE   = "FALSE"
    SUPER   = "SUPER"
    COEXIST = "COEXIST"


# ─────────────────────────────────────────
# 1. 캐시 — 휘발성 메모리 (생각 / 판단 중간값)
# ─────────────────────────────────────────

@dataclass
class CacheCell:
    key:       str
    value:     Any
    qstate:    QVal   = QVal.SUPER
    ttl:       float  = 60.0          # 기본 60초 후 소멸
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl

    def remaining(self) -> float:
        return max(0.0, self.ttl - (time.time() - self.created_at))


class ThinkCache:
    """
    휘발성 캐시 — 생각/판단 과정의 중간 상태
    TTL 만료 또는 명시적 flush 로 소멸
    """

    # 슬롯별 기본 TTL (초)
    TTL_MAP = {
        "emotion":   30.0,    # 감정 상태
        "intent":    20.0,    # 현재 의도
        "thought":   15.0,    # 현재 생각 조각
        "judgement": 10.0,    # 판단 중간값
        "focus":     45.0,    # 집중 대상
        "default":   60.0,
    }

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self._store: dict[str, CacheCell] = {}
        self._lock = threading.Lock()
        # 백그라운드 GC 스레드
        self._gc_thread = threading.Thread(target=self._gc_loop, daemon=True)
        self._gc_thread.start()

    def set(self, key: str, value: Any,
            qstate: QVal = QVal.SUPER,
            slot: str = "default",
            ttl: Optional[float] = None) -> CacheCell:
        ttl = ttl or self.TTL_MAP.get(slot, self.TTL_MAP["default"])
        cell = CacheCell(key=key, value=value, qstate=qstate, ttl=ttl)
        with self._lock:
            self._store[key] = cell
        return cell

    def get(self, key: str) -> Optional[CacheCell]:
        with self._lock:
            cell = self._store.get(key)
            if cell and cell.is_expired():
                del self._store[key]
                return None
            return cell

    def flush(self, key: Optional[str] = None):
        """특정 키 또는 전체 캐시 즉시 소멸"""
        with self._lock:
            if key:
                self._store.pop(key, None)
            else:
                self._store.clear()
        debug_log(self.verbose, f"[Cache] flush: {'전체' if not key else key}")

    def snapshot(self) -> dict:
        """현재 유효한 캐시 전체 스냅샷 (판단 시 컨텍스트 수집용)"""
        with self._lock:
            return {
                k: {"value": c.value, "qstate": c.qstate.value,
                    "remaining": f"{c.remaining():.1f}s"}
                for k, c in self._store.items()
                if not c.is_expired()
            }

    def _gc_loop(self):
        """5초마다 만료 셀 정리"""
        while True:
            time.sleep(5)
            with self._lock:
                expired = [k for k, c in self._store.items() if c.is_expired()]
                for k in expired:
                    del self._store[k]
            if expired:
                debug_log(self.verbose, f"[Cache GC] 만료 제거: {expired}")


# ─────────────────────────────────────────
# 2. SQLite — 장기/단기 기억
# ─────────────────────────────────────────

class SQLMemory:
    """
    장기기억: facts, user_profile
    단기기억: recent_turns (슬라이딩 윈도우, 최근 N턴 유지)
    """

    RECENT_WINDOW = 30   # 단기기억 유지 턴 수
    SUMMARY_BUFFER = 6   # 오래된 대화를 배치로 압축할 최소 버퍼

    def __init__(self, db_path: str = "memory.db", verbose: bool = True):
        self.db_path = db_path
        self.verbose = verbose
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_tables()
        debug_log(self.verbose, f"[SQLMemory] DB 연결: {db_path}")

    def _init_tables(self):
        with self._conn:
            # 장기기억: 학습된 사실/지식
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    key       TEXT NOT NULL UNIQUE,
                    value     TEXT NOT NULL,
                    qstate    TEXT DEFAULT 'SUPER',
                    confidence REAL DEFAULT 0.5,
                    context   TEXT DEFAULT '[]',
                    updated_at REAL NOT NULL
                )
            """)
            # 장기기억: 유저 프로필
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    attr      TEXT PRIMARY KEY,
                    value     TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            # 단기기억: 최근 대화 턴
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS recent_turns (
                    turn_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    role      TEXT NOT NULL,        -- 'user' | 'ai'
                    content   TEXT NOT NULL,
                    emotion   TEXT DEFAULT NULL,
                    qstate    TEXT DEFAULT 'SUPER',
                    timestamp REAL NOT NULL
                )
            """)
            # 장기기억: 압축 요약 (오래된 대화 → 요약 저장)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term_summary (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary   TEXT NOT NULL,
                    period_start REAL,
                    period_end   REAL,
                    created_at   REAL NOT NULL
                )
            """)

    # ── 장기기억: Facts ───────────────────

    def save_fact(self, key: str, value: Any,
                  qstate: QVal = QVal.SUPER,
                  confidence: float = 0.5,
                  context: Optional[list[Any]] = None):
        with self._lock:
            with self._conn:
                self._conn.execute("""
                    INSERT INTO facts (key, value, qstate, confidence, context, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        qstate=excluded.qstate,
                        confidence=excluded.confidence,
                        context=excluded.context,
                        updated_at=excluded.updated_at
                """, (key, json.dumps(value, ensure_ascii=False),
                      qstate.value, confidence,
                      json.dumps(context or []), time.time()))

    def get_fact(self, key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM facts WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        return {
            "key": row[1], "value": json.loads(row[2]),
            "qstate": row[3], "confidence": row[4],
            "context": json.loads(row[5]), "updated_at": row[6]
        }

    def get_facts(self, limit: Optional[int] = None) -> dict[str, Any]:
        query = "SELECT key, value FROM facts ORDER BY updated_at DESC"
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()

        return {key: json.loads(value) for key, value in rows}

    # ── 유저 프로필 ───────────────────────

    def set_profile(self, attr: str, value: Any):
        with self._lock:
            with self._conn:
                self._conn.execute("""
                    INSERT INTO user_profile (attr, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(attr) DO UPDATE SET
                        value=excluded.value, updated_at=excluded.updated_at
                """, (attr, json.dumps(value, ensure_ascii=False), time.time()))

    def get_profile(self, attr: Optional[str] = None) -> Optional[dict[str, Any]]:
        with self._lock:
            if attr:
                row = self._conn.execute(
                    "SELECT value FROM user_profile WHERE attr = ?", (attr,)
                ).fetchone()
                return json.loads(row[0]) if row else None
            else:
                rows = self._conn.execute("SELECT attr, value FROM user_profile").fetchall()
                return {r[0]: json.loads(r[1]) for r in rows}

    # ── 단기기억: 최근 대화 턴 ───────────

    def push_turn(self, role: str, content: str,
                  emotion: Optional[str] = None, qstate: QVal = QVal.SUPER) -> Optional[dict[str, Any]]:
        with self._lock:
            with self._conn:
                self._conn.execute("""
                    INSERT INTO recent_turns (role, content, emotion, qstate, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (role, content, emotion, qstate.value, time.time()))
                return self._archive_overflow_turns_locked()

    def get_recent(self, n: int = 10) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("""
                SELECT role, content, emotion, qstate, timestamp
                FROM recent_turns
                ORDER BY turn_id DESC LIMIT ?
            """, (n,)).fetchall()
        return [
            {"role": r[0], "content": r[1],
             "emotion": r[2], "qstate": r[3], "timestamp": r[4]}
            for r in reversed(rows)
        ]

    # ── 장기 요약 저장 ────────────────────

    def archive_summary(self, summary: str, period_start: float, period_end: float):
        with self._lock:
            with self._conn:
                self._conn.execute("""
                    INSERT INTO long_term_summary
                    (summary, period_start, period_end, created_at)
                    VALUES (?, ?, ?, ?)
                """, (summary, period_start, period_end, time.time()))
        debug_log(self.verbose, f"[SQLMemory] 장기 요약 저장 완료")

    def get_summaries(self, limit: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("""
                SELECT summary, period_start, period_end, created_at
                FROM long_term_summary ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [{"summary": r[0], "period_start": r[1],
                 "period_end": r[2], "created_at": r[3]} for r in rows]

    def update_summary(self, summary_id: int, summary: str):
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE long_term_summary SET summary = ? WHERE id = ?",
                    (summary, summary_id),
                )

    def _archive_overflow_turns_locked(self) -> Optional[dict[str, Any]]:
        total_turns = self._conn.execute(
            "SELECT COUNT(*) FROM recent_turns"
        ).fetchone()[0]
        threshold = self.RECENT_WINDOW + self.SUMMARY_BUFFER
        if total_turns <= threshold:
            return None

        overflow_count = total_turns - self.RECENT_WINDOW
        rows = self._conn.execute(
            """
            SELECT turn_id, role, content, emotion, timestamp
            FROM recent_turns
            ORDER BY turn_id ASC LIMIT ?
            """,
            (overflow_count,),
        ).fetchall()
        if not rows:
            return None

        summary = self._build_turn_summary(rows)
        summary_id: int | None = None
        if summary:
            cursor = self._conn.execute(
                """
                INSERT INTO long_term_summary (summary, period_start, period_end, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (summary, rows[0][4], rows[-1][4], time.time()),
            )
            summary_id = int(cursor.lastrowid)

        turn_ids = [row[0] for row in rows]
        placeholders = ", ".join("?" for _ in turn_ids)
        self._conn.execute(
            f"DELETE FROM recent_turns WHERE turn_id IN ({placeholders})",
            turn_ids,
        )
        debug_log(self.verbose, f"[SQLMemory] 최근 대화 {len(turn_ids)}턴을 장기 요약으로 압축")
        return {
            "summary_id": summary_id,
            "fallback_summary": summary,
            "period_start": rows[0][4],
            "period_end": rows[-1][4],
            "turns": [
                {
                    "role": row[1],
                    "content": row[2],
                    "emotion": row[3],
                    "timestamp": row[4],
                }
                for row in rows
            ],
        }

    def _build_turn_summary(self, rows: list[tuple[Any, ...]]) -> str:
        user_points: list[str] = []
        ai_points: list[str] = []
        emotions: list[str] = []

        for _, role, content, emotion, _ in rows:
            cleaned = self._normalize_summary_text(content)
            if not cleaned:
                continue
            if role == "user" and len(user_points) < 3:
                user_points.append(cleaned)
            elif role != "user" and len(ai_points) < 2:
                ai_points.append(cleaned)
            if emotion and emotion not in emotions:
                emotions.append(emotion)

        summary_parts: list[str] = []
        if user_points:
            summary_parts.append("사용자는 " + " / ".join(user_points))
        if ai_points:
            summary_parts.append("AI는 " + " / ".join(ai_points))
        if emotions:
            summary_parts.append("감정 흐름: " + ", ".join(emotions[:3]))

        return " | ".join(summary_parts)

    def _normalize_summary_text(self, content: str, limit: int = 70) -> str:
        cleaned = re.sub(r"\s+", " ", content).strip()
        cleaned = re.sub(r"^(You|AI|Assistant)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        if len(cleaned) > limit:
            cleaned = cleaned[:limit].rstrip() + "..."
        return cleaned

    def close(self):
        self._conn.close()


# ─────────────────────────────────────────
# 3. 메모리엔진 통합 인터페이스
# ─────────────────────────────────────────

class MemoryEngine:
    """
    메인엔진에서 호출하는 단일 진입점
    cache  → 휘발성 생각/판단
    sql    → 장기/단기 영속 기억
    """

    def __init__(self, db_path: str = "memory.db", verbose: bool = True):
        self.verbose = verbose
        self.cache = ThinkCache(verbose=verbose)
        self.sql   = SQLMemory(db_path, verbose=verbose)
        debug_log(self.verbose, "[MemoryEngine] 초기화 완료 — Cache + SQLite 활성")

    AUTO_LEARN_PATTERNS: dict[str, str] = {
        "name": r"(?:내\s*이름은|이름은)\s*([가-힣A-Za-z0-9_]{2,20})(?:야|이야|이에요|예요|입니다)?(?:\s|$|[.!?,])",
        "location": r"(?:나는|저는|전)\s*([가-힣A-Za-z]{2,20})에\s*(?:살아|거주해|있어)",
        "job": r"(?:나는|저는|전)\s*([가-힣A-Za-z]{2,20})\s*(?:야|이야|이에요|예요|입니다)(?:\s|$|[.!?,]|그리고|근데|인데)",
    }

    # ── 메인엔진 이벤트 핸들러 ─────────────
    def handle(self, event):
        t = event.etype
        p = event.payload

        if t == "MEMORY_SAVE_FACT":
            self.sql.save_fact(
                p["key"], p["value"],
                QVal(p.get("qstate", "SUPER")),
                p.get("confidence", 0.5),
                p.get("context", [])
            )
        elif t == "MEMORY_PUSH_TURN":
            self.sql.push_turn(
                p["role"], p["content"],
                p.get("emotion"), QVal(p.get("qstate", "SUPER"))
            )
        elif t == "CACHE_SET":
            self.cache.set(
                p["key"], p["value"],
                QVal(p.get("qstate", "SUPER")),
                p.get("slot", "default")
            )
        elif t == "CACHE_FLUSH":
            self.cache.flush(p.get("key"))

    # ── 컨텍스트 수집 (판단엔진용) ─────────
    def collect_context(self, recent_n: int = 5) -> dict:
        """
        현재 판단에 필요한 모든 컨텍스트 한 번에 수집
        대화판단엔진 → 메인엔진 턴 시 첨부
        """
        return {
            "cache_snapshot": self.cache.snapshot(),
            "recent_turns":   self.sql.get_recent(recent_n),
            "user_profile":   self.sql.get_profile(),
            "known_facts":    self.sql.get_facts(limit=20),
            "long_term_summaries": self.sql.get_summaries(limit=3),
            "system_time":    self._system_time_context(),
        }

    def recall_memory(self,
                      query: str,
                      recent_n: int = 6,
                      fact_limit: int = 10,
                      summary_limit: int = 3) -> dict[str, Any]:
        profile = self.sql.get_profile() or {}
        facts = self.sql.get_facts(limit=fact_limit)
        recent_turns = self.sql.get_recent(recent_n)
        summaries = self.sql.get_summaries(limit=summary_limit)
        keywords = self._extract_memory_keywords(query)

        matched_profile = {
            key: value for key, value in profile.items()
            if not keywords or any(keyword in f"{key} {value}".lower() for keyword in keywords)
        }
        matched_facts = {
            key: value for key, value in facts.items()
            if not keywords or any(keyword in f"{key} {value}".lower() for keyword in keywords)
        }
        matched_recent = [
            turn for turn in recent_turns
            if not keywords or any(keyword in turn["content"].lower() for keyword in keywords)
        ]
        matched_summaries = [
            item for item in summaries
            if not keywords or any(keyword in item["summary"].lower() for keyword in keywords)
        ]

        if keywords:
            return {
                "keywords": keywords,
                "user_profile": matched_profile,
                "known_facts": matched_facts,
                "recent_turns": matched_recent[:recent_n],
                "full_recent_turns": recent_turns,
                "long_term_summaries": matched_summaries[:summary_limit],
            }

        return {
            "keywords": [],
            "user_profile": profile,
            "known_facts": facts,
            "recent_turns": recent_turns,
            "full_recent_turns": recent_turns,
            "long_term_summaries": summaries,
        }

    def learn_from_turn(self,
                        user_input: str,
                        ai_response: str = "",
                        emotion: Optional[str] = None):
        text = user_input.strip()
        if not text:
            return

        self.sql.set_profile("preferred_language", "ko")

        profile_updates = self._extract_profile_updates(text)
        for attr, value in profile_updates.items():
            self.sql.set_profile(attr, value)

        fact_updates = self._extract_fact_updates(text, ai_response, emotion)
        for item in fact_updates:
            self.sql.save_fact(
                item["key"],
                item["value"],
                qstate=QVal.TRUE,
                confidence=item.get("confidence", 0.7),
                context=item.get("context", [text]),
            )

        if profile_updates or fact_updates:
            debug_log(
                self.verbose,
                f"[MemoryEngine] 자동 학습 완료: profile={list(profile_updates.keys())}, facts={[item['key'] for item in fact_updates]}",
            )

    def upgrade_summary_with_llm(self,
                                 archive_info: Optional[dict[str, Any]],
                                 llm_connector: Any | None) -> Optional[str]:
        if not archive_info or not archive_info.get("summary_id") or llm_connector is None:
            return None

        transcript = self._format_archive_turns(archive_info.get("turns", []))
        if not transcript:
            return None

        summary_prompt = (
            "다음은 오래된 대화 묶음입니다. 장기 기억용으로만 사용할 요약을 작성하세요.\n"
            "- 자연스러운 한국어 2~3문장\n"
            "- 사용자의 사실, 선호, 문제 해결 맥락, 감정 흐름을 우선\n"
            "- 불필요한 인사, 추측, 따옴표, 목록 기호 금지\n"
            "- 결과만 바로 출력\n\n"
            f"[기존 규칙 요약]\n{archive_info.get('fallback_summary', '')}\n\n"
            f"[대화 원문]\n{transcript}"
        )

        try:
            response = llm_connector.chat(
                summary_prompt,
                context={
                    "user_profile": self.sql.get_profile() or {},
                    "known_facts": self.sql.get_facts(limit=10),
                },
                system_override=(
                    "당신은 장기 기억 요약기입니다. 과거 대화를 압축해도 핵심 사실과 맥락이 유지되게 써야 합니다."
                ),
            )
        except Exception as error:
            debug_log(self.verbose, f"[MemoryEngine] LLM 요약 업그레이드 실패: {error}")
            return None

        upgraded = self._sanitize_summary_text(response.text if response else "")
        if not upgraded:
            return None

        self.sql.update_summary(archive_info["summary_id"], upgraded)
        debug_log(self.verbose, "[MemoryEngine] 장기 요약을 LLM 기반 요약으로 업그레이드")
        return upgraded

    def _extract_profile_updates(self, text: str) -> dict[str, Any]:
        updates: dict[str, Any] = {}

        name_match = re.search(self.AUTO_LEARN_PATTERNS["name"], text)
        if name_match:
            updates["name"] = re.sub(r"(야|이야|이에요|예요|입니다)$", "", name_match.group(1)).strip()

        location_match = re.search(self.AUTO_LEARN_PATTERNS["location"], text)
        if location_match:
            updates["location"] = location_match.group(1)

        job_match = re.search(self.AUTO_LEARN_PATTERNS["job"], text)
        if job_match:
            job_value = job_match.group(1)
            blocked = {"사람", "학생", "개발자", "디자이너", "프로그래머", "직장인", "연구원"}
            if job_value in blocked:
                updates["job"] = job_value

        likes = self._extract_preference_tokens(text, positive=True)
        if likes:
            updates["likes"] = self._merge_unique_list(self.sql.get_profile("likes"), likes)

        dislikes = self._extract_preference_tokens(text, positive=False)
        if dislikes:
            updates["dislikes"] = self._merge_unique_list(self.sql.get_profile("dislikes"), dislikes)

        return updates

    def _extract_memory_keywords(self, query: str) -> list[str]:
        normalized = query.lower()
        generic_tokens = {
            "기억", "장기", "장기기억", "장기 기억", "최근", "방금", "저번", "전에",
            "말", "말해", "말해봐", "알려", "알려줘", "기억나", "기억해", "있는거",
            "있어", "있니", "있는", "하고", "하고있는", "뭐", "뭔", "내용", "대화",
            "해줘", "해봐", "보여줘", "정리해줘", "보여", "줬잖아", "못해", "못하네",
            "못하냐", "왜", "방금", "기억못해", "기억", "했잖아",
        }
        tokens = [token.strip() for token in re.split(r"\s+", normalized) if len(token.strip()) >= 2]
        keywords = [token for token in tokens if token not in generic_tokens]
        return keywords

    def _format_archive_turns(self, turns: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for turn in turns:
            role = "사용자" if turn.get("role") == "user" else "AI"
            content = self._normalize_summary_text(str(turn.get("content", "")), limit=120)
            if not content:
                continue
            emotion = turn.get("emotion")
            suffix = f" [emotion={emotion}]" if emotion else ""
            lines.append(f"{role}: {content}{suffix}")
        return "\n".join(lines)

    def _sanitize_summary_text(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = cleaned.strip("'\"“”‘’`-• ")
        if len(cleaned) > 280:
            cleaned = cleaned[:280].rstrip() + "..."
        return cleaned

    def _normalize_summary_text(self, content: str, limit: int = 70) -> str:
        cleaned = re.sub(r"\s+", " ", content).strip()
        cleaned = re.sub(r"^(You|AI|Assistant|사용자)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        if len(cleaned) > limit:
            cleaned = cleaned[:limit].rstrip() + "..."
        return cleaned

    def _extract_fact_updates(self,
                              text: str,
                              ai_response: str,
                              emotion: Optional[str]) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []

        updates.append({
            "key": "last_user_message",
            "value": text,
            "confidence": 0.4,
            "context": [text, ai_response[:120]] if ai_response else [text],
        })

        if emotion:
            updates.append({
                "key": "last_user_emotion",
                "value": emotion,
                "confidence": 0.6,
                "context": [text],
            })

        topic = self._extract_topic(text)
        if topic:
            updates.append({
                "key": "recent_topic",
                "value": topic,
                "confidence": 0.55,
                "context": [text],
            })

        return updates

    def _extract_preference_tokens(self, text: str, positive: bool) -> list[str]:
        suffix = "좋아해" if positive else "싫어해"
        match = re.search(rf"([가-힣A-Za-z0-9 ]{{1,20}}?)(?:을|를|은|는)?\s*{suffix}", text)
        if not match:
            return []

        token = match.group(1).strip()
        token = re.sub(r"^(나는|저는|전)\s*", "", token)
        token = re.split(r"\b(?:그리고|근데|하지만|인데)\b", token)[-1].strip()
        token = re.sub(r"^(?:그리고|근데|하지만|인데)\s*", "", token)
        token = re.sub(r"(?:이야|이에요|예요|입니다)$", "", token).strip()
        if not token or len(token) > 20:
            return []
        return [token]

    def _extract_topic(self, text: str) -> Optional[str]:
        liked = self._extract_preference_tokens(text, positive=True)
        if liked:
            return liked[0]

        disliked = self._extract_preference_tokens(text, positive=False)
        if disliked:
            return disliked[0]

        cleaned = re.sub(r"[^가-힣A-Za-z0-9\s]", " ", text)
        tokens = [token for token in cleaned.split() if len(token) >= 2]
        if not tokens:
            return None

        stopwords = {
            "나는", "저는", "그냥", "지금", "오늘", "정말", "너무", "조금",
            "해주세요", "해줘", "있어", "없어", "좋아해", "싫어해",
            "이름은", "내", "이름", "서울에",
        }
        for token in tokens:
            if token not in stopwords:
                return token
        return None

    def _merge_unique_list(self, current: Any, incoming: list[str]) -> list[str]:
        items: list[str] = []
        if isinstance(current, list):
            items.extend(str(item) for item in current)
        elif current:
            items.append(str(current))

        for value in incoming:
            if value not in items:
                items.append(value)
        return items

    def _system_time_context(self) -> dict[str, str]:
        now = datetime.now()
        weekday_names = ["월", "화", "수", "목", "금", "토", "일"]
        weekday = weekday_names[now.weekday()]
        return {
            "iso": now.isoformat(timespec="seconds"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "display": now.strftime(f"%Y년 %m월 %d일 ({weekday}) %H시 %M분 %S초"),
            "weekday": weekday,
        }
    def status(self):
        print("\n── MemoryEngine 상태 ─────────────────")
        snap = self.cache.snapshot()
        print(f"  [Cache] 활성 셀 {len(snap)}개: {list(snap.keys())}")
        recent = self.sql.get_recent(3)
        print(f"  [SQL] 최근 {len(recent)}턴:")
        for t in recent:
            print(f"    [{t['role']}] {t['content'][:40]}... ({t['qstate']})")
        print("──────────────────────────────────────\n")


# ─────────────────────────────────────────
# 4. 실행 테스트
# ─────────────────────────────────────────

if __name__ == "__main__":
    mem = MemoryEngine(db_path=":memory:")   # 테스트용 인메모리 DB

    # 유저 프로필 저장
    mem.sql.set_profile("name", "사용자")
    mem.sql.set_profile("preferred_language", "ko")

    # 장기기억 저장
    mem.sql.save_fact("ai_name", "아이리스",
                      qstate=QVal.TRUE, confidence=1.0)

    # 대화 턴 저장
    mem.sql.push_turn("user", "안녕, 오늘 날씨 어때?",
                      emotion="NEUTRAL", qstate=QVal.TRUE)
    mem.sql.push_turn("ai", "안녕하세요! 오늘은 맑은 날씨네요.",
                      emotion="HAPPY", qstate=QVal.TRUE)

    # 캐시에 현재 생각 저장 (휘발성)
    mem.cache.set("current_thought", "유저가 날씨에 관심 있음",
                  slot="thought", qstate=QVal.SUPER)
    mem.cache.set("emotion", "HAPPY",
                  slot="emotion", qstate=QVal.TRUE)

    # 컨텍스트 수집
    ctx = mem.collect_context()
    print("\n[컨텍스트 수집 결과]")
    print(f"  캐시: {ctx['cache_snapshot']}")
    print(f"  최근 대화: {len(ctx['recent_turns'])}턴")
    print(f"  유저 프로필: {ctx['user_profile']}")

    mem.status()