import cv2
import numpy as np
from PIL import Image


MIN_WIDTH = 224
MIN_HEIGHT = 224

MIN_BRIGHTNESS = 20
MAX_BRIGHTNESS = 235

MIN_BLUR_SCORE = 15


def check_image_quality(image_path):

    image = Image.open(image_path).convert("RGB")

    width, height = image.size

    # Check image dimensions
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return {
            "valid": False,
            "reason": "Image resolution is too low. Please upload a higher-quality retinal image."
        }

    image_array = np.array(image)

    # Convert to grayscale for quality measurements
    gray = cv2.cvtColor(
        image_array,
        cv2.COLOR_RGB2GRAY
    )

    # Check brightness
    mean_brightness = float(np.mean(gray))

    if mean_brightness < MIN_BRIGHTNESS:
        return {
            "valid": False,
            "reason": "Image is too dark. Please upload a clearer retinal image."
        }

    if mean_brightness > MAX_BRIGHTNESS:
        return {
            "valid": False,
            "reason": "Image is too bright. Please upload a clearer retinal image."
        }

    # Check blur using variance of Laplacian
    blur_score = float(
        cv2.Laplacian(
            gray,
            cv2.CV_64F
        ).var()
    )

    if blur_score < MIN_BLUR_SCORE:
        return {
            "valid": False,
            "reason": "Image is too blurry. Please upload a clearer retinal image."
        }

    return {
        "valid": True,
        "reason": "Image quality is acceptable.",
        "blur_score": blur_score,
        "brightness": mean_brightness
    }