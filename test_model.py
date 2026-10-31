import tensorflow as tf

model = tf.keras.models.load_model(
    "model/final_model.keras",
    compile=False
)

print("Model loaded successfully!")
print("Input shape:", model.input_shape)
print("Output shape:", model.output_shape)