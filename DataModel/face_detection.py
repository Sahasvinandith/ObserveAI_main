from datetime import datetime
import cv2
import os
import numpy as np
from deepface import DeepFace

# Setup
db_path = "Faces_db"
os.makedirs(db_path, exist_ok=True)

# Configuration
CONFIDENCE_THRESHOLD = 0.6  # Lower is better match
MIN_FACE_SIZE = (120, 120)  # Minimum face size for recognition
MAX_FACES_PER_USER = 10  # Maximum number of face images to store per user
QUALITY_THRESHOLD = 100  # Minimum quality score to save face (higher is better)
FRAME_QUEUE_SIZE = 10  # Size of frame queue between threads

# Feature detector for ORB
orb = cv2.ORB_create(nfeatures=100, scaleFactor=1.2, WTA_K=2, scoreType=cv2.ORB_HARRIS_SCORE)


def create_kalman_filter():
    """Create and initialize a Kalman filter for tracking face position and velocity."""
    kalman = cv2.KalmanFilter(6, 4)  # 6 state variables (x, y, w, h, vx, vy), 4 measurement variables (x, y, w, h)

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

    # Process noise covariance matrix (Q) represent uncertanity in the state of transitiion model
    kalman.processNoiseCov = np.eye(6, dtype=np.float32) * 0.1
    kalman.processNoiseCov[4:, 4:] *= 0.5  # Higher noise for velocity

    # Measurement noise covariance matrix (R)
    kalman.measurementNoiseCov = np.eye(4, dtype=np.float32) * 1.0

    # Error covariance matrix (P)
    kalman.errorCovPre = np.eye(6, dtype=np.float32) * 10

    return kalman


def similar_face_exists(new_desc, existing_descs, threshold=0.6):
    """Check if a similar face already exists in our tracked faces"""
    for face_id, desc in existing_descs.items():
        # Compute similarity using feature matching
        # You can use your existing feature matching function here
        match_id, score = match_face_features(new_desc, {face_id: desc})
        if score < threshold:
            return match_id
    return None


def extract_face_features(face_img):
    """Extract ORB features from a face image."""
    try:
        # Convert to grayscale if not already
        if len(face_img.shape) > 2:
            gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        else:
            gray = face_img

        # Detect keypoints and compute descriptors
        keypoints = orb.detect(gray, None)
        keypoints, descriptors = orb.compute(gray, keypoints)

        if descriptors is None or len(keypoints) < 5:
            return None, None

        return keypoints, descriptors
    except Exception as e:
        print(f"Error extracting face features: {e}")
        return None, None


def is_same_face_by_location(current_face, previous_face, iou_threshold=0.5, overlap_threshold=0.7, distance_threshold=0.3):
    """
    Determine if two face bounding boxes likely belong to the same person.

    Args:
        current_face: Dict containing 'x', 'y', 'w', 'h' of current face
        previous_face: Dict containing 'x', 'y', 'w', 'h' of previous face
        iou_threshold: Minimum Intersection over Union to consider faces the same
        overlap_threshold: Alternative overlap measure threshold
        distance_threshold: Maximum normalized distance between centers relative to box size

    Returns:
        bool: True if faces are likely the same person, False otherwise
    """
    # 1. Calculate Intersection over Union (IoU)
    # Get coordinates of intersection rectangle
    x_left = max(current_face['x'], previous_face['x'])
    y_top = max(current_face['y'], previous_face['y'])
    x_right = min(current_face['x'] + current_face['w'], previous_face['x'] + previous_face['w'])
    y_bottom = min(current_face['y'] + current_face['h'], previous_face['y'] + previous_face['h'])

    # Calculate area of intersection rectangle
    intersection_area = max(0, x_right - x_left) * max(0, y_bottom - y_top)

    # Calculate area of both bounding boxes
    current_area = current_face['w'] * current_face['h']
    previous_area = previous_face['w'] * previous_face['h']

    # Calculate IoU
    union_area = current_area + previous_area - intersection_area
    iou = intersection_area / union_area if union_area > 0 else 0

    # 2. Calculate centers and distance between them
    current_center_x = current_face['x'] + current_face['w'] / 2
    current_center_y = current_face['y'] + current_face['h'] / 2
    previous_center_x = previous_face['x'] + previous_face['w'] / 2
    previous_center_y = previous_face['y'] + previous_face['h'] / 2

    # Euclidean distance between centers
    center_distance = ((current_center_x - previous_center_x) ** 2 +
                       (current_center_y - previous_center_y) ** 2) ** 0.5

    # Normalize distance by the average of face sizes
    avg_size = (current_face['w'] + current_face['h'] + previous_face['w'] + previous_face['h']) / 4
    normalized_distance = center_distance / avg_size if avg_size > 0 else float('inf')

    # 3. Calculate overlap ratio (intersection area / smaller box area)
    smaller_area = min(current_area, previous_area)
    overlap_ratio = intersection_area / smaller_area if smaller_area > 0 else 0

    # 4. Check size ratio (to ensure faces are similar in size)
    width_ratio = min(current_face['w'], previous_face['w']) / max(current_face['w'], previous_face['w'])
    height_ratio = min(current_face['h'], previous_face['h']) / max(current_face['h'], previous_face['h'])
    size_ratio = width_ratio * height_ratio

    # Decision making - return True if the faces are likely the same
    if iou >= iou_threshold:
        return True
    elif overlap_ratio >= overlap_threshold and normalized_distance <= distance_threshold:
        return True
    elif normalized_distance <= distance_threshold * 0.5 and size_ratio >= 0.7:
        # Very close centers and similar sizes
        return True

    return False


def match_face_features(new_descriptor, stored_descriptors, threshold=0.75):
    """Match face descriptors using feature matching."""
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


def calculate_face_quality(face_img):
    """Calculate a quality score for a face image based on clarity and lighting."""
    # Convert to grayscale if not already
    if len(face_img.shape) > 2:
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
    else:
        gray = face_img

    # 1. Calculate variance of Laplacian (measure of focus/sharpness)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

    # 2. Calculate histogram balance (measure of good lighting)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    hist_normalized = hist / hist.sum()
    hist_distribution = np.sum(-hist_normalized * np.log2(hist_normalized + 1e-10))  # Entropy

    # 3. Calculate face size ratio (larger is better)
    face_size_ratio = (face_img.shape[0] * face_img.shape[1]) / (640 * 480)

    # Combine the measures into a quality score
    quality_score = (laplacian_var * 0.5) + (hist_distribution * 50) + (face_size_ratio * 50)

    return quality_score


# def recognize_face(face_img):
#     """Compare a face with all users in the database."""
#     print("Recognize with deepface::")
#     try:
#         # First check if the database has any entries
#         if not any(os.path.isdir(os.path.join(db_path, d)) for d in os.listdir(db_path)):
#             print("No users in database.")
#             return "Unknown", 1.0

#         best_match = "Unknown"
#         best_confidence = 0.3

#         # Use DeepFace's verify function with each user folder
#         for user_folder in os.listdir(db_path):
#             print("CHECKING USER FOLDER: ", user_folder)
#             user_path = os.path.join(db_path, user_folder)
#             if not os.path.isdir(user_path):
#                 print("User folder does not exist, skipping.")
#                 continue

#             image_files = [f for f in os.listdir(user_path) if f.endswith(('.jpg', '.jpeg', '.png'))]
#             if not image_files:
#                 print("No images in user folder, skipping.")
#                 continue
#             print("Found image files: ", image_files)

#             # Try to verify against multiple reference images in the folder
#             for img_file in image_files[:3]:  # Check up to 3 images per user for speed
#                 reference_img = os.path.join(user_path, img_file)
#                 try:
#                     print("Verifying with image: ")
#                     result = DeepFace.verify(img1_path=face_img,
#                                              img2_path=reference_img,
#                                              enforce_detection=False,
#                                              model_name="ArcFace",
#                                              detector_backend="skip") #VGG-Face or any other model. please rever the doc inside the project folder
                    
#                     print("result: ", result)

#                     if result["verified"] and (result["distance"] < best_confidence):
#                         best_match = user_folder
#                         best_confidence = result["distance"]
#                         # If we found a very good match, break early
#                         if best_confidence < 0.2:
#                             break
#                 except Exception as e:
#                     print(f"Error verifying with image {img_file}: {e}")
#                     continue

#             # If we found a very good match, break out of user loop too
#             if best_confidence < 0.2:
#                 break

#         return best_match, best_confidence
#     except Exception as e:
#         print(f"Recognition error: {e}")
#         return "Unknown", 1.0

def recognize_face(face_img):
    """
    Compare a face with all users in the database using DeepFace.find
    This is much faster than looping through verify().
    """
    print("Recognize with deepface::")
    try:
        # Check if DB has users
        if not os.path.exists(db_path) or not os.listdir(db_path):
             return "Unknown", 1.0

        # DeepFace.find automatically searches the DB_PATH
        # It returns a list of pandas dataframes
        dfs = DeepFace.find(img_path=face_img, 
                            db_path=db_path, 
                            model_name="ArcFace", 
                            detector_backend="skip", 
                            enforce_detection=False, 
                            silent=True)
        
        if len(dfs) > 0 and not dfs[0].empty:
            # Get the first result (closest match)
            match = dfs[0].iloc[0]
            identity_path = match['identity']
            distance = match['distance'] # Lower is better
            
            # The identity_path will be something like "Faces_db/User_Name/image.jpg"
            # We need to extract just the "User_Name" folder
            user_folder = os.path.basename(os.path.dirname(identity_path))
            
            # ArcFace threshold is usually around 0.68, but for strict matching use 0.4 or 0.5
            if distance < 0.5: 
                return user_folder, distance
                
        return "Unknown", 1.0

    except Exception as e:
        print(f"Recognition error: {e}")
        return "Unknown", 1.0

def update_user_faces(user_folder, face_img, quality_score):
    """Update a user's face database with better quality images."""
    try:
        print("updating user folder: ",user_folder)
        user_path = os.path.join(db_path, str(user_folder))
        os.makedirs(user_path, exist_ok=True)

        # Get existing images and their quality scores
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

        # If we have too many images, replace the worst one
        if len(images) >= MAX_FACES_PER_USER:
            # Only replace if new image is better than the worst one
            if quality_score > images[0][1]:
                os.remove(images[0][0])
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_file = os.path.join(user_path, f"face_{timestamp}_q{quality_score:.1f}.jpg")
                cv2.imwrite(new_file, face_img)
                print(f"[UPDATED] Replaced low quality face with better one (q: {quality_score:.1f}) for {user_folder}")
        else:
            # Add new image
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_file = os.path.join(user_path, f"face_{timestamp}_q{quality_score:.1f}.jpg")
            cv2.imwrite(new_file, face_img)
            print(f"[ADDED] New face image (q: {quality_score:.1f}) for {user_folder}")

    except Exception as e:
        print(f"Error updating user faces: {e}")
