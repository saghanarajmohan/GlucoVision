---
license: mit
tags:
  - image-classification
  - medical-imaging
  - diabetic-retinopathy
  - efficientnet
  - keras
  - ophthalmology
datasets:
  - aptos2019-blindness-detection
metrics:
  - accuracy
  - f1
language:
  - en
---

# Diabetic Retinopathy Grading — EfficientNetB0

Fine-tuned **EfficientNetB0** for 5-class diabetic retinopathy severity grading from retinal fundus photographs, trained on the [APTOS 2019 Blindness Detection](https://www.kaggle.com/competitions/aptos2019-blindness-detection) dataset.

---

## Model Details

| Property | Value |
|---|---|
| Base model | EfficientNetB0 (ImageNet pretrained) |
| Framework | Keras 3.13.2 |
| Input shape | 224 × 224 × 3 (RGB) |
| Output | 5-class softmax |
| Parameters | ~5.3M |
| File size | 33.4 MB (float32) |

---

## DR Severity Classes

| Grade | Label | Clinical Meaning |
|---|---|---|
| 0 | No DR | No signs of diabetic retinopathy |
| 1 | Mild | Microaneurysms only |
| 2 | Moderate | More than microaneurysms, less than severe |
| 3 | Severe | Extensive hemorrhages, venous beading |
| 4 | Proliferative | Neovascularization or vitreous hemorrhage |

---

## Training Setup

**Dataset:** APTOS 2019 — 3,662 fundus images across 5 severity grades

**Two-phase fine-tuning:**
- Phase 1 (epochs 0–9): EfficientNetB0 backbone frozen, classification head trained from scratch
- Phase 2 (epochs 10–21): Full network unfrozen and fine-tuned with reduced learning rate

**Preprocessing pipeline:** Rescaling (÷255) → per-channel Normalization

**Regularization:** Dropout(0.3) before the final Dense layer

---

## Evaluation Results

Evaluated on 550 held-out validation images from APTOS 2019.

**Overall accuracy: 72% · Macro F1: 0.57 · Weighted F1: 0.73**

| Class | Precision | Recall | F1-score | Support |
|---|---|---|---|---|
| No DR | 0.95 | 0.94 | 0.95 | 271 |
| Mild | 0.33 | 0.62 | 0.43 | 56 |
| Moderate | 0.74 | 0.47 | 0.57 | 150 |
| Severe | 0.34 | 0.55 | 0.42 | 29 |
| Proliferative | 0.55 | 0.41 | 0.47 | 44 |

> **Note:** The APTOS 2019 dataset is heavily skewed toward No DR (49% of samples).
> The model performs strongly on the dominant class (F1 = 0.95) but struggles on
> minority classes — a known limitation of unimodal image-only approaches on
> imbalanced medical datasets. This serves as the baseline motivation for
> multimodal DR grading research incorporating metabolic context (HbA1c, diabetes duration).

---

## How to Use

```python
import keras
import numpy as np
from PIL import Image

# Load model
model = keras.saving.load_model("final_model.keras")

LABELS = ["No DR", "Mild", "Moderate", "Severe", "Proliferative"]

def predict(image_path: str):
    img = Image.open(image_path).convert("RGB").resize((224, 224))
    arr = np.expand_dims(np.array(img, dtype=np.float32), axis=0)
    probs = model.predict(arr)[0]
    label = LABELS[np.argmax(probs)]
    confidence = float(np.max(probs))
    return label, confidence

label, conf = predict("fundus.jpg")
print(f"Prediction: {label} ({conf:.1%})")
```

---

## Limitations

- **Class imbalance:** Performance degrades on minority classes (Severe, Proliferative) due to dataset skew
- **Boundary confusion:** Adjacent severity grades (Mild ↔ Moderate, Severe ↔ Proliferative) are frequently confused — a property inherent to unimodal retinal image analysis
- **Unimodal:** Does not incorporate metabolic or clinical context that clinicians rely on
- **Dataset scope:** Trained solely on APTOS 2019 — generalization to other fundus camera types or populations is untested
- **Not for clinical use:** This model has not been validated for medical diagnosis

---

## Citation

```bibtex
@misc{aptos2019,
  title   = {APTOS 2019 Blindness Detection},
  author  = {Asia Pacific Tele-Ophthalmology Society},
  year    = {2019},
  publisher = {Kaggle},
  url     = {https://www.kaggle.com/c/aptos2019-blindness-detection}
}
```

---

## Author

**Nasser Aldahmashi**  
AI specialization student · Asia Pacific University (APU), Kuala Lumpur  
🤗 [huggingface.co/Aldahmashi](https://huggingface.co/Aldahmashi)