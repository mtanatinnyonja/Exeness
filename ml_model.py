"""
Modèle ML local léger pour scorer la probabilité de réussite d'un signal.
Apprend à partir des signaux passés et du mouvement réel du marché après le signal.
Aucune API externe, aucun cloud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np


@dataclass
class TrainedLocalModel:
    weights: np.ndarray
    bias: float
    mean: np.ndarray
    std: np.ndarray
    sample_count: int
    accuracy: float
    trained_at: str


class LocalSignalModel:
    def __init__(self, store, broker):
        self.store = store
        self.broker = broker
        self._model: Optional[TrainedLocalModel] = None
        self._last_refresh_ts: float = 0.0
        self._label_cache: Dict[str, Optional[int]] = {}  # (instrument|ts|dir) → label

    def _now_ts(self) -> float:
        return datetime.now(timezone.utc).timestamp()

    def _sigmoid(self, z: np.ndarray) -> np.ndarray:
        z = np.clip(z, -30, 30)
        return 1.0 / (1.0 + np.exp(-z))

    def _encode_direction(self, value: Any) -> float:
        text = str(value or '').upper()
        if text == 'BUY':
            return 1.0
        if text == 'SELL':
            return -1.0
        return 0.0

    def _feature_vector_from_sample(self, sample: Dict[str, Any]) -> np.ndarray:
        score = float(sample.get('score', 0) or 0)
        rsi = float(sample.get('rsi', 50) or 50)
        macd = float(sample.get('macd', 0) or 0)
        spread = float(sample.get('spread', 0) or 0)
        confidence = float(sample.get('confidence', 0) or 0)
        direction = self._encode_direction(sample.get('direction') or sample.get('decision'))
        return np.array([
            score / 5.0,
            (rsi - 50.0) / 50.0,
            np.tanh(macd * 2000.0),
            min(spread / 100.0, 3.0),
            confidence,
            direction,
        ], dtype=float)

    def _feature_vector_from_signal(self, signal: Dict[str, Any], spread: float) -> np.ndarray:
        details = signal.get('details', {}) or {}
        score = float(signal.get('score', 0) or 0)
        rsi = float(details.get('rsi', 50) or 50)
        macd = float(details.get('macd', 0) or 0)
        confidence_hint = min(1.0, max(0.0, score / 5.0))
        direction = self._encode_direction(signal.get('direction'))
        return np.array([
            score / 5.0,
            (rsi - 50.0) / 50.0,
            np.tanh(macd * 2000.0),
            min(float(spread or 0) / 100.0, 3.0),
            confidence_hint,
            direction,
        ], dtype=float)

    def _fit_logistic(self, X: np.ndarray, y: np.ndarray) -> TrainedLocalModel:
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std == 0] = 1.0
        Xn = (X - mean) / std

        weights = np.zeros(Xn.shape[1], dtype=float)
        bias = 0.0
        lr = 0.15
        reg = 0.01

        for _ in range(min(600, max(350, len(Xn) * 2))):
            logits = Xn @ weights + bias
            preds = self._sigmoid(logits)
            error = preds - y
            grad_w = (Xn.T @ error) / len(Xn) + reg * weights
            grad_b = float(error.mean())
            weights -= lr * grad_w
            bias -= lr * grad_b

        final_preds = (self._sigmoid(Xn @ weights + bias) >= 0.5).astype(float)
        accuracy = float((final_preds == y).mean()) if len(y) else 0.0

        return TrainedLocalModel(
            weights=weights,
            bias=bias,
            mean=mean,
            std=std,
            sample_count=int(len(y)),
            accuracy=round(accuracy, 3),
            trained_at=datetime.now(timezone.utc).isoformat(),
        )

    def train_if_needed(self, force: bool = False) -> Optional[TrainedLocalModel]:
        now = self._now_ts()
        if not force and self._model is not None and (now - self._last_refresh_ts) < 90:
            return self._model

        rows = self.store.get_ml_training_samples(1000)
        X_list = []
        y_list = []
        for row in rows:
            direction = str(row.get('direction') or row.get('decision') or '').upper()
            if direction not in {'BUY', 'SELL'}:
                continue
            cache_key = f"{row.get('instrument')}|{row.get('timestamp')}|{direction}"
            if cache_key in self._label_cache:
                outcome = self._label_cache[cache_key]
            else:
                try:
                    outcome = self.broker.get_signal_outcome_label(
                        instrument=row.get('instrument'),
                        sample_time=row.get('timestamp'),
                        direction=direction,
                        spread=float(row.get('spread', 0) or 0),
                    )
                except Exception:
                    outcome = None
                self._label_cache[cache_key] = outcome
            if outcome is None:
                continue
            X_list.append(self._feature_vector_from_sample(row))
            y_list.append(float(outcome))

        self._last_refresh_ts = now
        if len(y_list) < 25:
            self._model = None
            return None

        X = np.vstack(X_list)
        y = np.array(y_list, dtype=float)
        self._model = self._fit_logistic(X, y)
        return self._model

    def evaluate_signal(self, signal: Dict[str, Any], spread: float) -> Dict[str, Any]:
        model = self.train_if_needed()
        if model is None:
            base = min(0.75, max(0.25, 0.42 + (float(signal.get('score', 0) or 0) - 2.0) * 0.08))
            return {
                'trained': False,
                'probability': round(base, 3),
                'sample_count': 0,
                'accuracy': None,
                'source': 'heuristic-bootstrap',
            }

        vec = self._feature_vector_from_signal(signal, spread)
        vecn = (vec - model.mean) / model.std
        prob = float(self._sigmoid(vecn @ model.weights + model.bias))
        return {
            'trained': True,
            'probability': round(prob, 3),
            'sample_count': model.sample_count,
            'accuracy': model.accuracy,
            'source': 'local-logistic-ml',
            'trained_at': model.trained_at,
        }

    def get_status(self) -> Dict[str, Any]:
        model = self.train_if_needed()
        if model is None:
            return {
                'trained': False,
                'sample_count': 0,
                'accuracy': None,
                'model_type': 'local-logistic-ml',
            }
        return {
            'trained': True,
            'sample_count': model.sample_count,
            'accuracy': model.accuracy,
            'model_type': 'local-logistic-ml',
            'trained_at': model.trained_at,
        }
