import os
import cv2
import tkinter as tk
import math
import threading
import time
import queue
import numpy as np

# --- IMPORTS ---
from DataModel.face_detection import * 
from DataModel.Reid_model import ReIDModel
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import torch
from torchvision.transforms import transforms

class Person:
    def __init__(self, person_id, x, y, w, h, confidence):
        self.person_id = person_id
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.confidence = confidence
        self.faces = {}  
        self.last_seen = time.time()
        self.feature_vector = None

    def update_position(self, x, y, w, h, confidence):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.confidence = confidence
        self.last_seen = time.time()

    def get_primary_face_name(self):
        if not self.faces:
            return "Unknown"
        # Prioritize faces that are NOT scanning and NOT unknown if possible
        valid_faces = [f for f in self.faces.values() if f.name != "Scanning..." and f.name != "Unknown"]
        if valid_faces:
            return valid_faces[0].name
            
        # Fallback
        best_face = min(self.faces.values(), key=lambda f: f.confidence)
        return best_face.name


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

class DetectionSystem:
    def __init__(self, camera_name, db_path="Faces_db", camera_buffer=None, output_callback=None):
        print("[INFO] Initializing Detection System...")

        self.camera_name = camera_name
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        
        self.camera_buffer = camera_buffer
        self.output_callback = output_callback 

        # Configuration
        self.CONFIDENCE_THRESHOLD = 0.3
        self.MIN_FACE_SIZE = (80, 80)
        
        
        self.FRAME_QUEUE_SIZE = 20
        self.RECOGNITION_QUEUE_SIZE = 20 # Buffer for async recognition
        self.DISTANCE_THRESHOLD = 50
        
        self.frame_count = 0

        # Shared resources
        self.frame_queue = queue.Queue(maxsize=self.FRAME_QUEUE_SIZE)
        self.recognition_queue = queue.Queue(maxsize=self.RECOGNITION_QUEUE_SIZE) # RESTORED QUEUE
        
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        
        self.last_frame_buffer = {"frame": None, "timestamp": 0.0}

        # Data
        self.tracked_persons = {}
        self.identified_faces = {}
        self.next_face_id = 0 

        # YOLO Configs
        self.PERSON_CONFIDENCE_THRESHOLD = 0.5
        self.MIN_PERSON_SIZE = (50, 100)
        self.PERSON_TRACKING_MAX_AGE = 30
        self.PERSON_TRACKING_N_INIT = 3

        self.yolo_model = None
        self.yolo_face_model = None
        self.reid_model = None
        self.person_tracker = None

        self.initialize_models()
        
        # Get starting ID
        self.next_face_id = self.get_next_available_face_id()

        # Threads
        self.cam_thread = None
        self.proc_thread = None
        self.disp_thread = None
        self.recog_thread = None # RESTORED WORKER
        self.watchdog_thread = None

        print("[INFO] System initialized successfully.")

    def initialize_models(self):
        self.yolo_model = YOLO("yolov8n.pt")
        self.yolo_face_model = YOLO("yolov11n-face.pt")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.reid_model = ReIDModel().to(device)
        self.reid_model.eval()
        self.person_tracker = DeepSort(max_age=self.PERSON_TRACKING_MAX_AGE, n_init=self.PERSON_TRACKING_N_INIT)
        print("[INFO] Models loaded.")

    def get_next_available_face_id(self):
        """Scans Faces_db to find the next 'User_X' ID"""
        highest_id = 0
        if not os.path.exists(self.db_path): return 1
        try:
            for item in os.listdir(self.db_path):
                if item.startswith("User_") and os.path.isdir(os.path.join(self.db_path, item)):
                    try:
                        pid = int(item.split('_')[1])
                        if pid > highest_id: highest_id = pid
                    except: continue
        except: return 1
        return highest_id + 1

    def start(self):
        print("[INFO] Starting all threads...")
        self.stop_event.clear()

        self.cam_thread = threading.Thread(target=self.camera_thread_function, daemon=True)
        self.cam_thread.start()

        self.proc_thread = threading.Thread(target=self.processing_thread_function, daemon=True)
        self.proc_thread.start()

        # RESTORED: Recognition Worker Thread
        self.recog_thread = threading.Thread(target=self.recognition_worker_function, daemon=True)
        self.recog_thread.start()

        self.disp_thread = threading.Thread(target=self.display_thread_function, daemon=True)
        self.disp_thread.start()

        self.watchdog_thread = threading.Thread(target=self.watchdog_thread_function, daemon=True)
        self.watchdog_thread.start()

    def stop(self):
        print("[INFO] Stopping all threads...")
        self.stop_event.set()
        if self.cam_thread: self.cam_thread.join(timeout=1.0)
        if self.proc_thread: self.proc_thread.join(timeout=1.0)
        if self.recog_thread: self.recog_thread.join(timeout=1.0)
        if self.disp_thread: self.disp_thread.join(timeout=1.0)
        cv2.destroyAllWindows()
        print("[INFO] System shut down.")

    # --- 1. RECOGNITION WORKER (The Heavy Lifter) ---
    def recognition_worker_function(self):
        """
        Background thread. Pulls faces from queue, runs DeepFace, 
        saves 'Unknowns' to disk, and updates the Face objects.
        """
        print("[THREAD] Recognition Worker started")
        
        while not self.stop_event.is_set():
            try:
                # Get task: (temp_face_id, face_image)
                task = self.recognition_queue.get(timeout=1.0)
                face_id_key, face_img = task
                
                name, confidence = recognize_face(face_img=face_img)
                # face_id, confidence = "Unknown", 1.0  # Placeholder for actual recognition
                
                # 2. Update Logic
                with self.lock:
                    if face_id_key in self.identified_faces:
                        face_obj = self.identified_faces[face_id_key]
                    else:
                        print(f"[RECOG WORKER] Face ID {face_id_key} not found in identified_faces.")
                        print(f"[RECOG WORKER] Identifaed Faces Keys: {list(self.identified_faces.keys())}")
                        
                # --- LOGIC: Handle New User ---
                
                if name == "Unknown":
                    try:
                        # Generate next ID safely
                        new_id_num = self.get_next_available_face_id()
                        new_folder_name = f"User_{new_id_num}"
                        print(f"[STORAGE] Assigning New User ID: {new_folder_name}")
                        
                        update_user_faces(new_folder_name,face_img=face_img)
                        
                        # Update live object name
                        face_obj.name = new_folder_name
                        
                        # Increment internal counter to reduce scanning conflict
                        # (Though get_next_available is safest)
                    except Exception as e:
                        print(f"[ERROR] Failed to save new user: {e}")
                        face_obj.name = "Unknown"
                else:
                    # Known match
                    face_obj.name = name
                    face_obj.confidence = confidence
                face_obj.is_recognizing = False # Unlock flag
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[RECOG WORKER ERROR] {e}")

    # --- 2. CAMERA THREAD ---
    def camera_thread_function(self):
        print("[THREAD] Camera thread started")
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    if self.camera_buffer and not self.camera_buffer.empty():
                        frame = self.camera_buffer.get()
                    else:
                        time.sleep(0.01); continue

                self.last_frame_buffer["frame"] = frame.copy()
                self.last_frame_buffer["timestamp"] = time.time()

                if self.frame_queue.full():
                    try: self.frame_queue.get_nowait()
                    except: pass
                self.frame_queue.put(frame, block=False)
                time.sleep(0.03)
            except: time.sleep(0.1)

    
    def process_faces_in_person(self, frame, person_bbox, person_id):
        px, py, pw, ph = person_bbox
        px = max(0, px)
        py = max(0, py)
        
        detected_face_ids = []
        
         # --- PHASE 1: UPDATE TRACKERS (Fast) ---
        person_faces = [f for f in self.identified_faces.values() if f.person_id == person_id]
        active_tracked_faces = []
        
        for face_obj in person_faces:
            success, bbox = face_obj.tracker.update(frame)
            if success:
                x, y, w, h = [int(v) for v in bbox]
                face_obj.position_update(x, y, w, h)
                detected_face_ids.append(face_obj.face_id)
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
                        gx = px + lx1
                        gy = py + ly1
                        gw = lx2 - lx1
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
                                    print(f"[QUEUE] Created Face {face_id} and added to identified_faces")

                                # Try to push to queue
                                self.recognition_queue.put((face_id, face_img), block=False)

                                # SUCCESS: Now we create the object
                                self.next_face_id += 1
                                print(f"[QUEUE] Pushed Face {face_id} for recognition")

                                

                                detected_face_ids.append(face_id)

                        except queue.Full:
                            #
                            # If queue is full, we DO NOT create the face object.
                            # We just ignore it this frame. It will be detected again in the next frame.
                            pass

        return detected_face_ids
        

    def processing_thread_function(self):
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
                    face_ids = self.process_faces_in_person(frame, (l, t, w, h), tid)

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

    # --- 4. DISPLAY THREAD ---
    def display_thread_function(self):
        print("[THREAD] Display thread started")
        
        while not self.stop_event.is_set():
            # Get Frame
            frame = None
            with self.lock:
                if self.last_frame_buffer["frame"] is not None:
                    frame = self.last_frame_buffer["frame"].copy()
            
            if frame is None: time.sleep(0.05); continue

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

                # # Draw Faces
                # try:
                #     for face_obj in person_obj.faces.values():
                #         fx, fy, fw, fh = face_obj.x, face_obj.y, face_obj.w, face_obj.h

                #         if face_obj.is_recognizing:
                #             f_color = (0, 255, 255)  # Yellow
                #             label = "Scanning..."
                #         else:
                #             f_color = (0, 0, 255)  # Red
                #             label = f"{face_obj.name} ({face_obj.confidence:.2f})"

                #         cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), f_color, 2)
                #         cv2.putText(frame, label, (fx, fy - 10),
                #                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, f_color, 1)
                # except RuntimeError:
                #     pass
            
            # Send to PyQt
            if self.output_callback:
                self.output_callback(self.camera_name, frame)
            
            time.sleep(0.03)

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