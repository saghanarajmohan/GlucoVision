import tensorflow as tf
from PIL import Image
import numpy as np


# ============================================================
# Load model
# ============================================================

MODEL_PATH = "model/final_model.keras"

model = tf.keras.models.load_model(
    MODEL_PATH,
    compile=False
)


# ============================================================
# DR class names
# ============================================================

class_names = [
    "No Diabetic Retinopathy",
    "Mild Diabetic Retinopathy",
    "Moderate Diabetic Retinopathy",
    "Severe Diabetic Retinopathy",
    "Proliferative Diabetic Retinopathy"
]


# ============================================================
# Prediction function
# ============================================================

def predict_image(image_path):

    # Load image
    image = Image.open(image_path).convert("RGB")

    # Resize to model input size
    image = image.resize((224, 224))

    # Convert to NumPy array
    image_array = np.array(image, dtype=np.float32)

    # Add batch dimension
    image_array = np.expand_dims(image_array, axis=0)

    # Make prediction
    prediction = model.predict(
        image_array,
        verbose=0
    )

    # Get predicted class
    predicted_class = int(np.argmax(prediction[0]))

    # Get confidence
    confidence = float(np.max(prediction[0]) * 100)

    # Get all probabilities
    probabilities = {}

    for i, probability in enumerate(prediction[0]):
        probabilities[class_names[i]] = float(probability * 100)

    # Return results
    return {
        "prediction": class_names[predicted_class],
        "confidence": confidence,
        "probabilities": probabilities
    }


# ============================================================
# Test the function
# ============================================================

if __name__ == "__main__":

    image_path = "test_image.png"

    result = predict_image(image_path)

    print("\n===== GlucoVision Screening Result =====")

    print(
        "Prediction:",
        result["prediction"]
    )

    print(
        "Confidence:",
        f"{result['confidence']:.2f}%"
    )

    print("\nAll class probabilities:")

    for class_name, probability in result["probabilities"].items():

        print(
            f"{class_name}: {probability:.2f}%"
        )

    print("========================================")