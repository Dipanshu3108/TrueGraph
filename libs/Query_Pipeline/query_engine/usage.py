"""Usage tracking for the Query Pipeline.

Mirrors the pattern in Knowledge_Builder/knowledge_builder/extraction.py.
One UsageTracker is created per ask() call; it accumulates token counts from
both LLM stages (understanding + generation) and writes a single human-readable
log when the pipeline finishes.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

USAGE_DIR = Path(__file__).resolve().parent.parent / "Usage"
"""Default directory where per-query usage logs are written."""


@dataclass(frozen=True)
class UsageCall:
    """Token usage for a single LLM completion."""

    call_number: int
    model: str
    provider: Optional[str]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp: str


class UsageTracker:
    """Accumulate LLM usage across pipeline calls and persist a human-readable log."""

    def __init__(self, document_name: str, usage_dir: Optional[str] = None) -> None:
        self.document_name = document_name
        self.calls: list[UsageCall] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0
        self._usage_dir = Path(usage_dir) if usage_dir else USAGE_DIR

    def record(
        self,
        *,
        model: str,
        provider: Optional[str],
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record one LLM completion's token usage."""
        self.total_calls += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.calls.append(
            UsageCall(
                call_number=self.total_calls,
                model=model,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                timestamp=datetime.now().isoformat(),
            )
        )

    def write_log(self) -> Path:
        """Write accumulated usage to Usage/Usage_<document>.log.

        Returns the path of the written log file.
        """
        self._usage_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(self.document_name).stem)
        log_path = self._usage_dir / f"Usage_{safe_stem}.log"

        with log_path.open("w", encoding="utf-8") as handle:
            first_model = self.calls[0].model if self.calls else "unknown"
            first_provider = (self.calls[0].provider or "unknown") if self.calls else "unknown"

            handle.write(f"Document: {self.document_name}\n")
            handle.write(f"Model: {first_model}\n")
            handle.write(f"Provider: {first_provider}\n")
            handle.write(f"Total LLM Calls: {self.total_calls}\n")
            handle.write(f"Total Input Tokens: {self.total_input_tokens}\n")
            handle.write(f"Total Output Tokens: {self.total_output_tokens}\n")
            handle.write(f"Total Tokens: {self.total_input_tokens + self.total_output_tokens}\n")
            handle.write("Per-Call Usage:\n")

            for call in self.calls:
                handle.write(f"  Call {call.call_number}:\n")
                handle.write(f"    Timestamp: {call.timestamp}\n")
                handle.write(f"    Model: {call.model}\n")
                handle.write(f"    Provider: {call.provider or 'unknown'}\n")
                handle.write(f"    Input Tokens: {call.input_tokens}\n")
                handle.write(f"    Output Tokens: {call.output_tokens}\n")
                handle.write(f"    Total Tokens: {call.total_tokens}\n")

        logger.info("Usage log written: %s", log_path)
        return log_path
