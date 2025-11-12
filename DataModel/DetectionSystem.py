import os
import cv2
import tkinter as tk
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
        self.person_id = person_id  # Link to parent person
        self.last_seen = time.time()

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


class DetectionSystem:
    def __init__(self, db_path="Faces_db", video_path="test_videos/3.mov"):
        """
        Initialize the entire detection system.
        All global variables and configurations become instance attributes.
        """
        print("[INFO] Initializing Detection System...")
        
        # --- Setup & Configuration ---
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        self.video_path = video_path # Make video path an init parameter

        # Configuration constants
        self.CONFIDENCE_THRESHOLD = 0.6
        self.MIN_FACE_SIZE = (120, 120)
        self.PERSON_CONFIDENCE_THRESHOLD = 0.5
        # ... (all other config constants) ...
        
        # --- Threading & State ---
        self.frame_queue = queue.Queue(maxsize=self.FRAME_QUEUE_SIZE)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.last_frame_buffer = {"frame": None, "timestamp": 0.0}

        # --- Tracked Data ---
        self.tracked_persons = {}  # Was global 'tracked_persons'
        self.identified_faces = {} # Was global 'identified_faces'
        self.next_face_id = 0
        self.next_person_id = 0
        
        # ... (other 'global' variables) ...
        self.yolo_detect_face = []
        self.frame_count = 0

        # --- Models ---
        self.yolo_model = None
        self.yolo_face_model = None
        self.reid_model = None
        self.person_tracker = None
        self.face_cascade = None
        
        self.initialize_models() # Call helper method to load models
        
        # Get starting ID
        self.next_face_id = self.get_next_available_face_id()
        self.next_person_id = 1
        
        # Thread holders
        self.cam_thread = None
        self.proc_thread = None
        self.disp_thread = None
        self.watchdog_thread = None
        
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

        self.disp_thread = threading.Thread(target=self.display_thread_function)
        self.disp_thread.daemon = True
        self.disp_thread.start()

        self.watchdog_thread = threading.Thread(target=self.watchdog_thread_function)
        self.watchdog_thread.daemon = True
        self.watchdog_thread.start()
        
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
        
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        print("[INFO] Models loaded.")
    
    def extract_person_features(self,person_crop):
        
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
    
    def camera_thread_function(self):
        """Thread function to capture frames from camera."""
        
        video_path = os.path.join("test_videos", "1.mp4")
        print(f"[THREAD] Video thread started, attempting to open: {video_path}")

        # Initialize video capture with the file path instead of camera index (0)
        cap = cv2.VideoCapture(video_path)

        delay_s = 0.04  # Corresponds to your original ~25 FPS rate

        if not cap.isOpened():
            print(f"Error: Could not open video file at {video_path}. Check the path and file integrity.")
            self.stop_event.set()
            return

        # --- Get Original Video Dimensions ---
        original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Video Original Resolution: {original_width}x{original_height}")

        # Get the resolution once
        max_screen_width, max_screen_height = self.get_screen_resolution()

        target_width = original_width
        target_height = original_height

        if original_width > max_screen_width or original_height > max_screen_height:
            # Only scale down if the video is too large for the screen/limit
            scale_w = max_screen_width / original_width
            scale_h = max_screen_height / original_height
            scale_factor = min(scale_w, scale_h)

            target_width = int(original_width * scale_factor)
            target_height = int(original_height * scale_factor)

        while not self.stop_event.is_set():
            ret, frame = cap.read()
            # For testing - you can uncomment the next two lines to use static image
            # image_path = "E:\Campus\Data_Management_project\iiro.jpg"
            # frame = cv2.imread(image_path, cv2.IMREAD_COLOR)

            if not ret:
                # Check if we reached the end of the video
                if not frame is None:  # frame is None might happen if reading failed initially
                    print("Error: Failed to capture frame.")
                    time.sleep(0.1)
                    continue
                else:
                    print("Info: Reached end of video file.")
                    # Option 2: Stop the thread (recommended for processing a single video)
                    break

            if target_width != original_width or target_height != original_height:
                frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)

            # Always update the shared buffer
            with self.lock:
                self.last_frame_buffer["frame"] = frame.copy()
                self.last_frame_buffer["timestamp"] = time.time()

            # If queue is full, remove oldest frame
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except:
                    pass

            # Add new frame to queue
            try:
                self.frame_queue.put(frame, block=False)
            except:
                pass

            time.sleep(0.04)  # ~25 FPS capture

        cap.release()
        print("[THREAD] Camera thread stopped")
    
  
    def processing_thread_function(self):
        """Enhanced thread function to process frames with person and face detection"""
        print("[THREAD] Processing thread started")

        global next_person_id, tracked_persons, person_tracker

        frame_count = 0
        temp_face_path = "temp_face.jpg"
        last_processed_time = time.time()

        while not self.stop_event.is_set():
            try:
                if self.frame_queue.qsize() > 5:
                    # Discard frame if queue is backed up
                    frame = self.frame_queue.get(timeout=0.01)
                    print("[INFO] Processing thread skipping frame to reduce backlog.")
                    continue  # Skip all processing and grab the next frame immediately

                    # Normal frame retrieval
                frame = self.frame_queue.get(timeout=1.0)
                last_processed_time = time.time()
                frame_count += 1

                # 1. Detect persons using YOLO
                person_detections = self.detect_persons_yolo(frame)

                # 2. Update person tracker
                tracks = person_tracker.update_tracks(person_detections, frame=frame)

                # 3. Process tracked persons
                current_tracked_persons = {}

                for track in tracks:
                    if not track.is_confirmed():
                        continue

                    track_id = track.track_id
                    ltrb = track.to_ltrb()
                    px, py, px2, py2 = map(int, ltrb)
                    pw, ph = px2 - px, py2 - py

                    # Update or create person object
                    if track_id in tracked_persons:
                        person_obj = tracked_persons[track_id]
                        person_obj.update_position(px, py, pw, ph,
                                                track.confidence if hasattr(track, 'confidence') else 0.8)
                    else:
                        person_obj = Person(track_id, px, py, pw, ph,
                                            track.confidence if hasattr(track, 'confidence') else 0.8)
                        tracked_persons[track_id] = person_obj

                        # Extract Re-ID features
                        person_crop = frame[py:py + ph, px:px + pw]
                        features = self.extract_person_features(person_crop)
                        if features is not None:
                            person_obj.feature_vector = features

                    current_tracked_persons[track_id] = person_obj

                    # 4. Process faces within this person
                    face_ids = self.process_faces_in_person(frame, (px, py, pw, ph), track_id, temp_face_path)
                    print(f"Returned face id to person-{track_id} is {face_ids}")
                    # face_ids = []
                    # Update person's faces
                    person_obj.faces = {fid: self.identified_faces[fid] for fid in face_ids if fid in self.identified_faces}

                # 5. Clean up old persons and faces
                with self.lock:
                    # Remove persons not seen in current frame
                    persons_to_remove = []
                    for person_id, person_obj in tracked_persons.items():
                        if person_id not in current_tracked_persons:
                            if time.time() - person_obj.last_seen > 2.0:  # Remove if not seen for 2 seconds
                                persons_to_remove.append(person_id)

                    for person_id in persons_to_remove:
                        # Remove associated faces
                        faces_to_remove = [fid for fid, face in self.identified_faces.items() if face.person_id == person_id]
                        for face_id in faces_to_remove:
                            del self.identified_faces[face_id]
                        del tracked_persons[person_id]

            except queue.Empty:
                time.sleep(0.1)
                continue
            except Exception as e:
                print(f"Error in processing thread: {e}")
                time.sleep(0.1)

        # Clean up
        if os.path.exists(temp_face_path):
            try:
                os.remove(temp_face_path)
            except:
                pass

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


    def get_next_available_face_id():
        """Get next available face ID by scanning database"""
        highest_id = -1
        try:
            existing_dirs = [d for d in os.listdir(db_path) if os.path.isdir(os.path.join(db_path, d))]

            for d in existing_dirs:
                if d.startswith("User_"):
                    parts = d.split('_')
                    if len(parts) == 2 and parts[1].isdigit():
                        current_id = int(parts[1])
                        if current_id > highest_id:
                            highest_id = current_id
                elif d.isdigit():
                    current_id = int(d)
                    if current_id > highest_id:
                        highest_id = current_id
        except FileNotFoundError:
            print(f"Database path not found: {db_path}")
            return 0

        return highest_id + 1

    