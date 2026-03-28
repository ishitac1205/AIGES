#!/usr/bin/env python3

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
from torch import nn

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOW_SIZE = 8
FEATURE_COUNT = 18
HIDDEN_SIZE = 64
NUM_LAYERS = 2


def _default_model_dir() -> str:
    preferred = REPO_ROOT / "new_models" / "aegis_models"
    if preferred.exists():
        return "new_models/aegis_models"
    return "models/aegis_models"


def _model_dir() -> Path:
    configured = os.getenv("AEGIS_MODEL_DIR", _default_model_dir())
    path = Path(configured)
    return path if path.is_absolute() else REPO_ROOT / path


class AegisLSTM(nn.Module):
    def __init__(self, input_size: int, service_class_count: int = 0) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=HIDDEN_SIZE,
            num_layers=NUM_LAYERS,
            batch_first=True,
        )
        self.fc_failure = nn.Linear(HIDDEN_SIZE, 1)
        self.fc_service = nn.Linear(HIDDEN_SIZE, service_class_count) if service_class_count else None

    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        output, _ = self.lstm(x)
        hidden = output[:, -1, :]
        failure_logits = self.fc_failure(hidden)
        payload: Dict[str, torch.Tensor] = {
            "failure_probability": torch.sigmoid(failure_logits),
        }
        if self.fc_service is not None:
            payload["service_logits"] = self.fc_service(hidden)
        return payload


class LSTMInference:
    def __init__(self, window_size: int = WINDOW_SIZE) -> None:
        self.window_size = window_size
        self.n_features = FEATURE_COUNT
        self.model: Optional[AegisLSTM] = None
        self.loaded_from: Optional[str] = None
        self.service_labels: List[str] = []

    def load(self) -> bool:
        model_dir = _model_dir()
        model_path = model_dir / "lstm_model.pth"
        if not model_path.exists():
            raise FileNotFoundError(f"LSTM model artifact not found at {model_path}")
        state_dict = torch.load(model_path, map_location="cpu")
        if not isinstance(state_dict, dict):
            raise RuntimeError("Unsupported LSTM checkpoint format")

        service_to_idx = {}
        service_index_path = model_dir / "service_to_idx.pkl"
        if service_index_path.exists():
            with open(service_index_path, "rb") as handle:
                service_to_idx = pickle.load(handle)
        service_class_count = 0
        if isinstance(service_to_idx, dict) and service_to_idx:
            service_class_count = max(int(idx) for idx in service_to_idx.values()) + 1
            ordered = sorted(service_to_idx.items(), key=lambda item: int(item[1]))
            self.service_labels = [str(name) for name, _ in ordered]

        input_size = int(state_dict["lstm.weight_ih_l0"].shape[1])
        self.n_features = input_size
        multi_head = "fc_failure.weight" in state_dict
        if not multi_head and "fc.weight" not in state_dict:
            raise RuntimeError("Unsupported LSTM checkpoint format")

        model = AegisLSTM(input_size=input_size, service_class_count=service_class_count if multi_head else 0)
        if multi_head:
            model.load_state_dict(state_dict, strict=service_class_count > 0)
        else:
            upgraded_state = {
                key.replace("fc.", "fc_failure."): value if key.startswith("fc.") else value
                for key, value in state_dict.items()
            }
            model.load_state_dict(upgraded_state, strict=False)
        model.eval()

        self.model = model
        self.loaded_from = str(model_path)
        return True

    def predict_details(self, sequence_array: np.ndarray) -> Dict[str, object]:
        if self.model is None:
            raise RuntimeError("LSTM model is not loaded")

        seq = np.array(sequence_array, dtype=np.float32)
        if seq.ndim == 2:
            seq = seq[np.newaxis, :, :]
        if seq.shape[1] != self.window_size or seq.shape[2] != self.n_features:
            raise ValueError(
                f"LSTM expected input shape (*, {self.window_size}, {self.n_features}) "
                f"but received {seq.shape}"
            )

        with torch.inference_mode():
            tensor = torch.from_numpy(seq)
            output = self.model(tensor)
            failure_probability = float(output["failure_probability"].cpu().numpy()[0, 0])
            details: Dict[str, object] = {
                "failure_probability": failure_probability,
            }
            service_logits = output.get("service_logits")
            if service_logits is not None and self.service_labels:
                probabilities = torch.softmax(service_logits[0], dim=0).cpu().numpy()
                top_index = int(np.argmax(probabilities))
                ranked = sorted(
                    (
                        {
                            "service": self.service_labels[idx] if idx < len(self.service_labels) else str(idx),
                            "probability": float(probabilities[idx]),
                        }
                        for idx in range(len(probabilities))
                    ),
                    key=lambda item: item["probability"],
                    reverse=True,
                )
                details["predicted_service"] = ranked[0]["service"]
                details["predicted_service_probability"] = ranked[0]["probability"]
                details["service_probabilities"] = ranked[:5]
            return details

    def predict(self, sequence_array: np.ndarray) -> float:
        return float(self.predict_details(sequence_array)["failure_probability"])

    def metadata(self) -> Dict[str, object]:
        if self.model is None:
            return {"loaded": False}
        return {
            "loaded": True,
            "type": "pytorch_lstm",
            "window_size": self.window_size,
            "feature_count": self.n_features,
            "hidden_size": HIDDEN_SIZE,
            "num_layers": NUM_LAYERS,
            "path": self.loaded_from,
            "service_classes": self.service_labels,
        }


_instance: Optional[LSTMInference] = None


def get_instance() -> LSTMInference:
    global _instance
    if _instance is None:
        _instance = LSTMInference()
        _instance.load()
    return _instance
