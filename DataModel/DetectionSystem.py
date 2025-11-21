import os
import cv2
import tkinter as tk
import math
import threading
import time
import queue
import numpy as np
from DataModel.face_detection import *
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import torch
import torch.nn as nn
from torchvision.transforms import transforms
from DataModel.Reid_model import ReIDModel
import traceback
# At the top of main/MainWindow.py


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
    def __init__(self,camera_name, db_path="Faces_db",camera_buffer=None, output_callback=None):
        """
        Initialize the entire detection system.
        All global variables and configurations become instance attributes.
        """
        print("[INFO] Initializing Detection System...")

        # --- Setup & Configuration ---
        self.camera_name = camera_name
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        
        self.camera_buffer = camera_buffer  # Camera buffer passed from main 
        self.output_callback = output_callback  # Output callback function

    

        # Configuration
        self.CONFIDENCE_THRESHOLD = 0.3  # Lower is better match
        self.MIN_FACE_SIZE = (120, 120)  # Minimum face size for recognition
        self.MAX_FACES_PER_USER = 10  # Maximum number of face images to store per user
        self.QUALITY_THRESHOLD = 100  # Minimum quality score to save face (higher is better)
        self.FRAME_QUEUE_SIZE = 10  # Size of frame queue between threads
        self.FACE_FEATURE_THRESHOLD = 0.68  # Confidence of detected face using trackers

        # Shared resources
        self.frame_queue = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
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

        # self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
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
        """Thread function to capture frames from camera buffers."""
        print("[THREAD] Camera thread started, using camera buffers from Main System")

        while not self.stop_event.is_set():
            try:
                # Fetch the latest frame from the camera buffer
                with self.lock:
                    if self.camera_buffer and not self.camera_buffer.empty():
                        frame = self.camera_buffer.get()
                    else:
                        time.sleep(0.01)  # Wait briefly if no frame is available
                        continue

                # Always update the shared buffer
                self.last_frame_buffer["frame"] = frame.copy()
                self.last_frame_buffer["timestamp"] = time.time()

                # If queue is full, remove the oldest frame
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except queue.Empty:
                        pass

                # Add the new frame to the queue
                try:
                    self.frame_queue.put(frame, block=False)
                except queue.Full:
                    pass

                time.sleep(0.04)  # ~25 FPS capture rate

            except Exception as e:
                print(f"[ERROR] Camera thread encountered an error: {e}")
                time.sleep(0.1)

        print("[THREAD] Camera thread stopped")

    def process_faces_in_person(self,frame, person_bbox, person_id, temp_face_path):
        """Process faces within a detected person"""
        px, py, pw, ph = person_bbox

        # Extract person region
        person_crop = frame[py:py + ph, px:px + pw]

        # Detect faces within person region
        results = self.yolo_face_model(person_crop, verbose=False)

        detected_faces = []

        for r in results:
            print("Doing face scan:::::")

            # Iterate through detected bounding boxes (YOLO already filters by confidence)
            for box in r.boxes:
                print("Doing face scan2:::::")
                # YOLO-Face models are typically trained only for faces, so class ID check is optional.

                # Get detection coordinates [x1, y1, x2, y2] relative to the person_crop
                fx1, fy1, fx2, fy2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])

                # Convert to [x, y, w, h] format
                fx, fy = fx1, fy1
                fw, fh = fx2 - fx1, fy2 - fy1

                # Convert face coordinates to global frame coordinates
                global_fx = px + fx
                global_fy = py + fy

                # finished finalizing parameters related to the face image (px,py,pw,ph)

                # Check if face is already tracked
                is_already_tracked = False
                existing_face_id = None

                temp_bbox_arr = []

                for face_id, face_obj in self.identified_faces.items():
                    if face_obj.person_id == person_id:  # check if face object belong to person already  identified
                        face_obj.position_update(global_fx, global_fy, fw, fh)  # probably trying to check by iou
                        # iou = get_iou((global_fx, global_fy, fw, fh), (face_obj.x, face_obj.y, face_obj.w, face_obj.h))
                        # if iou > 0.6:
                        #     is_already_tracked = True
                        #     # Update face position
                        #     face_obj.position_update(global_fx, global_fy, fw, fh)  # probably trying to check by iou
                        #     continue
                        is_already_tracked = True
                        detected_faces.append(face_id)
                        break

                    success, bbox = face_obj.tracker.update(
                        person_crop)  # check if tracker can find the face inside the persons bbox
                    if success:
                        print(f"Detection by tracker is success. Identified the face as {face_id}")
                        # later will be need to add iou to increase the accuracy
                        face_obj.x, face_obj.y, face_obj.w, face_obj.h = [int(v) for v in bbox]
                        is_already_tracked = True
                        detected_faces.append(face_id)
                        break

                #            check the updation of person object when parametes of faces changed only in identified faces array

                if is_already_tracked:
                    continue

                #     Problem of the current code is after iou checkings programme jump straight to deepface without using the trackers

                # Extract face image from person crop
                face_img = person_crop[fy:fy + fh, fx:fx + fw]
                cv2.imwrite(temp_face_path, face_img)

                # Recognize face
                face_id, confidence = recognize_face(temp_face_path)

                print("Face id based on deepface: ", face_id)

                yolo_detect_face = [global_fx, global_fy, fw, fh, face_id]

                # Create face tracker
                if fw * fh > 10000:
                    tracker = cv2.TrackerCSRT_create()
                else:
                    tracker = cv2.TrackerKCF_create()

                tracker.init(frame, (global_fx, global_fy, fw, fh))

                # Handle face recognition result
                if face_id == "Unknown" or confidence > 0.3:
                    # New face
                    face_id = str(self.next_face_id)
                    self.next_face_id += 1

                    # Update face database if quality is good
                    quality_score = calculate_face_quality(face_img)
                    if quality_score > QUALITY_THRESHOLD:
                        update_user_faces(face_id, face_img, quality_score)
                else:
                    # Known face - update database
                    quality_score = calculate_face_quality(face_img)
                    if quality_score > QUALITY_THRESHOLD:
                        update_user_faces(face_id, face_img, quality_score)

                # Create Face object
                new_face = Face(face_id, global_fx, global_fy, fw, fh, face_id, confidence, tracker, person_id)
                self.identified_faces[face_id] = new_face
                detected_faces.append(face_id)
                print("deepface new face added. face id", face_id, " person id: ", person_id)
                break

        print("esxi2: ", detected_faces)
        return detected_faces

    def processing_thread_function(self):
        """Enhanced thread function to process frames with person and face detection"""
        print("[THREAD] Processing thread started")
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
                tracks = self.person_tracker.update_tracks(person_detections, frame=frame)

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
                    if track_id in self.tracked_persons:
                        person_obj = self.tracked_persons[track_id]
                        person_obj.update_position(px, py, pw, ph,
                                                   track.confidence if hasattr(track, 'confidence') else 0.8)
                    else:
                        person_obj = Person(track_id, px, py, pw, ph,
                                            track.confidence if hasattr(track, 'confidence') else 0.8)
                        self.tracked_persons[track_id] = person_obj

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
                    person_obj.faces = {fid: self.identified_faces[fid] for fid in face_ids if
                                        fid in self.identified_faces}

                # 5. Clean up old persons and faces
                with self.lock:
                    # Remove persons not seen in current frame
                    persons_to_remove = []
                    for person_id, person_obj in self.tracked_persons.items():
                        if person_id not in current_tracked_persons:
                            if time.time() - person_obj.last_seen > 2.0:  # Remove if not seen for 2 seconds
                                persons_to_remove.append(person_id)

                    for person_id in persons_to_remove:
                        # Remove associated faces
                        faces_to_remove = [fid for fid, face in self.identified_faces.items() if
                                           face.person_id == person_id]
                        for face_id in faces_to_remove:
                            del self.identified_faces[face_id]
                        del self.tracked_persons[person_id]

            except queue.Empty:
                time.sleep(0.1)
                continue
            except Exception as e:
                print(f"Error in processing thread: {e}")
                traceback.print_exc()
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

    def get_next_available_face_id(self):
        """Get next available face ID by scanning database"""
        highest_id = -1
        try:
            existing_dirs = [d for d in os.listdir(self.db_path) if os.path.isdir(os.path.join(self.db_path, d))]

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
            print(f"Database path not found: {self.db_path}")
            return 0

        return highest_id + 1

    def display_thread_function(self):
        global yolo_detect_face
        """Enhanced thread function to display the video with person tracking and face recognition results."""
        print("[THREAD] Display thread started")
        last_display_time = time.time()

        while not self.stop_event.is_set():
            # try:
            current_time = time.time()
            time_since_last = current_time - last_display_time

            if time_since_last < 0.033:
                time.sleep(0.033 - time_since_last)

            frame = None
            if not self.frame_queue.empty():
                try:
                    frame = self.frame_queue.queue[-1].copy()
                except:
                    pass

            if frame is None:
                with self.lock:
                    if self.last_frame_buffer["frame"] is not None:
                        frame = self.last_frame_buffer["frame"].copy()

            if frame is None:
                time.sleep(0.05)
                continue

            last_display_time = time.time()

            # Get current status
            with self.lock:
                enrollment_in_progress = self.enrollment_status["in_progress"]
                enrollment_user = self.enrollment_status["user_folder"]
                enrollment_count = self.enrollment_status["count"]

            # Draw person tracking results
            for person_id, person_obj in self.tracked_persons.items():
                person_id = int(person_id)
                px, py, pw, ph = person_obj.x, person_obj.y, person_obj.w, person_obj.h
                # print(f"Person id: {person_id}, person id type: {type(person_id)} person object: {person_obj}")
                # Color coding for persons
                person_color = ((person_id * 50) % 255, (person_id * 100) % 255, (person_id * 150) % 255)

                # Draw person bounding box
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), person_color, 3)

                # Get primary face name
                primary_face_name = person_obj.get_primary_face_name()
                if primary_face_name == "Unknown":
                    print("3211 Found Unknown face in display thread. details below:")
                    person_obj.display()
                # else:
                #     print("3210 Found face in display thread. details below:")
                #     person_obj.display()

                # Display person info
                cv2.putText(frame, f"Persona {person_id}: {primary_face_name}",
                            (px, py - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, person_color, 2)

                # Draw faces within person
                for face_id, face_obj in person_obj.faces.items():
                    fx, fy, fw, fh = face_obj.x, face_obj.y, face_obj.w, face_obj.h
                    face_confidence = face_obj.confidence
                    face_name = face_obj.name
                    if face_name == "Unknown":
                        print("3211 Found Unknown face in display thread. details below:")
                        person_obj.display()

                    # Face color (lighter version of person color)
                    face_color = (min(255, person_color[0] + 50),
                                  min(255, person_color[1] + 50),
                                  min(255, person_color[2] + 50))

                    # Draw face rectangle
                    cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), face_color, 2)

                    # Display face info
                    cv2.putText(frame, f"{face_name}",
                                (fx, fy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, face_color, 1)
                    cv2.putText(frame, f"Conf: {face_confidence:.2f}",
                                (fx, fy + fh + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, face_color, 1)
            
            if self.output_callback:
                self.output_callback(self.camera_name, frame)

            # Display system status
            status_text = "Person Tracking + Face Recognition"
            if enrollment_in_progress:
                status_text = f"Enrolling: {enrollment_user}: {enrollment_count}/3"

            cv2.putText(frame, f"Persons: {len(self.tracked_persons)} | Faces: {len(self.identified_faces)}",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # Show quality metrics
            cv2.putText(frame, "System Status:", (10, frame.shape[0] - 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"Queue: {self.frame_queue.qsize()}/{self.FRAME_QUEUE_SIZE}",
                        (10, frame.shape[0] - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"YOLO + DeepSORT + Face Recognition",
                        (10, frame.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"Press 'q' to quit", (10, frame.shape[0] - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # Show the frame
            cv2.imshow("Enhanced Person Tracking + Face Recognition System", frame)

            # Exit on 'q' press
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.stop_event.set()
                break

        # except Exception as e:
        #     print(f"Error in display thread: {e}")
        #     time.sleep(0.1)

        cv2.destroyAllWindows()
        print("[THREAD] Display thread stopped")


