from DataModel.EmbeddingCache import EmbeddingCache
import os
import cv2
import tkinter as tk
import math
import threading
import time
import queue
import psutil
import numpy as np

# --- IMPORTS ---
from DataModel.face_detection import update_user_faces, calculate_face_quality
from DataModel.Reid_model import ReIDModel
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import torch
from torchvision.transforms import transforms
from DataModel.EmbeddingCache import get_embedding_cache
from DataModel.GlobalPersonTracker import GlobalPersonTracker
from DataModel.SettingsManager import get_settings

def Ai_System_thread(camera_name, db_path="Faces_db", camera_buffer=None, output_callback=None, frame_skip_interval=3, gui_fps_limit=15, global_tracker=None, Main_Detection_system=None):
    detection_system = DetectionSystem(
        camera_name=camera_name,
        db_path=db_path,
        camera_buffer=camera_buffer,
        output_callback=output_callback,
        frame_skip_interval=frame_skip_interval,
        gui_fps_limit=gui_fps_limit,
        global_tracker=global_tracker
    )
    Main_Detection_system[camera_name] = detection_system
    detection_system.start()
    return detection_system


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
        self.global_id = None  # Global ID from GlobalPersonTracker

    def update_position(self, x, y, w, h, confidence):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.confidence = confidence
        self.last_seen = time.time()

    def get_primary_face_name(self, global_tracker=None):
        """
        Get the primary face name for this person.
        If global_tracker is provided, uses consolidated name across cameras.
        """
        # First, check if we have a global ID and can get consolidated name
        if global_tracker and self.global_id:
            consolidated = global_tracker.get_consolidated_name(self.global_id)
            if consolidated and consolidated not in ("Unknown", "Scanning..."):
                # DEBUG: Log when consolidated name is used
                return consolidated
            else:
                print(f"[DISPLAY] Person L:{self.person_id} G:{self.global_id} consolidated='{consolidated}', falling back to local")
        else:
            print(f"[DISPLAY] Person L:{self.person_id} no global_tracker={global_tracker is not None} global_id={self.global_id}")
        
        if not self.faces:
            return "Unknown"
        # Prioritize faces that are NOT scanning and NOT unknown if possible
        valid_faces = [f for f in self.faces.values() if f.name != "Scanning..." and f.name != "Unknown"]
        if valid_faces:
            # Choose the face with highest confidence among valid faces
            best_valid = max(valid_faces, key=lambda f: f.confidence)
            return best_valid.name
            
        # Fallback: pick the most confident face overall
        best_face = max(self.faces.values(), key=lambda f: f.confidence)
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
        self.tracker_miscount: int = 0  # Count of consecutive tracker failures
        
        # Identity verification fields
        self.identity_history = []  # List of (user_name, confidence) tuples
        self.locked_identity = None  # Locked after N consistent matches
        self.avg_confidence = 0.0  # Average confidence for locked identity
        self.unknown_count = 0  # Count of consecutive "Unknown" results (for new user creation threshold)

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
    
    def update_identity(self, new_name: str, new_confidence: float, 
                        confirm_frames: int = 3, 
                        confidence_threshold: float = 0.6,
                        change_margin: float = 0.15) -> str:
        """
        Update face identity with verification logic.
        
        Returns the final identity name (may reject the new_name if locked).
        """
        # Reject low confidence matches
        if new_confidence > confidence_threshold:  # Note: lower distance = better match
            return self.locked_identity if self.locked_identity else "Unknown"
        
        # Add to history
        self.identity_history.append((new_name, new_confidence))
        
        # Keep only last N entries
        if len(self.identity_history) > confirm_frames * 2:
            self.identity_history = self.identity_history[-confirm_frames * 2:]
        
        # If already locked
        if self.locked_identity:
            # Check if new identity is significantly better
            if new_name != self.locked_identity:
                # Require margin improvement to change identity
                if new_confidence < (self.avg_confidence - change_margin):
                    # Strong evidence for new identity - unlock and re-evaluate
                    print(f"[IDENTITY] Strong evidence: {new_name} ({new_confidence:.2f}) vs locked {self.locked_identity} ({self.avg_confidence:.2f})")
                    self.locked_identity = None
                    self.identity_history = [(new_name, new_confidence)]
                else:
                    # Keep locked identity
                    return self.locked_identity
            else:
                # Same identity, update confidence
                self.avg_confidence = (self.avg_confidence + new_confidence) / 2
                return self.locked_identity
        
        # Check for consistent matches to lock identity
        recent = self.identity_history[-confirm_frames:]
        if len(recent) >= confirm_frames:
            names = [r[0] for r in recent]
            if all(n == names[0] and n not in ("Unknown", "Scanning...") for n in names):
                # All recent matches are consistent - lock identity
                self.locked_identity = names[0]
                self.avg_confidence = sum(r[1] for r in recent) / len(recent)
                print(f"[IDENTITY] Locked {self.locked_identity} (avg_conf={self.avg_confidence:.2f})")
                return self.locked_identity
        
        # Not yet locked, return current match
        return new_name

class DetectionSystem:
    def __init__(self, camera_name, db_path="Faces_db", camera_buffer=None, output_callback=None, frame_skip_interval=3, gui_fps_limit=15, global_tracker:GlobalPersonTracker=None):
        print("[INFO] Initializing Detection System...")

        self.camera_name = camera_name
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        
        # Global person tracking
        self.global_tracker = global_tracker
        
        
        self.settings = get_settings()
        
        self.EmbeddingCache:EmbeddingCache = None  # Placeholder for EmbeddingCache instance
        
        self.camera_buffer = camera_buffer
        self.output_callback = output_callback 
        
        self.process = psutil.Process(os.getpid())
        # Performance Parameters (user-configurable)
        self.frame_skip_interval = frame_skip_interval  # Skip N frames between detections (default 3)
        self.gui_fps_limit = gui_fps_limit  # GUI refresh rate limit in FPS (default 15)
        self.gui_frame_delay = 1.0 / gui_fps_limit if gui_fps_limit > 0 else 0.067  # Calculate delay from FPS

        # Configuration
        self.CONFIDENCE_THRESHOLD = 0.3
        self.MIN_FACE_SIZE = (80, 80)
        
        
        self.FRAME_QUEUE_SIZE = 20
        self.RECOGNITION_QUEUE_SIZE = 20 # Buffer for async recognition
        self.DB_UPDATE_QUEUE_SIZE = 30   # Buffer for async database updates
        self.DISTANCE_THRESHOLD = 50
        
        self.frame_count = 0

        # Shared resources
        self.frame_queue = queue.Queue(maxsize=self.FRAME_QUEUE_SIZE)
        self.recognition_queue = queue.Queue(maxsize=self.RECOGNITION_QUEUE_SIZE) # RESTORED QUEUE
        self.db_update_queue = queue.Queue(maxsize=self.DB_UPDATE_QUEUE_SIZE)  # Async DB updates
        
        # Quality cache: user_name -> min_quality_on_disk (avoids disk reads)
        self.quality_cache = {}
        self.quality_cache_lock = threading.Lock()
        
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        
        self.last_frame_buffer = {"frame": None, "timestamp": 0.0}

        # Data
        self.tracked_persons:dict[int, Person] = {}
        self.identified_faces:dict[int, Face] = {}
        self.next_face_id = 0 

        # YOLO Configs
        self.PERSON_CONFIDENCE_THRESHOLD = 0.5
        self.MIN_PERSON_SIZE = (50, 100)
        self.PERSON_TRACKING_MAX_AGE = 30  # Increased from 30 - keep tracks alive longer
        self.PERSON_TRACKING_N_INIT = 3     # Decreased from 3 - confirm tracks immediately

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
        self.db_update_thread = None  # Database update worker
        self.watchdog_thread = None

        print("[INFO] System initialized successfully.")

    def initialize_models(self):
        
        self.yolo_model = YOLO("yolov8n.pt")
        self.yolo_face_model = YOLO("yolov11n-face.pt")
        
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Initialize EmbeddingCache (singleton - shared across all DetectionSystem instances)
        self.EmbeddingCache = get_embedding_cache(db_path=self.db_path)
        self.reid_model = ReIDModel().to(device)
        self.reid_model.eval()
        
        self.person_tracker = DeepSort(max_age=self.PERSON_TRACKING_MAX_AGE, n_init=self.PERSON_TRACKING_N_INIT)
        print("[INFO] Models loaded.")
        time.sleep(3.0)

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

    def _create_tracker(self):
        """Create a tracker using multiple fallbacks. Returns a tracker instance or None.
        Tries CSRT first (preferred), then falls back to KCF, MOSSE, or the generic factory.
        """
        # Preferred: CSRT
        try:
            # Newer OpenCV: cv2.TrackerCSRT_create()
            return cv2.TrackerCSRT_create()
        except Exception:
            pass
        try:
            # Another variant: cv2.TrackerCSRT.create()
            return cv2.TrackerCSRT.create()
        except Exception:
            pass
        try:
            # Some builds expose it under legacy
            return cv2.legacy.TrackerCSRT_create()
        except Exception:
            pass

        # Fallbacks: try KCF, MOSSE, or generic factory
        try:
            return cv2.TrackerKCF_create()
        except Exception:
            pass
        try:
            return cv2.TrackerMOSSE_create()
        except Exception:
            pass
        try:
            # Older OpenCV had a generic factory
            return cv2.Tracker_create('CSRT')
        except Exception:
            pass

        print('[TRACKER] No suitable tracker factory found. Please install opencv-contrib-python or use a build with trackers enabled.')
        return None

    def start(self):
        print("[INFO] Starting all threads...")
        try:    
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

            # Database Update Worker Thread
            self.db_update_thread = threading.Thread(target=self.db_update_worker, daemon=True)
            self.db_update_thread.start()

            self.watchdog_thread = threading.Thread(target=self.watchdog_thread_function, daemon=True)
            self.watchdog_thread.start()
        except Exception as e:
            print(f"[ERROR] Failed to start threads: {e}")

    def stop(self):
        print("[INFO] Stopping Detection System...")
        self.stop_event.set()
        
        # Wait for threads to finish
        for t in [self.proc_thread, self.disp_thread, self.recog_thread, self.db_update_thread, self.watchdog_thread, self.cam_thread]:
            if t and t.is_alive():
                t.join(timeout=2.0)
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
                
                # DEBUG: Save face image to temp file for inspection
                try:
                    cv2.imwrite("debug_face_temp.jpg", face_img)
                    print(f"[DEBUG] Saved face {face_id_key} to debug_face_temp.jpg (shape={face_img.shape})")
                except Exception as e:
                    print(f"[DEBUG] Failed to save temp face: {e}")
                
                name, confidence = self.EmbeddingCache.find_match(face_img)
                print(f"[RECOG] Face {face_id_key} matched: name='{name}', conf={confidence:.3f}")

                # 2. Update Logic
                with self.lock:
                    face_obj = self.identified_faces.get(face_id_key)
                    if face_obj is None:
                        print(f"[RECOG WORKER] Face ID {face_id_key} not found in identified_faces.")
                        print(f"[RECOG WORKER] Identified Faces Keys: {list(self.identified_faces.keys())}")
                # If the face was removed while queued for recognition, skip it
                if face_obj is None:
                    continue

                # --- LOGIC: Handle New User ---
                if name == "Unknown":
                    # Increment unknown counter for this face
                    with self.lock:
                        face_obj.unknown_count = getattr(face_obj, 'unknown_count', 0) + 1
                        unknown_count = face_obj.unknown_count
                    
                    # Require 3 consecutive Unknown results before creating new user
                    unknown_threshold = 3  # TODO: Add to settings
                    
                    if unknown_count < unknown_threshold:
                        print(f"[RECOG] Face {face_id_key} Unknown ({unknown_count}/{unknown_threshold}) - waiting for more frames")
                        with self.lock:
                            face_obj.name = "Scanning..."
                            face_obj.is_recognizing = False  # CRITICAL: Reset so face can be re-queued!
                        continue  # Don't create new user yet
                    
                    # Threshold reached - create new user
                    print(f"[RECOG] Face {face_id_key} confirmed Unknown after {unknown_count} frames - creating new user")
                    
                    try:
                        # Calculate face quality before saving
                        quality_score = calculate_face_quality(face_img)
                        
                        # Generate next ID safely
                        new_id_num = self.get_next_available_face_id()
                        new_folder_name = f"User_{new_id_num}"
                        print(f"[STORAGE] Assigning New User ID: {new_folder_name} (quality: {quality_score:.1f})")

                        # Save with quality check (may skip if quality too low)
                        saved = update_user_faces(new_folder_name, face_img=face_img, quality_score=quality_score)

                        if saved:
                            self.EmbeddingCache.add_new_user(new_folder_name, face_img)

                            # Calculate initial confidence based on image quality
                            # Higher quality = lower confidence value = higher priority
                            # Quality typically ranges 200-400, normalize to 0.1-0.5
                            # quality 400 -> conf 0.1 (best), quality 200 -> conf 0.5 (worst)
                            initial_confidence = max(0.1, min(0.5, 0.5 - (quality_score - 200) / 400))
                            print(f"[NEW USER] Quality {quality_score:.1f} -> initial_confidence {initial_confidence:.3f}")

                            # Update live object name under lock
                            with self.lock:
                                face_obj.name = new_folder_name
                                face_obj.locked_identity = new_folder_name  # Immediately lock new user
                                face_obj.avg_confidence = initial_confidence
                                face_obj.unknown_count = 0  # Reset counter
                                
                                # Report new user to global tracker for consolidation
                                person_id = face_obj.person_id
                                if person_id and person_id in self.tracked_persons:
                                    person = self.tracked_persons[person_id]
                                    if person.global_id and self.global_tracker:
                                        consolidated = self.global_tracker.update_face_identity(
                                            person.global_id,
                                            new_folder_name,
                                            initial_confidence  # Quality-based confidence
                                        )
                                        print(f"[NEW USER] Reported {new_folder_name} (conf={initial_confidence:.3f}) to global tracker -> {consolidated}")
                        else:
                            print(f"[STORAGE] Skipped saving - quality below threshold")
                            with self.lock:
                                face_obj.name = "Scanning..."
                                face_obj.is_recognizing = False  # Reset so face can be re-queued
                                # Don't reset unknown_count to allow retry

                    except Exception as e:
                        print(f"[ERROR] Failed to save new user: {e}")
                        with self.lock:
                            face_obj.name = "Unknown"
                            face_obj.is_recognizing = False  # Reset so face can be re-queued
                else:
                    # Known match: use identity verification
                    # Reset unknown counter since we found a match
                    with self.lock:
                        face_obj.unknown_count = 0
                    
                    # Get settings (use defaults if not available)
                    confirm_frames = 3  # TODO: get from settings
                    confidence_threshold = 0.6
                    change_margin = 0.15
                    
                    with self.lock:
                        # Use update_identity to verify and possibly lock identity
                        verified_name = face_obj.update_identity(
                            name, confidence,
                            confirm_frames=confirm_frames,
                            confidence_threshold=confidence_threshold,
                            change_margin=change_margin
                        )
                        face_obj.name = verified_name
                        face_obj.confidence = confidence
                        
                        # DEBUG: Log the state after update_identity
                        print(f"[KNOWN MATCH] Face {face_id_key}: verified={verified_name}, locked={face_obj.locked_identity}, person_id={face_obj.person_id}")
                        
                        # If identity is locked, report to global tracker for consolidation
                        if face_obj.locked_identity and face_obj.locked_identity not in ("Unknown", "Scanning..."):
                            # Find the global_id via the person object
                            person_id = face_obj.person_id
                            if person_id and person_id in self.tracked_persons:
                                person = self.tracked_persons[person_id]
                                if person.global_id and self.global_tracker:
                                    # Update global tracker and get consolidated name
                                    print(f"[CONSOLIDATE CALL] global_id={person.global_id}, user={face_obj.locked_identity}, conf={face_obj.avg_confidence:.3f}")
                                    consolidated_name = self.global_tracker.update_face_identity(
                                        person.global_id, 
                                        face_obj.locked_identity, 
                                        face_obj.avg_confidence
                                    )
                                    # Use consolidated name
                                    face_obj.name = consolidated_name
                                    face_obj.locked_identity = consolidated_name
                                else:
                                    print(f"[CONSOLIDATE SKIP] person.global_id={person.global_id}, global_tracker={self.global_tracker is not None}")
                            else:
                                print(f"[CONSOLIDATE SKIP] person_id={person_id} not in tracked_persons")

                    # Only push to DB update queue if identity is LOCKED (confirmed)
                    if face_obj.locked_identity and face_obj.locked_identity not in ("Unknown", "Scanning..."):
                        try:
                            quality_score = calculate_face_quality(face_img)
                            self._push_db_update(face_obj.locked_identity, face_img, quality_score)
                        except Exception as e:
                            print(f"[QUALITY UPDATE] Error: {e}")

                # Unlock flag under lock
                with self.lock:
                    face_obj.is_recognizing = False
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[RECOG WORKER ERROR] {e}")

    # --- 1.5 DATABASE UPDATE WORKER ---
    def db_update_worker(self):
        """
        Background thread that processes face quality updates.
        Saves better quality images and refreshes embeddings.
        """
        print("[THREAD] DB Update Worker started")
        
        while not self.stop_event.is_set():
            try:
                # Get task: (user_name, face_img, quality_score)
                task = self.db_update_queue.get(timeout=1.0)
                user_name, face_img, quality_score = task
                
                # Save image (update_user_faces handles the disk comparison)
                saved = update_user_faces(user_name, face_img=face_img, quality_score=quality_score)
                
                if saved:
                    # Update our cache with new minimum
                    new_min = self._get_min_quality_from_disk(user_name)
                    self._update_quality_cache(user_name, new_min)
                    
                    # Refresh embedding with best quality image
                    self.EmbeddingCache.refresh_user(user_name)
                    print(f"[DB WORKER] Updated {user_name} and refreshed embedding")
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[DB WORKER ERROR] {e}")
        
        print("[THREAD] DB Update Worker stopped")
    
    # --- Quality Cache Helpers ---
    def _get_cached_min_quality(self, user_name: str) -> float:
        """
        Get cached minimum quality for a user.
        Returns 0 if not cached (cache miss - will need disk read).
        """
        with self.quality_cache_lock:
            return self.quality_cache.get(user_name, 0)
    
    def _update_quality_cache(self, user_name: str, min_quality: float):
        """Update the cached minimum quality for a user."""
        with self.quality_cache_lock:
            self.quality_cache[user_name] = min_quality
            print(f"[CACHE] Updated {user_name} min_quality={min_quality:.1f}")
    
    def _get_min_quality_from_disk(self, user_name: str) -> float:
        """
        Read minimum quality from disk for a user.
        Called on cache miss or after save to refresh cache.
        """
        user_path = os.path.join(self.db_path, str(user_name))
        if not os.path.isdir(user_path):
            return 0
        
        min_quality = float('inf')
        for filename in os.listdir(user_path):
            if not filename.endswith(('.jpg', '.jpeg', '.png')):
                continue
            
            # Extract quality from filename (format: face_TIMESTAMP_qSCORE.jpg)
            if '_q' in filename:
                try:
                    q_part = filename.split('_q')[1].split('.')[0]
                    file_quality = float(q_part)
                    min_quality = min(min_quality, file_quality)
                except (IndexError, ValueError):
                    min_quality = 0  # Old format images have quality 0
            else:
                min_quality = 0  # Old format without quality score
        
        return min_quality if min_quality != float('inf') else 0
    
    def _push_db_update(self, user_name: str, face_img, quality_score: float, max_faces: int = 5):
        """
        Push a face to db_update_queue.
        - If user has < max_faces images: always push (filling phase)
        - If user has >= max_faces: only push if quality is better (replacement phase)
        Non-blocking: skips if queue is full.
        """
        # Get image count and min quality from disk (one-time read per user)
        user_path = os.path.join(self.db_path, str(user_name))
        if os.path.isdir(user_path):
            images = [f for f in os.listdir(user_path) if f.endswith(('.jpg', '.jpeg', '.png'))]
            num_images = len(images)
        else:
            num_images = 0
        
        # PHASE 1: Filling - always push if under capacity
        if num_images < max_faces:
            try:
                self.db_update_queue.put_nowait((user_name, face_img.copy(), quality_score))
                print(f"[DB QUEUE] Pushed {user_name} for filling ({num_images + 1}/{max_faces})")
            except queue.Full:
                pass
            return
        
        # PHASE 2: Replacement - only push if quality is better than cached minimum
        cached_min = self._get_cached_min_quality(user_name)
        
        # If not in cache, do a one-time disk read to populate cache
        if cached_min == 0:
            cached_min = self._get_min_quality_from_disk(user_name)
            self._update_quality_cache(user_name, cached_min)
        
        # Only push if quality is better than cached minimum
        if quality_score > cached_min:
            try:
                self.db_update_queue.put_nowait((user_name, face_img.copy(), quality_score))
                print(f"[DB QUEUE] Pushed {user_name} (q={quality_score:.1f} > min={cached_min:.1f})")
            except queue.Full:
                pass  # Queue full, skip this update (non-blocking)
        # else: silently skip - not better than existing

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
            except Exception as e:
                print(f"[CAM THREAD ERROR] {e}")
                time.sleep(0.1)

    
    def process_faces_in_person(self, frame, person_bbox, person_id):
        px, py, pw, ph = person_bbox
        px = max(0, px)
        py = max(0, py)
        
        detected_face_ids = []
        
         # --- PHASE 1: UPDATE TRACKERS (Fast) ---
        person_faces = [f for f in self.identified_faces.values() if f.person_id == person_id]
        active_tracked_faces = []
        
        for face_obj in person_faces:
            try:
                success, bbox = face_obj.tracker.update(frame)
            except Exception as e:
                # Tracker failed; skip this face for now
                print(f"[TRACKER ERROR] face_id {face_obj.face_id}: {e}")
                continue
            if success:
                x, y, w, h = [int(v) for v in bbox]
                face_obj.position_update(x, y, w, h)
                detected_face_ids.append(face_obj.face_id)
                # Only add to active_tracked_faces if identity is LOCKED
                # This allows unlocked faces to be re-queued for recognition
                if face_obj.locked_identity and face_obj.locked_identity not in ("Unknown", "Scanning..."):
                    active_tracked_faces.append(face_obj)
                
         # --- PHASE 2: DETECT NEW FACES ---
        # Check if we need to run detection (if no faces tracked or periodically)
        should_run_detection = (len(active_tracked_faces) == 0) or (self.frame_count % 10 == 0)

        if should_run_detection:
            person_crop = frame[py:py + ph, px:px + pw]
            if person_crop.size > 0:
                # DEBUG: Time the face detection
                import time as _time
                _face_start = _time.perf_counter()
                results = self.yolo_face_model(person_crop, verbose=False)
                _face_elapsed = (_time.perf_counter() - _face_start) * 1000
                print(f"[TIMING] yolo_face_model: {_face_elapsed:.1f}ms")

                for r in results:
                    for box in r.boxes:
                        # DEBUG: Log YOLO face detection confidence
                        yolo_conf = float(box.conf[0]) if box.conf is not None else 0.0
                        print(f"[YOLO FACE] Detected face with confidence: {yolo_conf:.3f}")
                        
                        # Coords
                        lx1, ly1, lx2, ly2 = map(int, box.xyxy[0])
                        gx = px + lx1
                        gy = py + ly1
                        gw = lx2 - lx1
                        gh = ly2 - ly1
                        
                        # --- FACE VALIDATION FILTER ---
                        # Get settings (with fallbacks)
                        min_width = self.settings.get("min_face_width", 70) if self.settings else 70
                        min_height = self.settings.get("min_face_height", 90) if self.settings else 90
                        min_conf = self.settings.get("min_face_confidence", 0.5) if self.settings else 0.5
                        
                        # Check size requirements
                        if gw < min_width or gh < min_height:
                            print(f"[FACE REJECT] Size {gw}x{gh} < {min_width}x{min_height} minimum")
                            continue
                        
                        # Check confidence requirement
                        if yolo_conf < min_conf:
                            print(f"[FACE REJECT] Confidence {yolo_conf:.3f} < {min_conf:.2f} minimum")
                            continue
                        
                        print(f"[FACE ACCEPT] Size {gw}x{gh}, conf {yolo_conf:.3f} - valid face")
                        
                        new_center = (gx + gw // 2, gy + gh // 2)

                        # --- MATCH WITH ALL EXISTING FACES (locked AND unlocked) ---
                        matched_face = None
                        for face_obj in person_faces:
                            existing_center = face_obj.get_center()
                            dist = math.dist(new_center, existing_center)
                            if dist < self.DISTANCE_THRESHOLD:
                                matched_face = face_obj
                                break

                        if matched_face:
                            # Update position
                            matched_face.position_update(gx, gy, gw, gh)
                            matched_face.tracker_miscount += 1
                            
                            # If LOCKED, just update DB queue
                            if matched_face.locked_identity and matched_face.locked_identity not in ("Unknown", "Scanning..."):
                                try:
                                    face_img = frame[gy:gy + gh, gx:gx + gw].copy()
                                    if face_img.size > 0:
                                        quality_score = calculate_face_quality(face_img)
                                        self._push_db_update(matched_face.locked_identity, face_img, quality_score)
                                except Exception as e:
                                    pass  # Non-critical, silently skip
                            else:
                                # UNLOCKED: Re-queue for recognition to accumulate history
                                if not matched_face.is_recognizing:
                                    try:
                                        face_img = frame[gy:gy + gh, gx:gx + gw].copy()
                                        if face_img.size > 0:
                                            matched_face.is_recognizing = True
                                            self.recognition_queue.put((matched_face.face_id, face_img), block=False)
                                            print(f"[QUEUE] Re-queued unlocked Face {matched_face.face_id} for recognition")
                                    except queue.Full:
                                        pass  # Queue full, try next time
                                    except Exception as e:
                                        pass
                            continue

                        # --- PHASE 4: NEW FACE FOUND ---
                        # Try to push to queue FIRST. If full, skip this face entirely for now.
                        # This prevents "Zombie" faces that stay stuck on "Scanning..."
                        try:
                            face_img = frame[gy:gy + gh, gx:gx + gw].copy()

                            if face_img.size > 0:
                                # Generate ID
                                face_id = str(self.next_face_id)
                                
                                # Initialize Tracker
                                # Create tracker using helper with robust fallbacks
                                tracker = self._create_tracker()
                                if tracker is None:
                                    print(f"[TRACKER] Could not create a tracker for face {face_id}; skipping face.")
                                    continue
                                try:
                                    tracker.init(frame, (gx, gy, gw, gh))
                                except Exception as e:
                                    print(f"[TRACKER INIT ERROR] face_id {face_id}: {e}")
                                    # If init fails, try a different tracker once
                                    alt = None
                                    try:
                                        alt = cv2.TrackerKCF_create()
                                    except Exception:
                                        pass
                                    if alt is not None:
                                        try:
                                            alt.init(frame, (gx, gy, gw, gh))
                                            tracker = alt
                                        except Exception as e2:
                                            print(f"[TRACKER INIT ERROR] alternative tracker failed: {e2}")
                                            continue
                                
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
                        break

                # If queue was empty, wait for a new frame
                if frame is None:
                    try:
                        frame = self.frame_queue.get(timeout=1.0)
                    except queue.Empty:
                        print("Frame queue timeout")
                        continue

                self.frame_count += 1

                # 1. Detect persons using YOLO (with frame skipping for efficiency)
               
                should_run_yolo_detection = True
                
                detections = []
                if should_run_yolo_detection:
                    self.frame_count=0
                    results = self.yolo_model(frame, verbose=False)
                    for r in results:
                        for box in r.boxes:
                            if int(box.cls[0]) == 0:
                                conf = float(box.conf[0])
                                if conf >= self.PERSON_CONFIDENCE_THRESHOLD:
                                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                                    detections.append(([x1, y1, x2 - x1, y2 - y1], conf, 0))
                    # Only update tracker when we have fresh detections
                    tracks = self.person_tracker.update_tracks(detections, frame=frame) #check the track of user. i think this is local id
                else:
                    # Between detection frames, still update tracker with empty detections
                    # This keeps existing tracks alive
                    tracks = self.person_tracker.update_tracks([], frame=frame) 

                # 3. Process tracked persons
                current_tracked_ids = [] #check the track of user. i think this is local id

                for track in tracks:
                    # Process only confirmed tracks
                    # With n_init=1, tracks confirm immediately after first detection
                    if not track.is_confirmed():
                        print(f"deepsort track for user in {self.camera_name} is not yet confirmed")
                        continue

                    tid = track.track_id
                    current_tracked_ids.append(tid)
                    l, t, r, b = map(int, track.to_ltrb())
                    w, h = r - l, b - t

                    # Update/Create Person already tracked person
                    if tid in self.tracked_persons:
                        person_obj = self.tracked_persons[tid] 
                        person_obj.update_position(l, t, w, h, 0.9)
                        
                        # Update global tracker if we have features but no global ID yet
                        if self.global_tracker and person_obj.feature_vector is not None and person_obj.global_id is None:
                            global_id = self.global_tracker.create_or_update(
                                camera_name=self.camera_name,
                                local_id=tid,
                                feature_vector=person_obj.feature_vector,
                                bbox=(l, t, w, h),
                                frame_shape=(frame.shape[1], frame.shape[0])  # (width, height)
                            )
                            person_obj.global_id = global_id
                    else:
                        person_obj = Person(tid, l, t, w, h, 0.9) #new tracking. creating a new Person object
                        # Extract features once
                        crop = frame[t:t + h, l:l + w]
                        person_obj.feature_vector = self.extract_person_features(crop)
                        self.tracked_persons[tid] = person_obj
                        
                        # Register with global tracker
                        if self.global_tracker and person_obj.feature_vector is not None:
                            global_id = self.global_tracker.create_or_update(
                                camera_name=self.camera_name,
                                local_id=tid,
                                feature_vector=person_obj.feature_vector,
                                bbox=(l, t, w, h),
                                frame_shape=(frame.shape[1], frame.shape[0])  # (width, height)
                            )
                            person_obj.global_id = global_id # assigning global id for user. check the camera name. 

                    # 4. Process faces (The new Async Logic)
                    face_ids = self.process_faces_in_person(frame, (l, t, w, h), tid)

                    # Link faces to person (read under lock to avoid races with recognition worker)
                    with self.lock:
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
        last_display_time = 0
        
        while not self.stop_event.is_set():
            current_time = time.time()
            
            # --- FPS THROTTLING: Skip frames to limit display refresh rate ---
            if current_time - last_display_time < self.gui_frame_delay:
                time.sleep(0.001)  # Sleep briefly to avoid busy-waiting
                continue
            
            last_display_time = current_time
            
            # Get Frame
            frame = None
            with self.lock:
                if self.last_frame_buffer["frame"] is not None:
                    frame = self.last_frame_buffer["frame"].copy()
            
            if frame is None: time.sleep(0.01); continue

            # 2. Snapshot Data (Safe Copy)
            with self.lock:
                display_persons = list(self.tracked_persons.values())
                q_size = self.recognition_queue.qsize()

            # 3. Drawing Loop
            for person_obj in display_persons:
                pid = int(person_obj.person_id)
                px, py, pw, ph = person_obj.x, person_obj.y, person_obj.w, person_obj.h

                color=(0,0,129)
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (0,0,139), 3)

                # Person Label - use global_tracker for consolidated name
                prim_face = person_obj.get_primary_face_name(self.global_tracker)
                gid = person_obj.global_id if person_obj.global_id else "-"
                
                # Check if any face has locked identity
                is_confirmed = any(
                    f.locked_identity and f.locked_identity not in ("Unknown", "Scanning...")
                    for f in person_obj.faces.values()
                ) if person_obj.faces else False
                
                # Show confirmed/unconfirmed status (use ASCII - OpenCV doesn't support Unicode)
                status = "[OK]" if is_confirmed else "[?]"
                label = f"G:{gid} L:{pid} {prim_face} {status}"
                cv2.putText(frame, label, (px, py - 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            # Send to PyQt
            if self.output_callback:
                self.output_callback(self.camera_name, frame)

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
