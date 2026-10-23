"""Shared MobileNetV3 model definition for training and inference."""

from __future__ import annotations

import torch.nn as nn
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small


ACTIVITY_CLASSES = ("feeding", "other", "walk")
IMAGE_SIZE = 224


def create_activity_model(num_classes: int = len(ACTIVITY_CLASSES), pretrained: bool = False):
    weights = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    model = mobilenet_v3_small(weights=weights)
    input_features = model.classifier[3].in_features
    model.classifier[3] = nn.Linear(input_features, num_classes)
    return model
