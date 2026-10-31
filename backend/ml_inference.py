from predict import predict_image
from gradcam import generate_gradcam


def run_inference(image_path, heatmap_path="gradcam_result.jpg"):
    """
    Run GlucoVision prediction and generate a Grad-CAM explanation.

    Args:
        image_path: Path to the uploaded retinal/fundus image.
        heatmap_path: Path where the Grad-CAM image should be saved.

    Returns:
        Dictionary containing prediction, confidence,
        probabilities, and Grad-CAM heatmap path.
    """

    prediction_result = predict_image(image_path)

    gradcam_result = generate_gradcam(
        image_path,
        output_path=heatmap_path
    )

    return {
        "prediction": prediction_result["prediction"],
        "confidence": prediction_result["confidence"],
        "probabilities": prediction_result["probabilities"],
        "heatmap_path": gradcam_result["heatmap_path"]
    }


if __name__ == "__main__":
    image_path = "test_image.png"

    result = run_inference(image_path)

    print("\n===== GlucoVision ML Result =====")
    print("Prediction:", result["prediction"])
    print("Confidence:", f"{result['confidence']:.2f}%")

    print("\nClass probabilities:")
    for class_name, probability in result["probabilities"].items():
        print(f"{class_name}: {probability:.2f}%")

    print("\nGrad-CAM:", result["heatmap_path"])
    print("================================")