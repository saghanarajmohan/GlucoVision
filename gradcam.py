import tensorflow as tf
from PIL import Image
import numpy as np
import cv2


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
# Grad-CAM function
# ============================================================

def generate_gradcam(image_path, output_path="gradcam_result.jpg"):

    # --------------------------------------------------------
    # Load image
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Normal prediction
    # --------------------------------------------------------

    prediction = model.predict(
        image_array,
        verbose=0
    )

    predicted_class = int(
        np.argmax(prediction[0])
    )

    confidence = float(
        np.max(prediction[0]) * 100
    )


    # --------------------------------------------------------
    # Get EfficientNet
    # --------------------------------------------------------

    efficientnet = model.get_layer(
        "efficientnetb0"
    )


    # --------------------------------------------------------
    # Get target layer
    # --------------------------------------------------------

    target_layer = efficientnet.get_layer(
        "top_conv"
    )

    feature_model = tf.keras.models.Model(
        inputs=efficientnet.input,
        outputs=target_layer.output
    )


    # --------------------------------------------------------
    # Find layers after top_conv
    # --------------------------------------------------------

    post_conv_layers = []

    found_target = False

    for layer in efficientnet.layers:

        if layer.name == "top_conv":
            found_target = True
            continue

        if found_target:
            post_conv_layers.append(layer)


    # --------------------------------------------------------
    # Calculate gradients
    # --------------------------------------------------------

    with tf.GradientTape() as tape:

        conv_output = feature_model(
            image_array,
            training=False
        )

        x = conv_output

        for layer in post_conv_layers:
            x = layer(x)


        # EfficientNet output
        efficientnet_result = x


        # Pass through main model layers
        x = efficientnet_result

        for layer in model.layers:

            if layer.name == "efficientnetb0":
                continue

            if isinstance(
                layer,
                tf.keras.layers.InputLayer
            ):
                continue

            x = layer(x)


        final_predictions = x

        class_score = final_predictions[
            :,
            predicted_class
        ]


    # --------------------------------------------------------
    # Get gradients
    # --------------------------------------------------------

    grads = tape.gradient(
        class_score,
        conv_output
    )


    # --------------------------------------------------------
    # Generate Grad-CAM heatmap
    # --------------------------------------------------------

    pooled_grads = tf.reduce_mean(
        grads,
        axis=(1, 2)
    )

    conv_output = conv_output[0]
    pooled_grads = pooled_grads[0]


    heatmap = conv_output @ pooled_grads[..., tf.newaxis]

    heatmap = tf.squeeze(
        heatmap
    )

    heatmap = tf.maximum(
        heatmap,
        0
    )


    max_heatmap = tf.reduce_max(
        heatmap
    )

    if max_heatmap > 0:
        heatmap = heatmap / max_heatmap


    heatmap = heatmap.numpy()


    # --------------------------------------------------------
    # Resize heatmap
    # --------------------------------------------------------

    heatmap = np.uint8(
        255 * heatmap
    )

    heatmap = cv2.resize(
        heatmap,
        (224, 224)
    )


    # --------------------------------------------------------
    # Create colored heatmap
    # --------------------------------------------------------

    heatmap_color = cv2.applyColorMap(
        heatmap,
        cv2.COLORMAP_JET
    )


    # --------------------------------------------------------
    # Prepare original image
    # --------------------------------------------------------

    original_image = np.array(
        image
    )

    original_image = cv2.cvtColor(
        original_image,
        cv2.COLOR_RGB2BGR
    )


    # --------------------------------------------------------
    # Overlay heatmap
    # --------------------------------------------------------

    overlay = cv2.addWeighted(
        original_image,
        0.6,
        heatmap_color,
        0.4,
        0
    )


    # --------------------------------------------------------
    # Save result
    # --------------------------------------------------------

    cv2.imwrite(
        output_path,
        overlay
    )


    # --------------------------------------------------------
    # Return result
    # --------------------------------------------------------

    return {
        "prediction": class_names[predicted_class],
        "confidence": confidence,
        "heatmap_path": output_path
    }


# ============================================================
# Test the function
# ============================================================

if __name__ == "__main__":

    image_path = "test_image.png"

    result = generate_gradcam(
        image_path
    )

    print("\n===== GlucoVision Grad-CAM =====")

    print(
        "Prediction:",
        result["prediction"]
    )

    print(
        "Confidence:",
        f"{result['confidence']:.2f}%"
    )

    print(
        "\nGrad-CAM heatmap generated successfully!"
    )

    print(
        "Saved as:",
        result["heatmap_path"]
    )

    print(
        "\nThe heatmap highlights regions that influenced"
    )

    print(
        "the model's prediction."
    )