"""Skin-lesion classification with a locally trained checkpoint.

Imports torch, so this module is only loaded when a checkpoint is configured.
The model scores an image against the fixed set of classes it was trained on. Its output is a
relative score between those classes, not a diagnosis and not a measure of clinical certainty.
"""

from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from lumi.ml.skin_data import CLASS_NAMES
from lumi.ml.skin_model import build_model, letterbox, load_checkpoint, pick_device, to_tensor
from lumi.pipelines.base import PipelineOutput
from lumi.pipelines.mock import UNANSWERED_QUESTION_WARNING
from lumi.validation import ValidatedFile

LIMITATIONS = [
    "Research prototype. It is not clinically validated and does not provide a diagnosis.",
    "The model can only answer with the classes it was trained on. An image of any other condition, or of something "
    "that is not skin, will still be assigned to one of them.",
    "Trained on one small public dataset (PAD-UFES-20, collected by one program in Brazil). Its patients are almost "
    "all adults (median age 62); only 39 of its 2,298 images come from patients under 18, and all of those are benign "
    "nevus. Performance on children, other populations, other skin tones or other cameras has not been evaluated.",
    "Probabilities are the model's relative scores across its classes. They are not clinical certainty, and a high "
    "score can still be wrong.",
]
SCORE_WARNING = (
    "MODEL_SCORE_NOT_CLINICAL_CERTAINTY: 'confidence' is the model's top class probability, not the chance that the "
    "finding is correct. A licensed clinician must assess any skin lesion."
)


class SkinClassifierPipeline:
    name = "skin_lesion_classifier"

    def __init__(self, checkpoint_path: str | Path, device: str | None = None):
        import torch

        checkpoint = load_checkpoint(Path(checkpoint_path))
        self._torch = torch
        self._device = pick_device(device)
        self._classes: list[str] = list(checkpoint["classes"])
        self._image_size: int = int(checkpoint["image_size"])
        self._info: dict = dict(checkpoint["info"])
        self._arch: str = checkpoint["arch"]
        model = build_model(self._arch, len(self._classes), pretrained=False)
        model.load_state_dict(checkpoint["state_dict"])
        self._model = model.to(self._device).eval()

    def model_info(self) -> dict:
        return {
            "name": self._arch,
            "run_id": self._info.get("run_id"),
            "created_utc": self._info.get("created_utc"),
            "trained_on": self._info.get("dataset"),
            "classes": self._classes,
            "image_size": self._image_size,
            "evaluation": {
                "held_out_test_macro_f1": self._info.get("test_macro_f1"),
                "held_out_test_images": self._info.get("test_images"),
                "note": "Measured once on a small patient-level held-out split of the training dataset; not a clinical validation.",
            },
        }

    def run(self, file: ValidatedFile, question: str | None) -> PipelineOutput:
        with Image.open(BytesIO(file.data)) as image:
            original_size = image.size
            tensor = to_tensor(np.asarray(letterbox(image, self._image_size))).unsqueeze(0).to(self._device)
        with self._torch.inference_mode():
            probabilities = self._torch.softmax(self._model(tensor), dim=1)[0].cpu().numpy()
        order = np.argsort(-probabilities)
        top = int(order[0])
        warnings = [SCORE_WARNING]
        if question is not None:
            warnings.append(UNANSWERED_QUESTION_WARNING)
        return PipelineOutput(
            result={
                "status": "completed",
                "pipeline": self.name,
                "predicted_class": self._classes[top],
                "predicted_class_name": CLASS_NAMES.get(self._classes[top], self._classes[top]),
                "probabilities": [
                    {"class": self._classes[i], "name": CLASS_NAMES.get(self._classes[i], self._classes[i]), "probability": round(float(probabilities[i]), 4)}
                    for i in order
                ],
                "model": self.model_info(),
                "input": {"width": original_size[0], "height": original_size[1]},
                "limitations": LIMITATIONS,
            },
            confidence=round(float(probabilities[top]), 4),
            explanation=(
                "A neural network fine-tuned on a public research dataset scored this image against six lesion classes. "
                "This is decision-support information only and not a diagnosis; no heatmap or other explanation of "
                "which image regions drove the score is available yet."
            ),
            warnings=warnings,
        )
