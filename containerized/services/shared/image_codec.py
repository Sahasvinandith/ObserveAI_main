"""
shared/image_codec.py

Encode and decode OpenCV BGR frames to/from Base64-encoded JPEG strings.
"""

import base64
import numpy as np
import cv2


def encode_frame(frame: np.ndarray, quality: int = 85) -> str:
    """
    Encode a BGR numpy array as a Base64 JPEG string.

    Args:
        frame:   OpenCV BGR image (H, W, 3) or (H, W) grayscale.
        quality: JPEG quality in [1, 100]. Lower = smaller file, more artefacts.

    Returns:
        ASCII Base64 string of the JPEG-encoded frame.

    Raises:
        ValueError: If cv2.imencode fails (empty frame, unsupported format, etc.)
    """
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("cv2.imencode returned False — frame may be empty or invalid")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def decode_frame(b64_str: str) -> np.ndarray:
    """
    Decode a Base64 JPEG string back to a BGR numpy array.

    Args:
        b64_str: ASCII Base64 string produced by encode_frame().

    Returns:
        OpenCV BGR image as a numpy array.

    Raises:
        ValueError: If the string is empty or cannot be decoded.
    """
    if not b64_str:
        raise ValueError("Empty Base64 string — nothing to decode")
    raw = base64.b64decode(b64_str)
    arr = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("cv2.imdecode returned None — JPEG bytes may be corrupted")
    return frame


def resize_if_larger(frame: np.ndarray, max_width: int, max_height: int) -> np.ndarray:
    """
    Proportionally resize frame so it fits within max_width x max_height.
    Returns the original frame unchanged if it already fits.
    """
    h, w = frame.shape[:2]
    if w <= max_width and h <= max_height:
        return frame
    scale = min(max_width / w, max_height / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
