"""Cost accounting.

"Measure it on lecture one. ASR plus generation for a 90-minute class."
Every run prints this. You need the number before any pricing conversation,
and a number you have to go and calculate later is a number you won't have.

Rates are USD and go stale — check them before quoting anyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

USD_TO_INR = 88.0  # indicative; update before using in a deck

# Per hour of audio.
ASR_RATES_PER_HOUR = {
    "whisper-large-v3-turbo": 0.04,
    "whisper-large-v3": 0.111,
}

# (input, output) USD per million tokens.
LLM_RATES_PER_MTOK = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "fake-deterministic-v0": (0.0, 0.0),
}


@dataclass
class CostLedger:
    audio_seconds: float = 0.0
    asr_model: str = ""
    llm_calls: list[tuple[str, int, int]] = field(default_factory=list)
    unpriced: set[str] = field(default_factory=set)

    def record_asr(self, seconds: float, model: str) -> None:
        self.audio_seconds += seconds
        self.asr_model = model

    def record_llm(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.llm_calls.append((model, input_tokens, output_tokens))

    def _match_rate(self, model: str) -> tuple[float, float] | None:
        if model in LLM_RATES_PER_MTOK:
            return LLM_RATES_PER_MTOK[model]
        for known, rate in LLM_RATES_PER_MTOK.items():
            if model.startswith(known):
                return rate
        return None

    @property
    def asr_usd(self) -> float:
        rate = ASR_RATES_PER_HOUR.get(self.asr_model)
        if rate is None:
            if self.asr_model:
                self.unpriced.add(self.asr_model)
            return 0.0
        return (self.audio_seconds / 3600.0) * rate

    @property
    def llm_usd(self) -> float:
        total = 0.0
        for model, inp, out in self.llm_calls:
            rate = self._match_rate(model)
            if rate is None:
                self.unpriced.add(model)
                continue
            total += (inp / 1_000_000) * rate[0] + (out / 1_000_000) * rate[1]
        return total

    @property
    def total_usd(self) -> float:
        return self.asr_usd + self.llm_usd

    def summary(self) -> str:
        asr, llm, total = self.asr_usd, self.llm_usd, self.total_usd
        in_tok = sum(c[1] for c in self.llm_calls)
        out_tok = sum(c[2] for c in self.llm_calls)
        asr_line = (
            f"  ASR         {self.audio_seconds / 60:6.1f} min audio"
            f"  ({self.asr_model})       ${asr:.4f}"
            if self.audio_seconds
            else "  ASR         skipped — reused an existing transcript      $0.0000"
        )
        lines = [
            "Cost for this session",
            asr_line,
            f"  Generation  {in_tok:,} in / {out_tok:,} out tokens"
            f" over {len(self.llm_calls)} call(s)   ${llm:.4f}",
            f"  Total                                            "
            f"       ${total:.4f}  (~Rs {total * USD_TO_INR:.2f})",
        ]
        if self.unpriced:
            lines.append(
                f"  note: no rate on file for {', '.join(sorted(self.unpriced))}"
                " — excluded from the total."
            )
        weekly = total * 5 * 4
        lines.append(
            f"  At 5 sessions/week, one section costs ~${weekly:.2f}"
            f" (~Rs {weekly * USD_TO_INR:.0f}) a month."
        )
        return "\n".join(lines)
