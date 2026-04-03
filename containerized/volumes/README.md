# ObserveAI — Volume Mounts Reference

This document describes every persistent data directory and file used by ObserveAI,
and how each is mounted in the containerized deployment.

---

## Volumes Summary

| Volume name        | Container path          | Purpose                                      | Size guidance |
|--------------------|-------------------------|----------------------------------------------|---------------|
| `faces-db`         | `/app/Faces_db/`        | Face crop images per person (DeepFace)       | 1–10 GB       |
| `actions-db`       | `/app/Actions_db/`      | Pose reference JSON files                    | < 10 MB       |
| `maps`             | `/app/maps/`            | Camera layout / calibration JSON files       | < 10 MB       |
| `settings`         | `/app/settings.json`    | Runtime configuration (JSON)                 | < 1 MB        |
| `logs`             | `/app/logs.db`          | SQLite activity log                          | 1–5 GB        |
| `detections`       | `/app/detections/`      | Action evidence JPEG snapshots               | 5–50 GB       |
| `yolo-weights`     | `/app/yolo-weights/`    | YOLO .pt model files (read-only)             | ~20 MB        |
| `torch-hub-cache`  | `/app/torch_hub_cache/` | ResNet-50 Re-ID weights (PyTorch Hub cache)  | ~100 MB       |
| `deepface-weights` | `/app/deepface_weights/`| DeepFace ArcFace model weights               | ~300 MB       |

---

## YOLO Model Weights

The three YOLO model files must be placed in the `yolo-weights` volume:

```
yolov8n.pt          — person detection
yolov11n-face.pt    — face detection
yolov8n-pose.pt     — pose estimation (for action recognition)
```

### Populating the yolo-weights volume (Docker Compose)

```bash
# Copy weights from the project root into the named volume
docker run --rm \
  -v /path/to/ObserveAI_main:/src:ro \
  -v observeai_yolo-weights:/dst \
  alpine sh -c "cp /src/yolov8n.pt /src/yolov11n-face.pt /src/yolov8n-pose.pt /dst/"
```

Or, use a bind mount in docker-compose.yml (edit the volume definition):

```yaml
volumes:
  yolo-weights:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /absolute/path/to/ObserveAI_main   # project root contains the .pt files
```

If the weights are missing on startup, the entrypoint will print a warning and
YOLO will attempt to download them from the internet automatically.

---

## Face Database (Faces_db)

Structure expected by DeepFace and EmbeddingCache:

```
Faces_db/
  PersonName/
    face_001.jpg
    face_002.jpg
    ...
  AnotherPerson/
    face_001.jpg
```

Each subfolder name is the person's display name. Images must be `.jpg` or `.png`.

---

## Migrating Existing Data

To seed a fresh volume from your monolith's data directory:

```bash
# Example: migrate Faces_db
docker run --rm \
  -v /path/to/ObserveAI_main/Faces_db:/src:ro \
  -v observeai_faces-db:/dst \
  alpine sh -c "cp -r /src/. /dst/"

# Example: migrate Actions_db
docker run --rm \
  -v /path/to/ObserveAI_main/Actions_db:/src:ro \
  -v observeai_actions-db:/dst \
  alpine sh -c "cp -r /src/. /dst/"

# Example: migrate settings.json
docker run --rm \
  -v /path/to/ObserveAI_main/settings.json:/src/settings.json:ro \
  -v observeai_settings:/dst \
  alpine sh -c "cp /src/settings.json /dst/"
```
