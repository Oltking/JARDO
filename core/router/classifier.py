"""Task classifier (spec §5.1): labels each step trivial|routine|complex|critical.

Two implementations behind one interface:
- HeuristicClassifier: deterministic rules, zero dependencies — always available,
  used until a local small model is installed (and as its fallback).
- ModelClassifier: local small model via Ollama (the spec's target); falls back
  to heuristics whenever Ollama is down or answers garbage. Never remote — the
  classifier itself must cost ~nothing.

`critical` is sticky by design (§5.2): security verdicts, code that will be
executed, anything touching money/credentials. False positives here cost cents;
false negatives cost trust.
"""

import re
from dataclasses import dataclass

from core.inference.ollama import OllamaClient, OllamaUnavailable

LABELS = ("trivial", "routine", "complex", "critical")

_CRITICAL_PATTERNS = re.compile(
    r"password|credential|secret|api.?key|token|wallet|bank|payment|pay\b|money|"
    r"transfer|delete|rm -rf|drop table|sudo|deploy|production|execute|run this",
    re.IGNORECASE,
)
_CODE_HINT = re.compile(r"```|def |class |import |function |SELECT .* FROM", re.IGNORECASE)


@dataclass
class TaskClass:
    label: str
    modality: str  # "text" (vision arrives Phase 7)
    reason: str


class HeuristicClassifier:
    async def classify(self, text: str) -> TaskClass:
        if _CRITICAL_PATTERNS.search(text):
            return TaskClass("critical", "text", "matched critical keyword pattern")
        if _CODE_HINT.search(text) or len(text) > 800:
            return TaskClass("complex", "text", "code content or long prompt")
        if len(text) < 80 and text.count("?") <= 1:
            return TaskClass("trivial", "text", "short single question")
        return TaskClass("routine", "text", "default")


_MODEL_PROMPT = """\
Classify the task into exactly one label: trivial, routine, complex, critical.
critical = security decisions, code that will be executed, money/credentials.
complex = multi-step reasoning, code writing, long analysis.
trivial = greetings, single-fact questions. routine = everything else.
Reply with ONLY the label."""


class ModelClassifier:
    def __init__(self, ollama: OllamaClient, model: str, fallback: HeuristicClassifier):
        self._ollama = ollama
        self._model = model
        self._fallback = fallback

    async def classify(self, text: str) -> TaskClass:
        heuristic = await self._fallback.classify(text)
        if heuristic.label == "critical":
            return heuristic  # sticky: a model may not downgrade critical
        try:
            result = await self._ollama.chat(
                self._model,
                [{"role": "system", "content": _MODEL_PROMPT},
                 {"role": "user", "content": text[:4000]}],
            )
            label = result.content.strip().lower().split()[0].strip(".,")
            if label in LABELS:
                return TaskClass(label, "text", f"local model {self._model}")
        except (OllamaUnavailable, IndexError):
            pass
        return heuristic
