#!/usr/bin/env python3
"""
hist_debug.py — Compare two (already-cropped) torso images using the exact
same colour histogram pipeline as the ObserveAI tracking system,
including Gray World normalization.

Usage:
    python hist_debug.py <image1.jpg> <image2.jpg>
"""

import sys
import cv2
import numpy as np

HSV_BINS   = [8, 8, 8]
HSV_RANGES = [0, 180, 0, 256, 0, 256]


def gray_world_normalize(img):
    """Scale each BGR channel so its mean equals 128 (same as the system does)."""
    gw = img.astype(np.float32)
    means = gw.mean(axis=(0, 1))
    if all(m > 5 for m in means):
        scale = 128.0 / means
        gw *= scale
        return np.clip(gw, 0, 255).astype(np.uint8)
    return img


def compute_hist(img):
    norm = gray_world_normalize(img)
    hsv = cv2.cvtColor(norm, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, HSV_BINS, HSV_RANGES)
    cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return hist.flatten()


def side_by_side(img_a, img_b, score):
    TARGET_H = 300
    def rh(img):
        w = int(img.shape[1] * TARGET_H / img.shape[0])
        return cv2.resize(img, (w, TARGET_H))

    canvas = np.hstack([rh(img_a), np.zeros((TARGET_H, 20, 3), dtype=np.uint8), rh(img_b)])

    if score < 0.40:   verdict, color = "SAME SHIRT", (0, 220, 0)
    elif score > 0.60: verdict, color = "DIFFERENT",  (0, 0, 220)
    else:              verdict, color = "UNCERTAIN",  (0, 165, 255)

    banner = np.zeros((50, canvas.shape[1], 3), dtype=np.uint8)
    cv2.putText(banner, f"Bhattacharyya: {score:.4f}  —  {verdict}",
                (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
    return np.vstack([canvas, banner])


def main():
    if len(sys.argv) < 3:
        print("Usage: python hist_debug.py <image1.jpg> <image2.jpg>")
        sys.exit(1)

    img_a = cv2.imread(sys.argv[1])
    img_b = cv2.imread(sys.argv[2])

    if img_a is None: print(f"ERROR: Cannot read '{sys.argv[1]}'"); sys.exit(1)
    if img_b is None: print(f"ERROR: Cannot read '{sys.argv[2]}'"); sys.exit(1)

    score = float(cv2.compareHist(
        compute_hist(img_a).reshape(HSV_BINS).astype(np.float32),
        compute_hist(img_b).reshape(HSV_BINS).astype(np.float32),
        cv2.HISTCMP_BHATTACHARYYA
    ))

    print(f"\n  Bhattacharyya Distance : {score:.4f}", end="  —  ")
    if score < 0.35:   print("✅ VERY SIMILAR")
    elif score < 0.50: print("⚠️  UNCERTAIN")
    else:              print("❌ DIFFERENT")

    cv2.imwrite("hist_debug_result.jpg", side_by_side(img_a, img_b, score))
    print("  Saved → hist_debug_result.jpg\n")


if __name__ == "__main__":
    main()
