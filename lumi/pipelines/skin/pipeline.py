"""Skin-lesion classification with a locally trained checkpoint.

Imports torch, so this module is only loaded when a checkpoint is configured.
The model scores an image against the fixed set of classes it was trained on. Its output is a
relative score between those classes, not a diagnosis and not a measure of clinical certainty.
"""

import json
import logging
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from lumi.ml import gradcam
from lumi.ml.skin_data import CLASS_NAMES
from lumi.ml.skin_model import build_model, letterbox, load_checkpoint, pick_device, to_tensor, upright_rgb
from lumi.pipelines.base import PipelineOutput
from lumi.pipelines.mock import UNANSWERED_QUESTION_WARNING
from lumi.validation import ValidatedFile

logger = logging.getLogger("lumi")

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


EXPLANATION_UNSUPPORTED_WARNING = (
    "EXPLANATION_UNSUPPORTED: this model's architecture has no attention-map method set up, so no map was made. "
    "The prediction itself is unaffected."
)
EXPLANATION_EMPTY_WARNING = (
    "EXPLANATION_EMPTY: the model found no positive evidence for its chosen class to draw, so no map is shown. "
    "The prediction itself is unaffected."
)
EXPLANATION_FAILED_WARNING = (
    "EXPLANATION_FAILED: the attention map could not be computed for this image. The prediction itself is unaffected."
)


class SkinClassifierPipeline:
    name = "skin_lesion_classifier"
    supports_explanation = True  # the service only asks for explain=True from pipelines that say so

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

    def run(self, file: ValidatedFile, question: str | None, explain: bool = False) -> PipelineOutput:
        with Image.open(BytesIO(file.data)) as image:
            original = upright_rgb(image)  # an independent, fully loaded copy
        tensor = to_tensor(np.asarray(letterbox(original, self._image_size))).unsqueeze(0).to(self._device)

        attention = None
        warnings = [SCORE_WARNING]
        if explain:
            try:
                layer_name, layer = gradcam.find_target_layer(self._model, self._arch)
                attention = gradcam.compute_grad_cam(self._model, tensor, layer, layer_name)
            except gradcam.ExplanationUnsupported:
                warnings.append(EXPLANATION_UNSUPPORTED_WARNING)
            except gradcam.ExplanationEmpty:
                warnings.append(EXPLANATION_EMPTY_WARNING)
            except gradcam.ExplanationError:
                warnings.append(EXPLANATION_FAILED_WARNING)
            except Exception as exc:  # noqa: BLE001  (an explanation problem must never cost the user a valid prediction)
                logger.error(json.dumps({"event": "explanation_failed", "type": type(exc).__name__}))
                warnings.append(EXPLANATION_FAILED_WARNING)
        if attention is not None:
            probabilities = attention.probabilities  # same forward pass as the map, so they always agree
        else:
            with self._torch.inference_mode():
                probabilities = self._torch.softmax(self._model(tensor), dim=1)[0].cpu().numpy()
        order = np.argsort(-probabilities)
        top = int(order[0])
        predicted = self._classes[top]

        explanation_image = None
        if attention is not None:
            try:
                overlay = gradcam.make_overlay(original, attention.cam, self._image_size)
                explanation_image = {
                    "kind": "grad_cam_overlay",
                    "method": "Grad-CAM",
                    "target_class": predicted,
                    "target_class_name": CLASS_NAMES.get(predicted, predicted),
                    "target_layer": attention.layer_name,
                    "map_cells": list(attention.grid),
                    "mime_type": "image/jpeg",
                    "width": overlay.width,
                    "height": overlay.height,
                    "image_base64": gradcam.encode_jpeg_base64(overlay),
                    "label": gradcam.LABEL,
                    "how_to_read": gradcam.HOW_TO_READ,
                    "limitations": gradcam.EXPLANATION_LIMITATIONS,
                }
            except Exception as exc:  # noqa: BLE001  (never let a drawing problem hide a valid prediction)
                logger.error(json.dumps({"event": "explanation_failed", "type": type(exc).__name__}))
                warnings.append(EXPLANATION_FAILED_WARNING)

        if question is not None:
            warnings.append(UNANSWERED_QUESTION_WARNING)
        result = {
            "status": "completed",
            "pipeline": self.name,
            "predicted_class": predicted,
            "predicted_class_name": CLASS_NAMES.get(predicted, predicted),
            "probabilities": [
                {"class": self._classes[i], "name": CLASS_NAMES.get(self._classes[i], self._classes[i]), "probability": round(float(probabilities[i]), 4)}
                for i in order
            ],
            "model": self.model_info(),
            "input": {"width": original.width, "height": original.height},
            "limitations": LIMITATIONS,
        }
        if explanation_image is not None:
            result["explanation_image"] = explanation_image
        explanation_text = (
            "A neural network fine-tuned on a public research dataset scored this image against six lesion classes. "
            "This is decision-support information only and not a diagnosis. "
        )
        explanation_text += (
            "The attention map (Grad-CAM) shows which image areas raised the model's score for its chosen class; it "
            "describes the model, not the lesion."
            if explanation_image is not None
            else "No attention map was produced for this request."
        )
        return PipelineOutput(
            result=result,
            confidence=round(float(probabilities[top]), 4),
            explanation=explanation_text,
            xai_reference=f"grad_cam:{attention.layer_name}:{predicted}" if explanation_image is not None else None,
            warnings=warnings,
        )
