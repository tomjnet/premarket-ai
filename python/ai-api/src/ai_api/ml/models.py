"""The classic ML baseline, run before the LLM judge (CPU, no GPU needed).

- **FinBERT** (``ProsusAI/finbert``): financial sentiment of the story
  (positive, negative, neutral), next to the LLM's sentiment.
- **DistilBERT verdict classifier**: ``distilbert-base-uncased`` fine-tuned
  on labeled vendor-sim feeds (``ai-api ml-train``, seeds other than the
  golden set's 42), predicting the four verdicts from the text alone.

Both are evidence for the analyst and numbers for the "rules vs classic ML
vs LLM" comparison in the eval; neither decides a verdict. torch and
transformers are only in the worker and eval images, and are imported
when a model is first used: the API never loads them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import dataclasses
import json
import logging
import pathlib
import threading
from typing import Any

_log = logging.getLogger(__name__)
FINBERT = "ProsusAI/finbert"
BASE_MODEL = "distilbert-base-uncased"
VERDICT_DIR = "distilbert-verdict"
LABELS = ("VERIFIED", "UNVERIFIED", "MISLEADING", "FAKE")
MAX_TOKENS = 256


def text_of(headline: str, body: str) -> str:
    """The model input: headline and story, without vendor markers."""
    headline = headline.replace("[SYNTHETIC]", "").strip()
    return f"{headline}. {body}"


@dataclasses.dataclass(frozen=True)
class Prediction:
    """One model's answer for one item.

    Attributes:
        label: The most likely label.
        score: Its probability.
        scores: Every label's probability.
    """

    label: str
    score: float
    scores: dict[str, float]

    def to_json(self) -> dict[str, Any]:
        """The prediction as the graph state carries it."""
        return dataclasses.asdict(self)


class _Model:
    """A sequence classifier loaded on first use (thread-safe)."""

    def __init__(self, source: str, cache_dir: pathlib.Path) -> None:
        self._source = source
        self._cache_dir = cache_dir
        self._lock = threading.Lock()
        self._loaded: tuple[Any, Any] | None = None

    def _load(self) -> tuple[Any, Any]:
        with self._lock:
            if self._loaded is None:
                import torch  # noqa: PLC0415 - worker and eval images only.
                import transformers  # noqa: PLC0415

                torch.set_num_threads(2)
                tokenizer = transformers.AutoTokenizer.from_pretrained(
                    self._source, cache_dir=self._cache_dir
                )
                model = (
                    transformers.AutoModelForSequenceClassification
                ).from_pretrained(self._source, cache_dir=self._cache_dir)
                model.eval()
                self._loaded = (tokenizer, model)
                _log.info("loaded %s", self._source)
        return self._loaded

    def predict(self, texts: Sequence[str]) -> list[Prediction]:
        import torch  # noqa: PLC0415

        tokenizer, model = self._load()
        labels = [
            model.config.id2label[i] for i in range(model.config.num_labels)
        ]
        batch = tokenizer(
            list(texts),
            truncation=True,
            max_length=MAX_TOKENS,
            padding=True,
            return_tensors="pt",
        )
        with torch.no_grad():
            probs = torch.softmax(model(**batch).logits, dim=-1).tolist()
        found = []
        for row in probs:
            scores = {
                str(label).upper(): round(p, 4)
                for label, p in zip(labels, row, strict=True)
            }
            best = max(scores, key=scores.get)
            found.append(Prediction(best, scores[best], scores))
        return found


class Baseline:
    """FinBERT sentiment and the DistilBERT verdict classifier."""

    def __init__(self, model_dir: pathlib.Path) -> None:
        """Uses ``model_dir`` (ML_MODEL_DIR): downloads and the trained model.

        Args:
            model_dir: Holds ``distilbert-verdict/`` (after training) and
                the Hugging Face download cache.
        """
        cache = model_dir / "hf-cache"
        self._finbert = _Model(FINBERT, cache)
        verdict_dir = model_dir / VERDICT_DIR
        self._verdict = None
        self.trained = (verdict_dir / "config.json").exists()
        if self.trained:
            self._verdict = _Model(str(verdict_dir), cache)
            info = verdict_dir / "training.json"
            if info.exists():
                meta = json.loads(info.read_text(encoding="utf-8"))
                _log.info(
                    "DistilBERT verdict model: held-out accuracy %s",
                    meta.get("held_out_accuracy"),
                )

    def _predict(
        self, headline: str, body: str
    ) -> tuple[Prediction, Prediction | None]:
        text = text_of(headline, body)
        sentiment = self._finbert.predict([text])[0]
        verdict = None
        if self._verdict is not None:
            verdict = self._verdict.predict([text])[0]
        return sentiment, verdict

    async def predict(
        self, headline: str, body: str
    ) -> tuple[Prediction, Prediction | None]:
        """FinBERT's sentiment and the classifier's verdict (None: untrained).

        Runs in a thread: inference is CPU-bound and must not block the
        worker's event loop.
        """
        return await asyncio.to_thread(self._predict, headline, body)

    def predict_verdicts(self, texts: Sequence[str]) -> list[Prediction]:
        """The classifier's verdicts for many texts (the eval).

        Raises:
            RuntimeError: The classifier isn't trained yet.
        """
        if self._verdict is None:
            raise RuntimeError("no trained model: make -C python ml-train")
        return self._verdict.predict(texts)
