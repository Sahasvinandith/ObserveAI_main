import os
import cv2
import tkinter as tk
import math
import threading
import time
import queue
import numpy as np
from face_detection import *
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import torch
import torch.nn as nn
from torchvision.transforms import transforms
from Reid_model import ReIDModel


class Person:
    def __init__(self, person_id, x, y, w, h, confidence):
        self.person_id = person_id
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.confidence = confidence
        self.faces = {}  # Dictionary of faces detected within this person {face_id: Face}
        self.last_seen = time.time()
        self.feature_vector = None  # Re-ID feature vector

    def update_position(self, x, y, w, h, confidence):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.confidence = confidence
        self.last_seen = time.time()

    def add_face(self, face):
        self.faces[face.face_id] = face

    def display(self):
        print(f"person id: {self.person_id}, person face name:{self.faces}")

    def get_primary_face_name(self):
        """Return the name of the most confident face in this person"""
        if not self.faces:
            return "Unknown"

        best_face = min(self.faces.values(), key=lambda f: f.confidence)
        return best_face.name if best_face.name != "Unknown" else "Unknown"


class Face:
    def __init__(self, name, x, y, w, h, face_id, confidence, tracker, person_id=None):
        self.name = name
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.face_id = face_id
        self.confidence = confidence
        self.tracker = tracker
        self.person_id = person_id
        self.last_seen = time.time()
        self.is_recognizing = False # Flag for async queue

    def position_update(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.last_seen = time.time()

    def position_and_tracker_update(self, x, y, w, h, tracker):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.tracker = tracker
        self.last_seen = time.time()

    # --- THIS WAS MISSING ---
    def get_center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

def get_screen_resolution():
    try:
        root = tk.Tk()
        # Prevents a main window from popping up
        root.withdraw()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.destroy()
        return screen_width, screen_height
    except:
        return 1280,720


class DetectionSystem:
    def __init__(self, db_path="Faces_db", video_path="test_videos/1.mp4"):
        """
        Initialize the entire detection system.
        All global variables and configurations become instance attributes.
        """
        print("[INFO] Initializing Detection System...")

        # --- Setup & Configuration ---
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        self.video_path = video_path  # Make video path an init parameter

        # Configuration
        self.RECOGNITION_QUEUE_SIZE = 10  # New Queue size
        self.DISTANCE_THRESHOLD = 50

        # Configuration
        self.CONFIDENCE_THRESHOLD = 0.3  # Lower is better match
        self.MIN_FACE_SIZE = (120, 120)  # Minimum face size for recognition
        self.MAX_FACES_PER_USER = 10  # Maximum number of face images to store per user
        self.QUALITY_THRESHOLD = 100  # Minimum quality score to save face (higher is better)
        self.FRAME_QUEUE_SIZE = 10  # Size of frame queue between threads
        self.FACE_FEATURE_THRESHOLD = 0.68  # Confidence of detected face using trackers

        # Shared resources
        self.frame_queue = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
        self.recognition_queue = queue.Queue(maxsize=self.RECOGNITION_QUEUE_SIZE)

        self.stop_event = threading.Event()
        self.current_identity = {"name": "Unknown", "confidence": 1.0}
        self.enrollment_status = {"in_progress": False, "user_folder": None, "count": 0}
        self.lock = threading.Lock()
        self.identified_faces: dict[str, Face] = {}
        self.last_frame_buffer = {"frame": None, "timestamp": 0.0}

        # --- Tracked Data ---
        self.tracked_persons = {}  # Was global 'tracked_persons'
        self.identified_faces = {}  # Was global 'identified_faces'
        self.next_face_id = 0
        self.next_person_id = 0

        # Person detection and tracking configurations
        self.PERSON_CONFIDENCE_THRESHOLD = 0.5  # Minimum confidence for person detection
        self.MIN_PERSON_SIZE = (50, 100)  # Minimum person bounding box size (width, height)
        self.PERSON_TRACKING_MAX_AGE = 30  # Maximum frames to keep track without detection
        self.PERSON_TRACKING_N_INIT = 3  # Number of frames to confirm a track

        # ... (other 'global' variables) ...
        self.yolo_detect_face = []
        self.frame_count = 0

        # --- Models ---
        self.yolo_model = None
        self.yolo_face_model = None
        self.reid_model = None
        self.person_tracker = None
        self.face_cascade = None

        self.initialize_models()  # Call helper method to load models

        # Get starting ID
        self.next_face_id = self.get_next_available_face_id()
        self.next_person_id = 1

        # Thread holders
        self.cam_thread = None
        self.proc_thread = None
        self.disp_thread = None
        self.watchdog_thread = None
        self.recog_thread = None

        print("[INFO] System initialized successfully.")

    def start(self):
        """Start all processing threads."""
        print("[INFO] Starting all threads...")
        self.stop_event.clear()

        self.cam_thread = threading.Thread(target=self.camera_thread_function)
        self.cam_thread.daemon = True
        self.cam_thread.start()

        self.proc_thread = threading.Thread(target=self.processing_thread_function)
        self.proc_thread.daemon = True
        self.proc_thread.start()

        # NEW: Recognition Worker Thread
        self.recog_thread = threading.Thread(target=self.recognition_worker_function)
        self.recog_thread.daemon = True
        self.recog_thread.start()

        self.disp_thread = threading.Thread(target=self.display_thread_function)
        self.disp_thread.daemon = True
        self.disp_thread.start()

        self.watchdog_thread = threading.Thread(target=self.watchdog_thread_function)
        self.watchdog_thread.daemon = True
        self.watchdog_thread.start()

    def recognition_worker_function(self):
        print("[THREAD] Recognition Worker started")
        while not self.stop_event.is_set():
            try:
                # Get a task: (face_id, face_image_numpy)
                task = self.recognition_queue.get(timeout=1.0)
                face_id, face_img = task

                # Run DeepFace (This is the slow part, but it's isolated now)
                name, confidence = recognize_face(face_img)

                # Update the Global Dictionary Safely
                with self.lock:
                    if face_id in self.identified_faces:
                        face_obj = self.identified_faces[face_id]

                        if name == "Unknown":
                            try:
                                # 1. Get the next available ID (e.g., 5)
                                new_id_num = self.get_next_available_face_id()
                                new_user_folder = f"User_{new_id_num}"

                                # 2. Create the directory: Faces_db/User_5
                                new_folder_path = os.path.join(self.db_path, new_user_folder)
                                os.makedirs(new_folder_path, exist_ok=True)

                                # 3. Save the image as 1.jpg
                                save_path = os.path.join(new_folder_path, "1.jpg")
                                cv2.imwrite(save_path, face_img)

                                print(f"[STORAGE] Unknown face saved as new user: {new_user_folder}")

                                # 4. Update the name in the live system so we see "User_5" immediately
                                face_obj.name = new_user_folder

                            except Exception as e:
                                print(f"[ERROR] Could not save new user: {e}")
                                face_obj.name = f"Unknown_{face_id}"

                        else:
                            face_obj.name = name

                        face_obj.confidence = confidence
                        face_obj.is_recognizing = False  # Unlock the flag

                        print(f"[RECOG] Face {face_id} identified as {name}")

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[RECOG ERROR] {e}")
                continue
        print("[THREAD] Recognition Worker stopped")

    def stop(self):
        """Signal all threads to stop and wait for them to join."""
        print("[INFO] Stopping all threads...")
        self.stop_event.set()
        # Wait for threads to finish
        if self.cam_thread:
            self.cam_thread.join(timeout=2.0)
        if self.proc_thread:
            self.proc_thread.join(timeout=2.0)
        if self.disp_thread:
            self.disp_thread.join(timeout=2.0)
        if self.watchdog_thread:
            self.watchdog_thread.join(timeout=2.0)

        cv2.destroyAllWindows()
        print("[INFO] System shut down.")

    def initialize_models(self):
        """Initialize and load all models."""
        # Note: 'global' keywords are gone. We use 'self.'
        self.yolo_model = YOLO("yolov8n.pt")
        self.yolo_face_model = YOLO("yolov11n-face.pt")

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.reid_model = ReIDModel().to(device)
        self.reid_model.eval()
        self.person_tracker = DeepSort(max_age=self.PERSON_TRACKING_MAX_AGE,
                                       n_init=self.PERSON_TRACKING_N_INIT)
        print("[INFO] Models loaded.")

    def extract_person_features(self, person_crop):
        """Extract Re-ID features from person crop"""
        reid_model = self.reid_model
        try:
            if person_crop.shape[0] == 0 or person_crop.shape[1] == 0:
                return None
            # Preprocess for Re-ID model
            preprocess = transforms.Compose([
                transforms.ToPILImage(),
                transforms.Resize((256, 128)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            processed_image = preprocess(cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB))
            processed_image = processed_image.unsqueeze(0).to(device)
            with torch.no_grad():
                features = reid_model(processed_image)
            return features.squeeze().cpu().numpy()
        except Exception as e:
            print(f"Error extracting person features: {e}")
            return None

    def detect_persons_yolo(self,frame):
        """Detect persons using YOLO"""
        results = self.yolo_model(frame)
        detections = []

        for r in results:
            for box in r.boxes:
                # Filter for 'person' class (class ID 0 in COCO dataset)
                if int(box.cls[0]) == 0:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])

                    # Filter by confidence and minimum size
                    w, h = x2 - x1, y2 - y1
                    if conf >= self.PERSON_CONFIDENCE_THRESHOLD and w >= self.MIN_PERSON_SIZE[0] and h >= self.MIN_PERSON_SIZE[1]:
                        # DeepSORT expects [x, y, w, h] format
                        detections.append(([x1, y1, w, h], conf, int(box.cls[0])))

        return detections

    def camera_thread_function(self):
        """Thread function to capture frames from camera."""

        video_path = os.path.join("test_videos", "1.mp4")
        print(f"[THREAD] Video thread started, attempting to open: {video_path}")

        # Initialize video capture with the file path instead of camera index (0)
        cap = cv2.VideoCapture(video_path)
        w,h = get_screen_resolution()

        while not self.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                print("Info: End of video.")
                break

            # Resize logic
            if frame.shape[1] > w:
                scale = w / frame.shape[1]
                frame = cv2.resize(frame, (0, 0), fx=scale, fy=scale)

            # --- LAG FIX: Shared Buffer (For Display) ---
            with self.lock:
                self.last_frame_buffer["frame"] = frame.copy()
                self.last_frame_buffer["timestamp"] = time.time()

        # --- Get Original Video Dimensions ---
        original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Video Original Resolution: {original_width}x{original_height}")

        # Get the resolution once
        max_screen_width, max_screen_height = get_screen_resolution()

        if original_width > max_screen_width or original_height > max_screen_height:
            # Only scale down if the video is too large for the screen/limit
            scale_w = max_screen_width / original_width
            scale_h = max_screen_height / original_height
            scale_factor = min(scale_w, scale_h)

            target_width = int(original_width * scale_factor)
            target_height = int(original_height * scale_factor)

        while not self.stop_event.is_set():
            ret, frame = cap.read()
            if not ret: break

            # Resize logic ... (keep existing)

            # Always update the shared buffer (For Display Thread)
            with self.lock:
                self.last_frame_buffer["frame"] = frame.copy()
                self.last_frame_buffer["timestamp"] = time.time()

            # --- LAG FIX: Leaky Bucket ---
            # If queue is full, remove the oldest item to make space
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()  # Drop oldest frame
                except queue.Empty:
                    pass

            try:
                self.frame_queue.put(frame,block=False)
            except queue.Full:
                pass
            time.sleep(0.03)  # ~30 FPS captur

        cap.release()
        print("[THREAD] Camera thread stopped")

    def process_faces_in_person(self, frame, person_bbox, person_id, temp_face_path):
        px, py, pw, ph = person_bbox
        px = max(0, px);
        py = max(0, py)

        detected_faces_ids = []

        # --- PHASE 1: UPDATE TRACKERS (Fast) ---
        person_faces = [f for f in self.identified_faces.values() if f.person_id == person_id]
        active_tracked_faces = []

        for face_obj in person_faces:
            success, bbox = face_obj.tracker.update(frame)
            if success:
                x, y, w, h = [int(v) for v in bbox]
                face_obj.position_update(x, y, w, h)
                detected_faces_ids.append(face_obj.face_id)
                active_tracked_faces.append(face_obj)

        # --- PHASE 2: DETECT NEW FACES ---
        # Check if we need to run detection (if no faces tracked or periodically)
        should_run_detection = (len(active_tracked_faces) == 0) or (self.frame_count % 10 == 0)

        if should_run_detection:
            person_crop = frame[py:py + ph, px:px + pw]
            if person_crop.size > 0:
                results = self.yolo_face_model(person_crop, verbose=False)

                for r in results:
                    for box in r.boxes:
                        # Coords
                        lx1, ly1, lx2, ly2 = map(int, box.xyxy[0])
                        gx = px + lx1;
                        gy = py + ly1
                        gw = lx2 - lx1;
                        gh = ly2 - ly1
                        new_center = (gx + gw // 2, gy + gh // 2)

                        # Match with existing
                        is_known_face = False
                        for tracked_face in active_tracked_faces:
                            existing_center = tracked_face.get_center()
                            dist = math.dist(new_center, existing_center)
                            if dist < self.DISTANCE_THRESHOLD:
                                tracked_face.position_update(gx, gy, gw, gh)
                                is_known_face = True
                                break

                        if is_known_face: continue

                        # --- PHASE 4: NEW FACE FOUND ---
                        # Try to push to queue FIRST. If full, skip this face entirely for now.
                        # This prevents "Zombie" faces that stay stuck on "Scanning..."
                        try:
                            face_img = frame[gy:gy + gh, gx:gx + gw].copy()

                            if face_img.size > 0:
                                # Generate ID
                                face_id = str(self.next_face_id)

                                # Try to push to queue
                                self.recognition_queue.put((face_id, face_img), block=False)

                                # SUCCESS: Now we create the object
                                self.next_face_id += 1
                                print(f"[QUEUE] Pushed Face {face_id} for recognition")

                                # Initialize Tracker
                                try:
                                    tracker = cv2.TrackerCSRT_create()
                                except:
                                    tracker = cv2.legacy.TrackerCSRT_create()
                                tracker.init(frame, (gx, gy, gw, gh))

                                # Create Face Object
                                new_face = Face("Scanning...", gx, gy, gw, gh, face_id, 0.0, tracker, person_id)
                                new_face.is_recognizing = True

                                with self.lock:
                                    self.identified_faces[face_id] = new_face

                                detected_faces_ids.append(face_id)

                        except queue.Full:
                            #
                            # If queue is full, we DO NOT create the face object.
                            # We just ignore it this frame. It will be detected again in the next frame.
                            pass

        return detected_faces_ids

    def processing_thread_function(self):
        """Enhanced thread function to process frames with person and face detection"""
        print("[THREAD] Processing thread started")

        while not self.stop_event.is_set():
            try:
                # --- LAG FIX: Queue Draining ---
                # Get the freshest frame possible, discard old backlog
                frame = None
                while not self.frame_queue.empty():
                    try:
                        frame = self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass

                # If queue was empty, wait for a new frame
                if frame is None:
                    try:
                        frame = self.frame_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue

                self.frame_count += 1

                # 1. Detect persons using YOLO
                results = self.yolo_model(frame, verbose=False)
                detections = []
                for r in results:
                    for box in r.boxes:
                        if int(box.cls[0]) == 0:
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            conf = float(box.conf[0])
                            if conf >= self.PERSON_CONFIDENCE_THRESHOLD:
                                detections.append(([x1, y1, x2 - x1, y2 - y1], conf, 0))

                # 2. Update person tracker
                tracks = self.person_tracker.update_tracks(detections, frame=frame)

                # 3. Process tracked persons
                current_tracked_ids = []

                for track in tracks:
                    if not track.is_confirmed():
                        continue

                    tid = track.track_id
                    current_tracked_ids.append(tid)
                    l, t, r, b = map(int, track.to_ltrb())
                    w, h = r - l, b - t

                    # Update/Create Person
                    if tid in self.tracked_persons:
                        self.tracked_persons[tid].update_position(l, t, w, h, 0.9)
                    else:
                        person_obj = Person(tid, l, t, w, h, 0.9)
                        # Optional: Extract features once
                        crop = frame[t:t + h, l:l + w]
                        person_obj.feature_vector = self.extract_person_features(crop)
                        self.tracked_persons[tid] = person_obj

                    # 4. Process faces (The new Async Logic)
                    face_ids = self.process_faces_in_person(frame, (l, t, w, h), tid, None)

                    # Link faces to person
                    self.tracked_persons[tid].faces = {fid: self.identified_faces[fid] for fid in face_ids if
                                                       fid in self.identified_faces}

                # 5. Cleanup
                with self.lock:
                    # Cleanup Persons
                    for pid in list(self.tracked_persons.keys()):
                        if pid not in current_tracked_ids:
                            if time.time() - self.tracked_persons[pid].last_seen > 2.0:
                                # Also remove faces
                                faces_to_del = [fid for fid, f in self.identified_faces.items() if f.person_id == pid]
                                for fid in faces_to_del:
                                    if fid in self.identified_faces: del self.identified_faces[fid]
                                del self.tracked_persons[pid]


            except Exception as e:
                print(f"Proc Error: {e}")
                time.sleep(0.1)

        print("[THREAD] Processing thread stopped")

    def watchdog_thread_function(self):
        """Thread to monitor and recover from potential issues."""
        print("[THREAD] Watchdog thread started")

        while not self.stop_event.is_set():
            try:
                time.sleep(1.0)
                current_time = time.time()

                # Check frame buffer health
                with self.lock:
                    if self.last_frame_buffer["timestamp"] > 0:
                        frame_age = current_time - self.last_frame_buffer["timestamp"]
                        if frame_age > 3.0:
                            print("[WATCHDOG] No new frames detected for 3 seconds!")

                # Check queue health
                queue_size = self.frame_queue.qsize()
                if queue_size == 0:
                    with self.lock:
                        if self.last_frame_buffer["frame"] is not None:
                            try:
                                self.frame_queue.put(self.last_frame_buffer["frame"].copy(), block=False)
                            except:
                                pass

            except Exception as e:
                print(f"[WATCHDOG] Error: {e}")

        print("[THREAD] Watchdog thread stopped")

    def get_next_available_face_id(self):
        """Get next available face ID by scanning database for User_X folders"""
        highest_id = 0

        # Ensure the database directory exists
        if not os.path.exists(self.db_path):
            return 1

        try:
            # List all items in Faces_db
            existing_items = os.listdir(self.db_path)

            for item in existing_items:
                full_path = os.path.join(self.db_path, item)

                # We only care about directories starting with "User_"
                if os.path.isdir(full_path) and item.startswith("User_"):
                    try:
                        # Extract the number: "User_5" -> 5
                        parts = item.split('_')
                        if len(parts) == 2 and parts[1].isdigit():
                            current_id = int(parts[1])
                            if current_id > highest_id:
                                highest_id = current_id
                    except ValueError:
                        continue

        except Exception as e:
            print(f"[ERROR] scanning DB: {e}")
            return 1

        return highest_id + 1

    def display_thread_function(self):
        print("[THREAD] Display thread started")

        while not self.stop_event.is_set():
            # 1. Get Frame from Buffer
            frame = None
            with self.lock:
                if self.last_frame_buffer["frame"] is not None:
                    frame = self.last_frame_buffer["frame"].copy()

            if frame is None:
                time.sleep(0.01)
                continue

            # 2. Snapshot Data (Safe Copy)
            with self.lock:
                display_persons = list(self.tracked_persons.values())
                q_size = self.recognition_queue.qsize()

            # 3. Drawing Loop
            for person_obj in display_persons:
                pid = int(person_obj.person_id)
                px, py, pw, ph = person_obj.x, person_obj.y, person_obj.w, person_obj.h

                # Color based on ID
                color = ((pid * 50) % 255, (pid * 100) % 255, (pid * 150) % 255)

                cv2.rectangle(frame, (px, py), (px + pw, py + ph), color, 3)

                # Person Label
                prim_face = person_obj.get_primary_face_name()
                cv2.putText(frame, f"ID:{pid} {prim_face}", (px, py - 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                # Draw Faces
                try:
                    for face_obj in person_obj.faces.values():
                        fx, fy, fw, fh = face_obj.x, face_obj.y, face_obj.w, face_obj.h

                        if face_obj.is_recognizing:
                            f_color = (0, 255, 255)  # Yellow
                            label = "Scanning..."
                        else:
                            f_color = (0, 0, 255)  # Red
                            label = f"{face_obj.name} ({face_obj.confidence:.2f})"

                        cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), f_color, 2)
                        cv2.putText(frame, label, (fx, fy - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, f_color, 1)
                except RuntimeError:
                    pass

            # 4. Status Overlay
            cv2.putText(frame, f"Recog Queue: {q_size}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow("Enhanced Person Tracking + Face Recognition System", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.stop_event.set()
                break

        cv2.destroyAllWindows()
        print("[THREAD] Display thread stopped")

