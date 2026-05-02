"""
LLM CONNECTOR
─────────────────────────────────────────────
Configurable Ollama-compatible chat connector
- 스트리밍 / 일반 응답
- 프롬프트 템플릿 관리
- 타임아웃 / 폴백 처리
- 메인엔진 이벤트 핸들러 포함
─────────────────────────────────────────────
"""

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlparse, urlunparse

import requests

from app_settings import DEFAULT_LLM_MODEL, DEFAULT_LLM_URL
from runtime_logging import debug_log


# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────

TIMEOUT_SEC = 90
MAX_RETRIES = 2


def resolve_timeout_sec() -> int:
    from os import getenv

    raw_value = getenv("WINAI_LLM_TIMEOUT_SEC")
    if not raw_value:
        return TIMEOUT_SEC
    try:
        return max(5, int(raw_value))
    except ValueError:
        return TIMEOUT_SEC


def resolve_llm_url() -> str:
    from os import getenv

    return getenv("WINAI_LLM_URL") or getenv("OLLAMA_HOST") or DEFAULT_LLM_URL


def resolve_model_name() -> str:
    from os import getenv

    return getenv("WINAI_LLM_MODEL") or DEFAULT_LLM_MODEL


# ─────────────────────────────────────────
# 1. 응답 객체
# ─────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    model: str
    elapsed: float
    success: bool = True
    error: str = ""
    tokens_used: int = 0


@dataclass
class LLMConnectionStatus:
    configured_url: str
    model: str
    connected: bool
    reachable_url: str = ""
    response_port: int | None = None
    error: str = ""
    installed_models: list[str] = field(default_factory=list)
    alternate_url: str = ""
    alternate_response_port: int | None = None
    alternate_models: list[str] = field(default_factory=list)
    alternate_model_found: bool = False


# ─────────────────────────────────────────
# 2. 프롬프트 템플릿
# ─────────────────────────────────────────

class PromptTemplate:
    """
    시스템 프롬프트 + 대화 컨텍스트 조립
    memory_engine.collect_context() 결과를 받아 프롬프트 구성
    """

    SYSTEM_BASE = """당신은 사용자와 함께 생활하는 AI 동반자입니다.
자연스럽고 따뜻하게 대화하며, 사용자의 감정과 상황을 세심하게 파악합니다.
짧고 명확하게 답하되, 필요할 때는 깊이 있게 설명합니다."""

    LANGUAGE_RULES = """[언어 규칙]
- 모든 응답은 기본적으로 자연스러운 한국어로만 작성하세요.
- 중국어(간체자, 번체자, 중국어 어휘/문장)를 사용하지 마세요.
- 사용자가 중국어로 입력해도 답변은 한국어로 유지하세요.
- 사용자가 번역을 명시적으로 요청한 경우에만 예시로 중국어를 포함할 수 있습니다."""

    @staticmethod
    def build(user_input: str,
              context: Optional[dict[str, Any]] = None,
              system_override: Optional[str] = None) -> list[dict[str, str]]:
        """
        Ollama messages 형식으로 프롬프트 조립
        context: memory_engine.collect_context() 결과
        """
        messages: list[dict[str, str]] = []

        system = system_override or PromptTemplate.SYSTEM_BASE
        system = f"{system}\n\n{PromptTemplate.LANGUAGE_RULES}"

        if context and context.get("user_profile"):
            profile = context["user_profile"]
            profile_str = ", ".join(f"{k}={v}" for k, v in profile.items())
            system += f"\n\n[사용자 정보] {profile_str}"

        if context and context.get("known_facts"):
            facts = context["known_facts"]
            facts_str = ", ".join(f"{k}={v}" for k, v in facts.items())
            system += f"\n[기억된 사실] {facts_str}"

        if context and context.get("long_term_summaries"):
            summaries = context["long_term_summaries"]
            summary_lines = [item["summary"] for item in summaries if item.get("summary")]
            if summary_lines:
                system += "\n[장기 기억 요약] " + " | ".join(summary_lines)

        if context and context.get("cache_snapshot"):
            snap = context["cache_snapshot"]
            if "emotion" in snap:
                system += f"\n[현재 감정 상태] {snap['emotion']['value']}"
            if "focus" in snap:
                system += f"\n[현재 집중 대상] {snap['focus']['value']}"

            if context and context.get("system_time"):
                system_time = context["system_time"]
                system += f"\n[현재 시각] {system_time.get('display', '')}"
                system += f"\n[시간 규칙] 시간이나 날짜 질문에는 위 현재 시각을 기준으로 답하세요. 모른다고 하지 마세요."

        messages.append({"role": "system", "content": system})

        if context and context.get("recent_turns"):
            for turn in context["recent_turns"]:
                role = "user" if turn["role"] == "user" else "assistant"
                messages.append({"role": role, "content": turn["content"]})

        messages.append({"role": "user", "content": user_input})
        return messages


# ─────────────────────────────────────────
# 3. LLM 연결 모듈
# ─────────────────────────────────────────

class LLMConnector:
    def __init__(self,
                 url: Optional[str] = None,
                 model: Optional[str] = None,
                 verbose: bool = True):
        self.verbose = verbose
        self.url = url or resolve_llm_url()
        self.model = model or resolve_model_name()
        self.timeout_sec = resolve_timeout_sec()
        self._lock = threading.Lock()
        debug_log(self.verbose, f"[LLMConnector] 초기화 — {self.model} @ {self.url}")

    def ping(self, quiet: bool = False) -> bool:
        status = self.inspect_connection(timeout_sec=3)
        if status.connected:
            debug_log(self.verbose and not quiet, f"[LLMConnector] 연결 OK — {self.model} 확인 @ {status.reachable_url}")
            return True

        if status.alternate_model_found:
            debug_log(
                self.verbose and not quiet,
                f"[LLMConnector] 설정 포트 연결 실패, 대체 포트에서 모델 발견 — {status.alternate_url}",
            )
        else:
            debug_log(self.verbose and not quiet, f"[LLMConnector] Ollama 연결 실패: {status.error}")
        return False

    def inspect_connection(self, timeout_sec: int = 3) -> LLMConnectionStatus:
        status = LLMConnectionStatus(
            configured_url=self.url,
            model=self.model,
            connected=False,
        )

        try:
            models = self._fetch_models(self.url, timeout_sec)
            status.reachable_url = self.url
            status.response_port = self._extract_port(self.url)
            status.installed_models = models
            if self.model in models:
                status.connected = True
                return status
            status.error = f"설정 포트에 요청 모델이 없습니다: {self.model}"
        except Exception as error:
            status.error = str(error)

        for candidate_url in self._candidate_urls():
            try:
                candidate_models = self._fetch_models(candidate_url, timeout_sec)
            except Exception:
                continue

            status.alternate_url = candidate_url
            status.alternate_response_port = self._extract_port(candidate_url)
            status.alternate_models = candidate_models
            status.alternate_model_found = self.model in candidate_models
            break

        return status

    def _fetch_models(self, base_url: str, timeout_sec: int) -> list[str]:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout_sec)
        response.raise_for_status()
        return [model["name"] for model in response.json().get("models", [])]

    def _candidate_urls(self) -> list[str]:
        parsed = urlparse(self.url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        current_port = parsed.port
        path = parsed.path.rstrip("/")
        candidates: list[str] = []

        for port in (11434, 11435):
            if port == current_port:
                continue
            netloc = f"{host}:{port}"
            candidates.append(urlunparse((scheme, netloc, path, "", "", "")))

        return candidates

    def _extract_port(self, url: str) -> int | None:
        parsed = urlparse(url)
        return parsed.port

    def chat(self,
             user_input: str,
             context: Optional[dict[str, Any]] = None,
             system_override: Optional[str] = None) -> LLMResponse:
        messages = PromptTemplate.build(user_input, context, system_override)
        start = time.time()
        target_url = self._resolve_chat_url()

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    f"{target_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": 0.75,
                            "top_p": 0.9,
                            "num_ctx": 4096,
                        },
                    },
                    timeout=self.timeout_sec,
                )
                data = response.json()
                text = data["message"]["content"].strip()
                return LLMResponse(
                    text=text,
                    model=self.model,
                    elapsed=round(time.time() - start, 2),
                    tokens_used=data.get("eval_count", 0),
                )
            except requests.Timeout:
                debug_log(self.verbose, f"[LLMConnector] 타임아웃 (시도 {attempt + 1}/{MAX_RETRIES})")
                if attempt == MAX_RETRIES - 1:
                    return self._fallback("응답 시간이 초과되었습니다.", start)
            except Exception as error:
                debug_log(self.verbose, f"[LLMConnector] 오류: {error}")
                return self._fallback(str(error), start)

        return self._fallback("알 수 없는 오류", start)

    def chat_stream(self,
                    user_input: str,
                    context: Optional[dict[str, Any]] = None,
                    on_token: Optional[Callable[[str], None]] = None) -> LLMResponse:
        """
        on_token: 토큰 수신 시 콜백 (UI 실시간 출력용)
        """
        messages = PromptTemplate.build(user_input, context)
        full_text: list[str] = []
        start = time.time()
        target_url = self._resolve_chat_url()

        try:
            with requests.post(
                f"{target_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {"temperature": 0.75, "num_ctx": 4096},
                },
                timeout=self.timeout_sec,
                stream=True,
            ) as response:
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        full_text.append(token)
                        if on_token:
                            on_token(token)
                    if chunk.get("done"):
                        break

            return LLMResponse(
                text="".join(full_text).strip(),
                model=self.model,
                elapsed=round(time.time() - start, 2),
            )
        except Exception as error:
            debug_log(self.verbose, f"[LLMConnector] 스트림 오류: {error}")
            return self._fallback(str(error), start)

    def _resolve_chat_url(self) -> str:
        status = self.inspect_connection(timeout_sec=3)
        if status.connected and status.reachable_url:
            return status.reachable_url
        if status.alternate_model_found and status.alternate_url:
            debug_log(self.verbose, f"[LLMConnector] 채팅 요청을 대체 포트로 우회: {status.alternate_url}")
            return status.alternate_url
        return self.url

    def _fallback(self, reason: str, start: float) -> LLMResponse:
        return LLMResponse(
            text="잠시 생각이 필요해요. 다시 말씀해 주실 수 있나요?",
            model=self.model,
            elapsed=round(time.time() - start, 2),
            success=False,
            error=reason,
        )

    def handle(self, event: Any):
        event_type = event.etype
        payload = event.payload

        if event_type == "LLM_CHAT":
            response = self.chat(
                user_input=payload.get("input", ""),
                context=payload.get("context"),
            )
            callback = payload.get("callback")
            if callback:
                callback(response)
        elif event_type == "LLM_PING":
            self.ping()


if __name__ == "__main__":
    llm = LLMConnector()

    if llm.ping():
        response = llm.chat("안녕! 오늘 기분이 어때?")
        print(f"\n[응답] {response.text}")
        print(f"[정보] {response.elapsed}초 / {response.tokens_used} 토큰")

        print("\n[스트리밍 테스트]")
        stream_response = llm.chat_stream(
            "짧게 자기소개 해줘",
            on_token=lambda token: print(token, end="", flush=True),
        )
        print(f"\n[완료] {stream_response.elapsed}초")
    else:
        print("Ollama 서버를 먼저 실행해주세요: ollama serve")
