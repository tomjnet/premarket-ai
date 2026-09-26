"""``ai-api ml-train``: fine-tune DistilBERT on labeled vendor-sim feeds.

The training feeds come from vendor-sim's generator with seeds 1 to 5
(never 42, the golden set the evals score), 10 days each; seed 6 is held
out to report accuracy. Every item's label is the verdict vendor-sim
expects (a duplicate's is its original's). A plain PyTorch loop (2
epochs, 256 tokens, batch 16) takes a few minutes on the CPU.

Caveat worth saying out loud: vendor-sim writes from templates, so the
classifier mostly learns them. Its score here is an upper bound; real news
would need real labels (the analysts' overrides, ``ai.eval_example``).

Only the ``ai-eval`` image has vendor-sim's generator and torch; the model
is written to ML_MODEL_DIR (the ``ml-models`` volume) for the worker.
"""

from __future__ import annotations

import datetime
import json
import logging
import pathlib
import random
import tempfile
import time
from typing import Any

from ai_api.dedup import normalize
from ai_api.ml import models

_log = logging.getLogger(__name__)
TRAIN_SEEDS = (1, 2, 3, 4, 5)
HELD_OUT_SEED = 6
GOLDEN_SEED = 42
_FIRST_DAY = datetime.date(2026, 6, 1)
_DAYS = 10
_EPOCHS = 2
_BATCH = 16
_LEARNING_RATE = 5e-5


def examples(seed: int, days: int = _DAYS) -> list[tuple[str, int]]:
    """(text, label index) pairs of ``days`` feeds of one seed.

    Args:
        seed: The vendor-sim seed (never the golden set's).
        days: How many feed dates, from 2026-06-01.

    Returns:
        The examples.

    Raises:
        ValueError: ``seed`` is the golden set's.
    """
    if seed == GOLDEN_SEED:
        raise ValueError("seed 42 is the golden set: never train on it")
    from vendor_sim import generator  # noqa: PLC0415 - eval image only.

    found = []
    for offset in range(days):
        day = _FIRST_DAY + datetime.timedelta(days=offset)
        feed = generator.generate_feed(day, seed)
        for item, label in zip(feed.items, feed.labels, strict=True):
            headline, body = normalize.strip_boilerplate(
                item.headline, item.body
            )
            found.append(
                (
                    models.text_of(headline, body),
                    models.LABELS.index(label.expected_verdict),
                )
            )
    return found


def _accuracy(model: Any, tokenizer: Any, data: list[tuple[str, int]]) -> float:
    import torch  # noqa: PLC0415

    model.eval()
    right = 0
    with torch.no_grad():
        for start in range(0, len(data), 64):
            batch = data[start : start + 64]
            encoded = tokenizer(
                [text for text, _ in batch],
                truncation=True,
                max_length=models.MAX_TOKENS,
                padding=True,
                return_tensors="pt",
            )
            predicted = model(**encoded).logits.argmax(dim=-1).tolist()
            right += sum(
                1 for p, (_, y) in zip(predicted, batch, strict=True) if p == y
            )
    return right / len(data) if data else 0.0


def train(model_dir: pathlib.Path, epochs: int = _EPOCHS) -> dict[str, Any]:
    """Fine-tunes the verdict classifier and saves it.

    Args:
        model_dir: ML_MODEL_DIR; the model goes to ``distilbert-verdict``.
        epochs: Passes over the training data.

    Returns:
        What ``training.json`` records (sizes, accuracy, time).
    """
    import torch  # noqa: PLC0415
    import transformers  # noqa: PLC0415

    started = time.monotonic()
    torch.manual_seed(0)
    rng = random.Random(0)
    data = [e for seed in TRAIN_SEEDS for e in examples(seed)]
    rng.shuffle(data)
    held_out = examples(HELD_OUT_SEED)
    # The base model's download stays out of the shared volume, which the
    # worker (another user) owns.
    cache = pathlib.Path(tempfile.gettempdir()) / "hf"
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        models.BASE_MODEL, cache_dir=cache
    )
    model = transformers.AutoModelForSequenceClassification.from_pretrained(
        models.BASE_MODEL,
        cache_dir=cache,
        num_labels=len(models.LABELS),
        id2label=dict(enumerate(models.LABELS)),
        label2id={label: i for i, label in enumerate(models.LABELS)},
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=_LEARNING_RATE)
    steps = 0
    for epoch in range(epochs):
        model.train()
        rng.shuffle(data)
        for start in range(0, len(data), _BATCH):
            batch = data[start : start + _BATCH]
            encoded = tokenizer(
                [text for text, _ in batch],
                truncation=True,
                max_length=models.MAX_TOKENS,
                padding=True,
                return_tensors="pt",
            )
            labels = torch.tensor([y for _, y in batch])
            loss = model(**encoded, labels=labels).loss
            loss.backward()
            optimizer.step()
            optimizer.zero_grad()
            steps += 1
            if steps % 50 == 0:
                _log.info(
                    "epoch %d step %d loss %.4f", epoch + 1, steps, loss.item()
                )
    accuracy = _accuracy(model, tokenizer, held_out)
    out = model_dir / models.VERDICT_DIR
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    info = {
        "base_model": models.BASE_MODEL,
        "train_seeds": list(TRAIN_SEEDS),
        "held_out_seed": HELD_OUT_SEED,
        "train_items": len(data),
        "held_out_items": len(held_out),
        "epochs": epochs,
        "held_out_accuracy": round(accuracy, 4),
        "seconds": int(time.monotonic() - started),
        "trained_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    (out / "training.json").write_text(json.dumps(info, indent=2) + "\n")
    _log.info("saved %s: %s", out, info)
    return info
