import keras
import numpy as np
from PIL import Image


MODEL_PATH = "model/final_model.keras"

LABELS = [
    "No Diabetic Retinopathy",
    "Mild Diabetic Retinopathy",
    "Moderate Diabetic Retinopathy",
    "Severe Diabetic Retinopathy",
    "Proliferative Diabetic Retinopathy"
]


print("Loading DR model...")

model = keras.saving.load_model(MODEL_PATH)

print("DR model loaded successfully!")


def predict_image(image_path):

    image = Image.open(image_path).convert("RGB")

    image = image.resize((224, 224))

    image_array = np.array(
        image,
        dtype=np.float32
    )

    image_array = np.expand_dims(
        image_array,
        axis=0
    )

    predictions = model.predict(
        image_array,
        verbose=0
    )[0]

    predicted_index = int(
        np.argmax(predictions)
    )

    predicted_label = LABELS[predicted_index]

    confidence = float(
        predictions[predicted_index]
    )

    probabilities = {
        label: float(probability)
        for label, probability in zip(
            LABELS,
            predictions
        )
    }

    return {
        "prediction": predicted_label,
        "confidence": confidence,
        "probabilities": probabilities
    }