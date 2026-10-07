# SPDX-License-Identifier: AGPL-3.0-or-later
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mcp_url: str
    mcp_token: str = ""
    mcp_binding: str = ""
    connectors: tuple[str, ...] = ("paystack-pay", "send-money", "airtime", "food-order", "memory")
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "openai.gpt-oss-120b"
    reasoning_effort: str = "low"
    llm_timeout_seconds: int = 60
    round_deadline_seconds: int = 120
    max_tool_rounds: int = 6
    model_calls_per_day: int = 0
    visitor_model_calls_per_day: int = 0
    flush_seconds: float = 0.15
    watchdog_seconds: int = 30
    max_idle_resumes: int = 3
    """Resumes in a row that a turn may take without a reply or a tool result in between."""
    resume_window_seconds: int = 30
    """Resumes this close together count as one."""
    no_progress_seconds: int = 300
    max_alarm_strikes: int = 3
    """Watchdog alarms in a row that find the log unchanged and no loop running, before the alarm stops."""
    tool_deadline_seconds: float = 45
    context_window_tokens: int = 32000
    compact_at: float = 0.6
    keep_recent_tokens: int = 6000
    compaction_timeout_seconds: int = 45
    stream_usage: bool = True
    public_base_url: str = ""
    events_secret: str = ""
    pact_agent_key: str = ""
    pact_reach: str = ""

    @classmethod
    def from_env(cls, read: Callable[[str], str | None]) -> Settings:
        def text(name: str, default: str) -> str:
            return read(name) or default

        def number(name: str, default: int) -> int:
            value = read(name)
            return default if value in (None, "") else int(value)

        def fraction(name: str, default: float) -> float:
            value = read(name)
            return default if value in (None, "") else float(value)

        names = text("CONNECTORS", ",".join(cls.connectors))
        connectors = tuple(c.strip() for c in names.split(",") if c.strip())
        return cls(
            mcp_url=text("CHECKOUT_MCP_URL", "http://localhost:8787").rstrip("/"),
            mcp_token=text("CHECKOUT_MCP_TOKEN", ""),
            mcp_binding=text("CHECKOUT_MCP_BINDING", ""),
            connectors=connectors,
            llm_base_url=text("LLM_BASE_URL", ""),
            llm_api_key=text("LLM_API_KEY", ""),
            llm_model=text("LLM_MODEL", cls.llm_model),
            reasoning_effort=text("LLM_REASONING_EFFORT", cls.reasoning_effort),
            llm_timeout_seconds=number("LLM_TIMEOUT_SECONDS", cls.llm_timeout_seconds),
            round_deadline_seconds=number("LLM_ROUND_DEADLINE_SECONDS", cls.round_deadline_seconds),
            tool_deadline_seconds=fraction("TOOL_DEADLINE_SECONDS", cls.tool_deadline_seconds),
            max_tool_rounds=number("MAX_TOOL_ROUNDS", cls.max_tool_rounds),
            model_calls_per_day=number("MODEL_CALLS_PER_DAY", 0),
            visitor_model_calls_per_day=number("VISITOR_MODEL_CALLS_PER_DAY", 0),
            watchdog_seconds=number("WATCHDOG_SECONDS", cls.watchdog_seconds),
            context_window_tokens=number("CONTEXT_WINDOW_TOKENS", cls.context_window_tokens),
            compact_at=fraction("COMPACT_AT", cls.compact_at),
            keep_recent_tokens=number("KEEP_RECENT_TOKENS", cls.keep_recent_tokens),
            compaction_timeout_seconds=number("COMPACTION_TIMEOUT_SECONDS", cls.compaction_timeout_seconds),
            stream_usage=text("LLM_STREAM_USAGE", "1") != "0",
            public_base_url=text("PUBLIC_BASE_URL", ""),
            events_secret=text("EVENTS_SECRET", ""),
            pact_agent_key=text("PACT_AGENT_KEY", ""),
            pact_reach=text("PACT_REACH", ""),
        )

    @property
    def reaches(self) -> bool:
        """Whether 234 acts for people at other Brands (turns/reach/): its key and their list are set."""
        return bool(self.public_base_url and self.pact_agent_key and self.pact_reach)

    @property
    def offered_connectors(self) -> tuple[str, ...]:
        """The connectors the model is told about: the remote ones, and `brands` when 234 reaches others."""
        return (*self.connectors, "brands") if self.reaches else self.connectors

    @property
    def compact_threshold_tokens(self) -> int:
        return int(self.context_window_tokens * self.compact_at)

    def model_problem(self) -> str | None:
        """Why no turn can run, or None. The host offers nothing that stands in for a model, and never
        a Claude model."""
        if not self.llm_base_url or not self.llm_api_key:
            return "No model is configured. Set LLM_BASE_URL and LLM_API_KEY."
        if any(word in self.llm_model.lower() for word in ("claude", "anthropic")):
            return "A Claude model is not used here. Set LLM_MODEL to another model."
        return None
