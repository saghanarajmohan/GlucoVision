import zipfile
import json
import os
import shutil

model_path = "model/final_model.keras"
backup_path = "model/final_model_backup.keras"
temp_path = "model/final_model_temp.keras"


# Create a backup first
if not os.path.exists(backup_path):
    shutil.copy2(model_path, backup_path)
    print("Backup created.")


def remove_quantization_config(obj):
    if isinstance(obj, dict):
        if "quantization_config" in obj and obj["quantization_config"] is None:
            del obj["quantization_config"]

        for value in obj.values():
            remove_quantization_config(value)

    elif isinstance(obj, list):
        for item in obj:
            remove_quantization_config(item)


# Read the original .keras file
with zipfile.ZipFile(model_path, "r") as source:
    with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:

        for item in source.infolist():
            data = source.read(item.filename)

            if item.filename == "config.json":
                config = json.loads(data.decode("utf-8"))

                remove_quantization_config(config)

                data = json.dumps(config).encode("utf-8")

            target.writestr(item, data)


# Replace the original with the patched version
os.replace(temp_path, model_path)

print("Model patched successfully!")
print("Original backup:", backup_path)