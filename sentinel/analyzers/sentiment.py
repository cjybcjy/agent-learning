"""FinBERT sentiment scoring via ONNX Runtime.

Supports batch inference with configurable batch_size.
Falls back to neutral (0.0) on any error with a warning log.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Label mapping for ProsusAI/finbert: 0=positive, 1=negative, 2=neutral
_LABEL_SCORES = {0: 1.0, 1: -1.0, 2: 0.0}


class SentimentAnalyzer:
    """ONNX Runtime-based FinBERT sentiment analyzer."""

    def __init__(self, model_dir: Path | str, batch_size: int = 64) -> None:
        self.model_dir = Path(model_dir)
        self.batch_size = batch_size
        self._session = None
        self._tokenizer = None

    def _load(self) -> None:
        """Lazy-load model and tokenizer on first use."""
        if self._session is not None:
            return

        import onnxruntime as ort
        from transformers import AutoTokenizer

        # Look for quantized model first, then regular
        quantized_path = self.model_dir / "quantized" / "model_quantized.onnx"
        regular_path = self.model_dir / "model.onnx"
        onnx_path = quantized_path if quantized_path.exists() else regular_path

        if not onnx_path.exists():
            raise FileNotFoundError(f"No ONNX model found at {onnx_path}")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 4
        self._session = ort.InferenceSession(str(onnx_path), sess_options=opts)
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        logger.info("Loaded FinBERT model from %s", onnx_path)

    def score_texts(self, texts: list[str]) -> list[float]:
        """Score a list of texts, returning sentiment in [-1.0, 1.0].

        Uses softmax over logits and maps to directional score:
          score = P(positive) - P(negative)

        Falls back to 0.0 for any text that causes an error.
        """
        if not texts:
            return []

        try:
            self._load()
        except Exception as exc:
            logger.warning("Failed to load sentiment model, returning neutral: %s", exc)
            return [0.0] * len(texts)

        scores: list[float] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_scores = self._infer_batch(batch)
            scores.extend(batch_scores)
        return scores

    def _infer_batch(self, texts: list[str]) -> list[float]:
        """Run inference on a single batch."""
        try:
            encoded = self._tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="np",
            )
            input_feed = {
                "input_ids": encoded["input_ids"].astype(np.int64),
                "attention_mask": encoded["attention_mask"].astype(np.int64),
            }
            # Some models also expect token_type_ids
            if "token_type_ids" in encoded:
                input_feed["token_type_ids"] = encoded["token_type_ids"].astype(np.int64)

            outputs = self._session.run(None, input_feed)
            logits = outputs[0]  # shape: (batch, num_labels)

            # Softmax
            exp_logits = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
            probs = exp_logits / exp_logits.sum(axis=-1, keepdims=True)

            # Directional score: P(positive) - P(negative)
            # ProsusAI/finbert: label 0=positive, 1=negative, 2=neutral
            scores: list[float] = []
            for row in probs:
                p_pos = float(row[0]) if len(row) > 0 else 0.0
                p_neg = float(row[1]) if len(row) > 1 else 0.0
                score = p_pos - p_neg
                scores.append(round(score, 4))
            return scores

        except Exception as exc:
            logger.warning("Batch inference failed, returning neutral: %s", exc)
            return [0.0] * len(texts)


class NullSentimentAnalyzer:
    """No-op analyzer that always returns neutral. Used when no model is available."""

    def score_texts(self, texts: list[str]) -> list[float]:
        return [0.0] * len(texts)
