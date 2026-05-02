"""
DIALOGUE ENGINE
─────────────────────────────────────────────
유저 입력 수신
  → 의도 분류 (Intent)
  → 감정 추출 (Emotion)
  → 컨텍스트 조립 (Memory)
  → LLM 호출
  → 응답 후처리
  → 메인엔진에 턴 반환
─────────────────────────────────────────────
"""

import re
import time
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from runtime_logging import debug_log


# ─────────────────────────────────────────
# 1. 의도 분류 (Intent)
# ─────────────────────────────────────────

class Intent(Enum):
    GREETING = "GREETING"
    QUESTION = "QUESTION"
    COMMAND = "COMMAND"
    EMOTION = "EMOTION"
    SMALLTALK = "SMALLTALK"
    MEMORY = "MEMORY"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"


MEMORY_KEYWORDS = [
    "기억", "장기 기억", "장기기억", "기억나", "기억하고", "저번에", "전에 말", "잊었어",
]

CREATIVE_REQUEST_KEYWORDS = [
    "소설", "이야기", "창작", "시", "대본", "각본", "써줘", "써 봐", "보여줘", "만들어줘",
]


INTENT_RULES: list[tuple[Intent, list[str]]] = [
    (Intent.GREETING, ["안녕", "반가워", "hi", "hello", "좋은아침", "잘자"]),
    (Intent.QUESTION, ["?", "뭐야", "어때", "알려줘", "뭔지", "어떻게", "왜", "언제", "누구"]),
    (Intent.COMMAND, ["해줘", "해봐", "실행", "켜줘", "꺼줘", "열어", "닫아", "검색해"]),
    (Intent.EMOTION, ["기분", "슬퍼", "행복", "화나", "짜증", "무서워", "외로워", "좋아"]),
    (Intent.MEMORY, ["기억해", "저번에", "아까", "전에 말했", "잊었어"]),
    (Intent.SYSTEM, ["종료", "재시작", "멈춰", "잠깐", "일시정지", "시스템"]),
]


def classify_intent(text: str) -> Intent:
    lowered = text.lower()
    if any(keyword in lowered for keyword in MEMORY_KEYWORDS):
        return Intent.MEMORY
    if any(keyword in lowered for keyword in CREATIVE_REQUEST_KEYWORDS):
        return Intent.COMMAND
    for intent, keywords in INTENT_RULES:
        if any(keyword in lowered for keyword in keywords):
            return intent
    return Intent.SMALLTALK


# ─────────────────────────────────────────
# 2. 감정 추출 (Emotion)
# ─────────────────────────────────────────

class Emotion(Enum):
    HAPPY = "HAPPY"
    SAD = "SAD"
    ANGRY = "ANGRY"
    ANXIOUS = "ANXIOUS"
    NEUTRAL = "NEUTRAL"
    CURIOUS = "CURIOUS"
    TIRED = "TIRED"


EMOTION_RULES: list[tuple[Emotion, list[str]]] = [
    (Emotion.HAPPY, ["기뻐", "행복", "좋아", "신나", "재밌", "ㅋㅋ", "😊", "😄"]),
    (Emotion.SAD, ["슬퍼", "우울", "힘들어", "눈물", "외로워", "😢", "ㅠㅠ"]),
    (Emotion.ANGRY, ["화나", "짜증", "열받", "싫어", "ㅡㅡ", "😡"]),
    (Emotion.ANXIOUS, ["무서워", "걱정", "불안", "긴장", "떨려"]),
    (Emotion.CURIOUS, ["궁금", "신기", "흥미", "왜", "어떻게", "??"]),
    (Emotion.TIRED, ["피곤", "졸려", "지쳐", "힘없", "쉬고싶"]),
]


def extract_emotion(text: str) -> Emotion:
    lowered = text.lower()
    for emotion, keywords in EMOTION_RULES:
        if any(keyword in lowered for keyword in keywords):
            return emotion
    return Emotion.NEUTRAL


# ─────────────────────────────────────────
# 3. 판단 결과 객체
# ─────────────────────────────────────────

@dataclass
class TurnResult:
    user_input: str
    intent: Intent
    emotion: Emotion
    llm_response: str
    elapsed: float
    success: bool = True
    error: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_input": self.user_input,
            "intent": self.intent.value,
            "emotion": self.emotion.value,
            "llm_response": self.llm_response,
            "elapsed": self.elapsed,
            "success": self.success,
        }


# ─────────────────────────────────────────
# 4. 대화 판단 엔진
# ─────────────────────────────────────────

class DialogueEngine:
    def __init__(self, main_engine: Optional[Any] = None, verbose: bool = True):
        self._main = main_engine
        self.verbose = verbose
        self._memory: Optional[Any] = None
        self._llm: Optional[Any] = None
        self._search: Optional[Any] = None
        self.on_response: Optional[Callable[[TurnResult], None]] = None
        debug_log(self.verbose, "[DialogueEngine] 초기화 완료")

    def attach(self,
               memory_engine: Any,
               llm_connector: Any,
               search_engine: Any | None = None):
        self._memory = memory_engine
        self._llm = llm_connector
        self._search = search_engine
        debug_log(self.verbose, "[DialogueEngine] 메모리엔진 + LLM 연결 완료")

    def process(self, user_input: str) -> TurnResult:
        start = time.time()
        text = user_input.strip()

        intent = classify_intent(text)
        emotion = extract_emotion(text)

        debug_log(self.verbose, f"[DialogueEngine] 입력: '{text}'")
        debug_log(self.verbose, f"  → 의도: {intent.value} / 감정: {emotion.value}")

        if self._memory:
            self._memory.cache.set("intent", intent.value, slot="intent")
            self._memory.cache.set("emotion", emotion.value, slot="emotion")

        if intent == Intent.SYSTEM:
            result = self._handle_system(text, intent, emotion, start)
            self._return_turn(result)
            return result

        if self._is_datetime_query(text):
            result = self._handle_datetime_query(text, intent, emotion, start)
            self._return_turn(result)
            return result

        if intent == Intent.MEMORY:
            result = self._handle_memory_query(text, intent, emotion, start)
            self._persist_turn(result, emotion.value)
            self._return_turn(result)
            return result

        search_query = self._extract_search_query(text)
        if search_query:
            result = self._handle_web_search(text, search_query, intent, emotion, start)
            self._return_turn(result)
            return result

        context: dict[str, Any] = {}
        if self._memory:
            context = self._memory.collect_context(recent_n=6)

        llm_response = self._call_llm(text, context, intent, emotion)
        response_text = self._postprocess(llm_response.text, intent)

        result = TurnResult(
            user_input=text,
            intent=intent,
            emotion=emotion,
            llm_response=response_text,
            elapsed=round(time.time() - start, 2),
            success=llm_response.success,
            error=llm_response.error,
        )
        self._persist_turn(result, emotion.value)
        self._return_turn(result)
        return result

    def _call_llm(self,
                  text: str,
                  context: dict[str, Any],
                  intent: Intent,
                  emotion: Emotion):
        if not self._llm:
            from llm_connector import LLMResponse
            return LLMResponse(
                text="LLM이 연결되지 않았습니다.",
                model="none",
                elapsed=0.0,
                success=False,
            )

        system_hint = self._intent_system_hint(text, intent, emotion)
        response = self._llm.chat(text, context=context, system_override=system_hint)
        if response.success and self._contains_disallowed_cjk(response.text):
            rewritten = self._rewrite_response_in_korean(text, response.text, intent, emotion)
            if rewritten is not None:
                return rewritten
        return response

    def _intent_system_hint(self, text: str, intent: Intent, emotion: Emotion) -> str:
        base = """당신은 사용자와 함께 생활하는 AI 동반자입니다.
자연스럽고 따뜻하게 대화하며, 사용자의 감정 상태를 세심하게 반영합니다."""

        hints = {
            Intent.GREETING: "밝고 친근하게 인사로 응답하세요. 짧게.",
            Intent.QUESTION: "정확하고 명확하게 답변하세요.",
            Intent.COMMAND: "요청을 확인하고 실행 여부를 알려주세요.",
            Intent.EMOTION: "공감을 먼저 표현한 후 응답하세요.",
            Intent.SMALLTALK: "편안하고 자연스럽게 대화하세요.",
            Intent.MEMORY: "기억을 바탕으로 연결된 대화를 이어가세요.",
        }

        emotion_hints = {
            Emotion.SAD: "사용자가 슬픈 상태입니다. 따뜻하게 위로하세요.",
            Emotion.ANGRY: "사용자가 화난 상태입니다. 차분하게 공감하세요.",
            Emotion.ANXIOUS: "사용자가 불안한 상태입니다. 안심시켜 주세요.",
            Emotion.TIRED: "사용자가 피곤한 상태입니다. 부드럽게 응답하세요.",
        }

        prompt = base
        if intent in hints:
            prompt += f"\n[지침] {hints[intent]}"
        if self._looks_like_story_request(text):
            prompt += "\n[창작 요청] 사용자가 바로 읽을 수 있는 짧은 창작 본문을 실제로 생성하세요. 요청을 설명하거나 되묻지 말고 결과를 본문 형태로 바로 제시하세요. 한국어 외 문자권 언어를 섞지 마세요. 중국어 문장, 중국어 제목, 중국어 예시는 금지합니다."
        if emotion in emotion_hints:
            prompt += f"\n[감정 대응] {emotion_hints[emotion]}"
        return prompt

    def _postprocess(self, text: str, intent: Intent) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > 500 and intent == Intent.SMALLTALK:
            text = text[:500] + "..."
        return text

    def _extract_search_query(self, text: str) -> Optional[str]:
        patterns = [
            r"(.+?)\s*(?:검색해줘|검색해|검색해 봐|검색해봐|찾아줘|찾아봐|알아봐줘)$",
            r"(?:웹검색|인터넷검색|검색)\s*[: ]\s*(.+)$",
            r"(?:인터넷에서|웹에서)\s*(.+?)\s*(?:검색해줘|검색해|찾아줘|찾아봐|알려줘)?$",
        ]

        for pattern in patterns:
            match = re.search(pattern, text.strip(), re.IGNORECASE)
            if not match:
                continue

            query = re.sub(r"\s+", " ", match.group(1)).strip(" .!?")
            if len(query) >= 2:
                return query
        return None

    def _contains_disallowed_cjk(self, text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def _rewrite_response_in_korean(self,
                                    user_text: str,
                                    original_text: str,
                                    intent: Intent,
                                    emotion: Emotion):
        if not self._llm:
            return None

        rewrite_prompt = (
            "다음 응답을 의미를 바꾸지 말고 자연스러운 한국어로만 다시 써주세요.\n"
            "- 중국어, 한자, 영어 설명투 금지\n"
            "- 이미 생성된 내용의 핵심은 유지\n"
            "- 요청이 창작이면 본문 형식을 유지\n"
            "- 결과만 바로 출력\n\n"
            f"[사용자 요청]\n{user_text}\n\n"
            f"[재작성할 응답]\n{original_text}"
        )
        rewrite_hint = self._intent_system_hint(user_text, intent, emotion)
        rewrite_hint += "\n[재작성 규칙] 출력은 한국어만 허용됩니다. 한자와 중국어 문장을 모두 제거하세요."
        rewritten = self._llm.chat(rewrite_prompt, context=None, system_override=rewrite_hint)
        if rewritten.success and not self._contains_disallowed_cjk(rewritten.text):
            return rewritten
        return None

    def _is_datetime_query(self, text: str) -> bool:
        normalized = text.lower().replace(" ", "")
        time_keywords = [
            "몇시", "현재시간", "지금시간", "몇시야", "시간알려", "시간좀",
            "whattime", "currenttime",
        ]
        date_keywords = [
            "오늘몇일", "오늘날짜", "현재날짜", "지금날짜", "며칠", "몇월몇일",
            "whatdate", "todaydate",
        ]
        return any(keyword in normalized for keyword in time_keywords + date_keywords)

    def _handle_datetime_query(self,
                               text: str,
                               intent: Intent,
                               emotion: Emotion,
                               start: float) -> TurnResult:
        now = datetime.now()
        normalized = text.lower().replace(" ", "")

        if any(keyword in normalized for keyword in ["몇시", "현재시간", "지금시간", "몇시야", "시간알려", "시간좀", "whattime", "currenttime"]):
            response = f"현재 시간은 {now.strftime('%Y년 %m월 %d일 %H시 %M분')}입니다."
        elif any(keyword in normalized for keyword in ["오늘몇일", "오늘날짜", "현재날짜", "지금날짜", "며칠", "몇월몇일", "whatdate", "todaydate"]):
            response = f"오늘 날짜는 {now.strftime('%Y년 %m월 %d일')}입니다."
        else:
            response = f"현재 날짜와 시간은 {now.strftime('%Y년 %m월 %d일 %H시 %M분')}입니다."

        return TurnResult(
            user_input=text,
            intent=intent,
            emotion=emotion,
            llm_response=response,
            elapsed=round(time.time() - start, 2),
            success=True,
            error="",
        )

    def _handle_system(self,
                       text: str,
                       intent: Intent,
                       emotion: Emotion,
                       start: float) -> TurnResult:
        response = "시스템 명령을 인식했습니다."
        if "종료" in text:
            response = "알겠어요. 종료할게요."
        elif "잠깐" in text or "멈춰" in text:
            response = "잠시 대기할게요."
        elif "재시작" in text:
            response = "재시작할게요."

        return TurnResult(
            user_input=text,
            intent=intent,
            emotion=emotion,
            llm_response=response,
            elapsed=round(time.time() - start, 3),
        )

    def _handle_memory_query(self,
                             text: str,
                             intent: Intent,
                             emotion: Emotion,
                             start: float) -> TurnResult:
        if self._memory is None:
            return TurnResult(
                user_input=text,
                intent=intent,
                emotion=emotion,
                llm_response="지금은 메모리 엔진이 연결되지 않아 기억을 확인할 수 없습니다.",
                elapsed=round(time.time() - start, 2),
                success=False,
                error="memory engine missing",
            )

        recalled = self._memory.recall_memory(text)
        if self._is_memory_repair_query(text):
            response = self._format_memory_repair_response(recalled)
        else:
            response = self._format_memory_response(recalled)
        return TurnResult(
            user_input=text,
            intent=intent,
            emotion=emotion,
            llm_response=response,
            elapsed=round(time.time() - start, 2),
            success=True,
            error="",
        )

    def _format_memory_response(self, recalled: dict[str, Any]) -> str:
        profile = recalled.get("user_profile", {})
        facts = recalled.get("known_facts", {})
        recent_turns = recalled.get("recent_turns", [])
        summaries = recalled.get("long_term_summaries", [])
        keywords = recalled.get("keywords", [])

        if not profile and not facts and not recent_turns and not summaries:
            return "아직 저장된 장기 기억이 많지 않습니다. 최근 대화나 학습된 사실이 더 쌓이면 기억해서 말씀드릴 수 있습니다."

        lines = []
        if keywords:
            lines.append(f"'{', '.join(keywords)}'와 관련해 기억나는 내용을 정리하면 이렇습니다.")
        else:
            lines.append("지금 저장돼 있는 기억을 기준으로 정리해보면 이렇습니다.")

        filtered_facts = {
            key: value for key, value in facts.items()
            if key not in {"last_user_message", "last_user_emotion"}
        }

        if profile:
            profile_text = ", ".join(f"{key}={value}" for key, value in profile.items())
            lines.append(f"사용자 정보: {profile_text}")

        if filtered_facts:
            fact_items = list(filtered_facts.items())[:5]
            fact_text = ", ".join(f"{key}={value}" for key, value in fact_items)
            lines.append(f"기억된 사실: {fact_text}")

        if summaries:
            summary_text = " | ".join(item["summary"] for item in summaries[:3])
            lines.append(f"장기 요약: {summary_text}")

        if recent_turns:
            recent_user_turns = [turn["content"] for turn in recent_turns if turn["role"] == "user"]
            if recent_user_turns:
                lines.append("최근 대화: " + " / ".join(recent_user_turns[-3:]))

        return "\n".join(lines)

    def _is_memory_repair_query(self, text: str) -> bool:
        lowered = text.lower()
        repair_markers = ["못해", "못하", "왜", "줬잖아", "했잖아", "방금", "기억 못"]
        return any(marker in lowered for marker in repair_markers)

    def _format_memory_repair_response(self, recalled: dict[str, Any]) -> str:
        recent_turns = recalled.get("full_recent_turns") or recalled.get("recent_turns", [])
        summaries = recalled.get("long_term_summaries", [])
        facts = recalled.get("known_facts", {})

        if not recent_turns and not summaries:
            return "맞아요. 방금 맥락을 충분히 못 잡았습니다. 아직 남아 있는 최근 대화가 적어서 정확히 짚지 못했어요."

        lines = ["맞아요. 방금 맥락을 제대로 이어받지 못했습니다."]

        user_turns = [turn["content"] for turn in recent_turns if turn.get("role") == "user"]
        ai_turns = [turn["content"] for turn in recent_turns if turn.get("role") != "user"]
        if user_turns:
            lines.append("제가 기억하고 있는 최근 사용자 요청은: " + " / ".join(user_turns[-2:]))
        if ai_turns:
            lines.append("최근 제 응답은: " + " / ".join(ai_turns[-2:]))

        repair_reason = self._infer_memory_repair_reason(recent_turns)
        if repair_reason:
            lines.append(repair_reason)

        recent_topic = facts.get("recent_topic")
        if recent_topic:
            lines.append(f"현재 잡힌 최근 주제는 '{recent_topic}'입니다.")

        if summaries:
            lines.append("장기 기억 요약에도 관련 맥락이 남아 있습니다: " + summaries[0]["summary"])

        lines.append("다음부터는 이런 경우 최근 요청과 제 직전 응답을 우선 비교해서 맥락을 이어가겠습니다.")
        return "\n".join(lines)

    def _infer_memory_repair_reason(self, recent_turns: list[dict[str, Any]]) -> str:
        user_turns = [turn for turn in recent_turns if turn.get("role") == "user"]
        last_user_turn = user_turns[-1] if user_turns else None
        previous_user_turn = user_turns[-2] if len(user_turns) >= 2 else None
        last_ai_turn = next((turn for turn in reversed(recent_turns) if turn.get("role") != "user"), None)
        if not last_user_turn or not last_ai_turn:
            return ""

        user_text = last_user_turn.get("content", "")
        previous_user_text = previous_user_turn.get("content", "") if previous_user_turn else ""
        ai_text = last_ai_turn.get("content", "")
        if not user_text or not ai_text:
            return ""

        target_user_text = previous_user_text if self._looks_like_memory_complaint(user_text) and previous_user_text else user_text

        if self._looks_like_story_request(target_user_text) and self._looks_like_datetime_answer(ai_text):
            return "문제는 사용자는 소설이나 창작 응답을 원했는데, 제가 직전 응답에서 날짜/시간 계열 맥락으로 잘못 흘렀다는 점입니다."

        if self._looks_like_generation_request(target_user_text) and self._looks_like_refusal_or_meta(ai_text):
            return "문제는 사용자의 요청을 실행형 질문으로 보지 않고, 설명이나 메타 응답으로 빗나가게 처리했다는 점입니다."

        user_keywords = self._extract_comparison_keywords(target_user_text)
        ai_keywords = self._extract_comparison_keywords(ai_text)
        if user_keywords and ai_keywords and user_keywords.isdisjoint(ai_keywords):
            return "문제는 직전 사용자 요청의 핵심 키워드와 제 응답 키워드가 거의 겹치지 않아, 문맥 정렬이 깨졌다는 점입니다."

        if user_keywords and not ai_keywords:
            return "문제는 사용자 요청의 핵심 의도를 제가 응답에 제대로 반영하지 못했다는 점입니다."

        return "문제는 최근 요청의 의도와 제 직전 응답이 충분히 맞물리지 않아, 문맥 회복 없이 답이 나갔다는 점입니다."

    def _looks_like_story_request(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in ["소설", "이야기", "창작", "써줘", "써 봐", "만들어줘"])

    def _looks_like_generation_request(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in ["보여", "써", "만들어", "생성", "말해줘", "해줘"])

    def _looks_like_memory_complaint(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in ["기억 못", "못해", "못하", "왜", "줬잖아", "했잖아"])

    def _looks_like_datetime_answer(self, text: str) -> bool:
        lowered = text.lower().replace(" ", "")
        return any(keyword in lowered for keyword in ["현재시간", "현재날짜", "오늘날짜", "몇시", "년", "월", "일", "시", "분"])

    def _looks_like_refusal_or_meta(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in ["요청", "명령", "설명", "기능", "할 수", "인식", "메타"])

    def _extract_comparison_keywords(self, text: str) -> set[str]:
        cleaned = re.sub(r"[^가-힣A-Za-z0-9\s]", " ", text.lower())
        stopwords = {
            "그냥", "정말", "너무", "조금", "이거", "저거", "방금", "최근", "지금",
            "해주세요", "해줘", "보여줘", "말해줘", "있어", "없어", "하는", "하고",
            "제가", "내가", "너가", "너는", "나는", "저는",
        }
        return {token for token in cleaned.split() if len(token) >= 2 and token not in stopwords}

    def _handle_web_search(self,
                           text: str,
                           query: str,
                           intent: Intent,
                           emotion: Emotion,
                           start: float) -> TurnResult:
        if self._search is None:
            result = TurnResult(
                user_input=text,
                intent=intent,
                emotion=emotion,
                llm_response="웹 검색 기능이 연결되지 않았습니다.",
                elapsed=round(time.time() - start, 2),
                success=False,
                error="search engine missing",
            )
            self._persist_turn(result, emotion.value)
            return result

        search_response = self._search.search(query)
        result = TurnResult(
            user_input=text,
            intent=intent,
            emotion=emotion,
            llm_response=search_response.format_text(),
            elapsed=round(time.time() - start, 2),
            success=search_response.success,
            error=search_response.error,
        )
        self._persist_turn(result, emotion.value)
        return result

    def _persist_turn(self, result: TurnResult, emotion_value: str):
        if not self._memory:
            return

        from memory_engine import QVal

        user_archive = self._memory.sql.push_turn("user", result.user_input, emotion=emotion_value, qstate=QVal.TRUE)
        ai_archive = self._memory.sql.push_turn("ai", result.llm_response, emotion="NEUTRAL", qstate=QVal.TRUE)
        self._memory.learn_from_turn(result.user_input, ai_response=result.llm_response, emotion=emotion_value)
        for archive_info in (user_archive, ai_archive):
            self._memory.upgrade_summary_with_llm(archive_info, self._llm)

    def _return_turn(self, result: TurnResult):
        if self.on_response:
            self.on_response(result)

        if self._main:
            from main_engine import Event
            self._main.emit(Event(
                source="dialogue_engine",
                target="main_engine",
                etype="TURN_COMPLETE",
                payload=result.to_dict(),
                priority=1,
            ))
            self._main.tick()

        debug_log(self.verbose, f"[DialogueEngine] 턴 완료 → {result.elapsed}초")

    def handle(self, event: Any):
        if event.etype == "DIALOGUE_INPUT":
            self.process(event.payload.get("input", ""))


if __name__ == "__main__":
    engine = DialogueEngine()
    tests = [
        "안녕! 오늘 어때?",
        "요즘 너무 피곤하고 슬퍼",
        "내일 날씨 어떻게 될까?",
        "음악 틀어줘",
        "저번에 내가 말했던 거 기억해?",
    ]

    for text in tests:
        intent = classify_intent(text)
        emotion = extract_emotion(text)
        print(f"입력: '{text}'")
        print(f"  의도: {intent.value} / 감정: {emotion.value}\n")
