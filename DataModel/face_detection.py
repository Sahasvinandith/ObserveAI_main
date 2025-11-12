from datetime import datetime
import cv2
import os
import numpy as np
from deepface import DeepFace

# Setup
db_path = "Faces_db"
os.makedirs(db_path, exist_ok=True)

# Configuration
CONFIDENCE_THRESHOLD = 0.6
MIN_FACE_SIZE = (120, 120)
MAX_FACES_PER_USER = 10
QUALITY_THRESHOLD = 100

# Feature detector for ORB
orb = cv2.ORB_create(nfeatures=100, scaleFactor=1.2, WTA_K=2, scoreType=cv2.ORB_HARRIS_SCORE)


def calculate_face_quality(face_img):
    """
    Calculate a quality score for a face image based on:
    - Sharpness (Laplacian variance)
    - Lighting balance (histogram entropy)
    - Face size
    """
    if len(face_img.shape) > 2:
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = face_img

    # 1. Sharpness score
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

    # 2. Lighting balance (entropy)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    hist_normalized = hist / hist.sum()
    hist_distribution = np.sum(-hist_normalized * np.log2(hist_normalized + 1e-10))

    # 3. Size ratio
    face_size_ratio = (face_img.shape[0] * face_img.shape[1]) / (640 * 480)

    # Combined score
    quality_score = (laplacian_var * 0.5) + (hist_distribution * 50) + (face_size_ratio * 50)

    return quality_score


def recognize_face(face_img_path):
    """
    Recognize a face by comparing it against all users in the database.
    Returns: (user_folder_name, confidence_score)

    Lower confidence score means better match.
    Returns ("Unknown", 1.0) if no match found.
    """
    try:
        # Check if database has any entries
        if not any(os.path.isdir(os.path.join(db_path, d)) for d in os.listdir(db_path)):
            return "Unknown", 1.0

        best_match = "Unknown"
        best_confidence = 1.0

        # Iterate through all user folders
        for user_folder in os.listdir(db_path):
            user_path = os.path.join(db_path, user_folder)

            if not os.path.isdir(user_path):
                continue

            # Get all image files in the user folder
            image_files = [f for f in os.listdir(user_path)
                           if f.endswith(('.jpg', '.jpeg', '.png'))]

            if not image_files:
                continue

            # Verify against up to 3 reference images per user for speed
            for img_file in image_files[:3]:
                reference_img = os.path.join(user_path, img_file)

                try:
                    result = DeepFace.verify(
                        img1_path=face_img_path,
                        img2_path=reference_img,
                        enforce_detection=False,
                        model_name="ArcFace"  # ArcFace is most accurate
                    )

                    if result["verified"] and result["distance"] < best_confidence:
                        best_match = user_folder
                        best_confidence = result["distance"]

                        # Early exit for very good matches
                        if best_confidence < 0.2:
                            break

                except Exception as e:
                    # Skip this comparison if it fails
                    continue

            # Early exit for very good matches
            if best_confidence < 0.3:
                break

        return best_match, best_confidence

    except Exception as e:
        print(f"Recognition error: {e}")
        return "Unknown", 1.0


def update_user_faces(user_folder, face_img, quality_score):
    """
    Update a user's face database with better quality images.
    Maintains up to MAX_FACES_PER_USER images, replacing lower quality ones.
    """
    try:
        user_path = os.path.join(db_path, str(user_folder))
        os.makedirs(user_path, exist_ok=True)

        # Get existing images with their quality scores
        images = []
        for filename in os.listdir(user_path):
            if not filename.endswith(('.jpg', '.jpeg', '.png')):
                continue

            file_path = os.path.join(user_path, filename)

            # Extract quality from filename if available
            if '_q' in filename:
                try:
                    file_quality = float(filename.split('_q')[1].split('.')[0])
                except:
                    file_quality = 0
            else:
                file_quality = 0

            images.append((file_path, file_quality))

        # Sort by quality (lowest first)
        images.sort(key=lambda x: x[1])

        # Replace worst quality image if at capacity
        if len(images) >= MAX_FACES_PER_USER:
            if quality_score > images[0][1]:
                os.remove(images[0][0])
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_file = os.path.join(user_path, f"face_{timestamp}_q{quality_score:.1f}.jpg")
                cv2.imwrite(new_file, face_img)
                print(f"[UPDATED] Replaced low quality face (q: {quality_score:.1f}) for {user_folder}")
        else:
            # Add new image if under capacity
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_file = os.path.join(user_path, f"face_{timestamp}_q{quality_score:.1f}.jpg")
            cv2.imwrite(new_file, face_img)
            print(f"[ADDED] New face image (q: {quality_score:.1f}) for {user_folder}")

    except Exception as e:
        print(f"Error updating user faces: {e}")


def extract_face_features(face_img):
    """
    Extract ORB features from a face image.
    Returns: (keypoints, descriptors)
    """
    try:
        if len(face_img.shape) > 2:
            gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        else:
            gray = face_img

        keypoints = orb.detect(gray, None)
        keypoints, descriptors = orb.compute(gray, keypoints)

        if descriptors is None or len(keypoints) < 5:
            return None, None

        return keypoints, descriptors

    except Exception as e:
        print(f"Error extracting face features: {e}")
        return None, None


def match_face_features(new_descriptor, stored_descriptors, threshold=0.75):
    """
    Match face descriptors using ORB feature matching.
    Returns: (best_face_id, best_score)

    Lower score means better match.
    """
    if new_descriptor is None or not stored_descriptors:
        return None, 1.0

    best_match = None
    best_score = 1.0

    for face_id, descriptor in stored_descriptors.items():
        if descriptor is None:
            continue

        # Use brute-force matcher with Hamming distance
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

        try:
            matches = bf.match(new_descriptor, descriptor)

            if len(matches) > 5:  # Need sufficient matches
                # Calculate match quality (lower is better)
                avg_distance = sum(match.distance for match in matches) / len(matches)
                normalized_score = min(1.0, avg_distance / 100.0)

                if normalized_score < best_score:
                    best_score = normalized_score
                    best_match = face_id

        except Exception as e:
            print(f"Error matching features: {e}")
            continue

    return best_match, best_score


def is_same_face_by_location(current_face, previous_face,
                             iou_threshold=0.5,
                             overlap_threshold=0.7,
                             distance_threshold=0.3):
    """
    Determine if two face bounding boxes likely belong to the same person
    using multiple geometric measures.

    Args:
        current_face: Dict with 'x', 'y', 'w', 'h'
        previous_face: Dict with 'x', 'y', 'w', 'h'
        iou_threshold: Minimum IoU to consider faces the same
        overlap_threshold: Alternative overlap measure
        distance_threshold: Max normalized distance between centers

    Returns:
        bool: True if faces are likely the same
    """
    # 1. Calculate Intersection over Union (IoU)
    x_left = max(current_face['x'], previous_face['x'])
    y_top = max(current_face['y'], previous_face['y'])
    x_right = min(current_face['x'] + current_face['w'],
                  previous_face['x'] + previous_face['w'])
    y_bottom = min(current_face['y'] + current_face['h'],
                   previous_face['y'] + previous_face['h'])

    intersection_area = max(0, x_right - x_left) * max(0, y_bottom - y_top)

    current_area = current_face['w'] * current_face['h']
    previous_area = previous_face['w'] * previous_face['h']

    union_area = current_area + previous_area - intersection_area
    iou = intersection_area / union_area if union_area > 0 else 0

    # 2. Calculate center distance
    current_center_x = current_face['x'] + current_face['w'] / 2
    current_center_y = current_face['y'] + current_face['h'] / 2
    previous_center_x = previous_face['x'] + previous_face['w'] / 2
    previous_center_y = previous_face['y'] + previous_face['h'] / 2

    center_distance = ((current_center_x - previous_center_x) ** 2 +
                       (current_center_y - previous_center_y) ** 2) ** 0.5

    # Normalize by average face size
    avg_size = (current_face['w'] + current_face['h'] +
                previous_face['w'] + previous_face['h']) / 4
    normalized_distance = center_distance / avg_size if avg_size > 0 else float('inf')

    # 3. Calculate overlap ratio
    smaller_area = min(current_area, previous_area)
    overlap_ratio = intersection_area / smaller_area if smaller_area > 0 else 0

    # 4. Check size similarity
    width_ratio = min(current_face['w'], previous_face['w']) / max(current_face['w'], previous_face['w'])
    height_ratio = min(current_face['h'], previous_face['h']) / max(current_face['h'], previous_face['h'])
    size_ratio = width_ratio * height_ratio

    # Decision logic
    if iou >= iou_threshold:
        return True
    elif overlap_ratio >= overlap_threshold and normalized_distance <= distance_threshold:
        return True
    elif normalized_distance <= distance_threshold * 0.5 and size_ratio >= 0.7:
        return True

    return False


def create_kalman_filter():
    """
    Create and initialize a Kalman filter for tracking face position and velocity.
    State: [x, y, w, h, vx, vy]
    Measurement: [x, y, w, h]
    """
    kalman = cv2.KalmanFilter(6, 4)

    # State transition matrix (F)
    kalman.transitionMatrix = np.array([
        [1, 0, 0, 0, 1, 0],  # x = x + vx
        [0, 1, 0, 0, 0, 1],  # y = y + vy
        [0, 0, 1, 0, 0, 0],  # w = w
        [0, 0, 0, 1, 0, 0],  # h = h
        [0, 0, 0, 0, 1, 0],  # vx = vx
        [0, 0, 0, 0, 0, 1]  # vy = vy
    ], np.float32)

    # Measurement matrix (H)
    kalman.measurementMatrix = np.array([
        [1, 0, 0, 0, 0, 0],
        [0, 1, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0],
        [0, 0, 0, 1, 0, 0]
    ], np.float32)

    # Process noise covariance (Q) - uncertainty in model
    kalman.processNoiseCov = np.eye(6, dtype=np.float32) * 0.1
    kalman.processNoiseCov[4:, 4:] *= 0.5  # Higher noise for velocity

    # Measurement noise covariance (R) - uncertainty in measurements
    kalman.measurementNoiseCov = np.eye(4, dtype=np.float32) * 1.0

    # Error covariance (P) - initial uncertainty
    kalman.errorCovPre = np.eye(6, dtype=np.float32) * 10

    return kalman