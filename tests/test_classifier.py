from core.inference.ollama import OllamaResult, OllamaUnavailable
from core.router.classifier import HeuristicClassifier, ModelClassifier


async def test_heuristic_critical_keywords():
    classifier = HeuristicClassifier()
    for text in ["what's my password again?", "transfer money to my account",
                 "run this: rm -rf /tmp/x", "store this api key"]:
        assert (await classifier.classify(text)).label == "critical", text


async def test_heuristic_trivial_short_question():
    result = await HeuristicClassifier().classify("What time is it in Lagos?")
    assert result.label == "trivial"


async def test_heuristic_complex_code_or_long():
    classifier = HeuristicClassifier()
    assert (await classifier.classify("```python\nprint('hi')\n```")).label == "complex"
    assert (await classifier.classify("x" * 900)).label == "complex"


class _FakeOllama:
    def __init__(self, reply=None, up=True):
        self._reply = reply
        self._up = up

    async def chat(self, model, messages):
        if not self._up:
            raise OllamaUnavailable("down")
        return OllamaResult(content=self._reply, model=model,
                            prompt_tokens=1, completion_tokens=1)


async def test_model_classifier_uses_local_model():
    classifier = ModelClassifier(_FakeOllama("complex"), "m", HeuristicClassifier())
    result = await classifier.classify("please summarize my week")
    assert result.label == "complex"
    assert "local model" in result.reason


_ROUTINE_PROMPT = ("Draft a short note to my landlord about the leaking kitchen tap "
                   "and politely ask for a repair visit sometime this coming week.")


async def test_model_classifier_falls_back_when_down():
    classifier = ModelClassifier(_FakeOllama(up=False), "m", HeuristicClassifier())
    result = await classifier.classify(_ROUTINE_PROMPT)
    assert result.label == "routine"  # heuristic default


async def test_model_classifier_ignores_garbage_label():
    classifier = ModelClassifier(_FakeOllama("banana"), "m", HeuristicClassifier())
    assert (await classifier.classify(_ROUTINE_PROMPT)).label == "routine"


async def test_critical_is_sticky_over_model_opinion():
    # model says trivial, heuristic says critical → critical wins (§5.2)
    classifier = ModelClassifier(_FakeOllama("trivial"), "m", HeuristicClassifier())
    assert (await classifier.classify("rotate my api key")).label == "critical"
