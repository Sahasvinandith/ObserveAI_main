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
from DataModel.Face import Face
from DataModel.ActionManager import ActionManager
from DataModel.Face import Face
from DataModel.ActionManager import ActionManager

def Ai_System_thread(camera_name, db_path="Faces_db", camera_buffer=None, output_callback=None, frame_skip_interval=3, gui_fps_limit=15, global_tracker=None, Main_Detection_system=None, action_callback=None):
    detection_system = DetectionSystem(
        camera_name=camera_name,
        db_path=db_path,
        camera_buffer=camera_buffer,
        output_callback=output_callback,
        frame_skip_interval=frame_skip_interval,
        gui_fps_limit=gui_fps_limit,
        global_tracker=global_tracker,
        action_callback=action_callback
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
        self.color_hist = None
        self.global_id = None  # Global ID from GlobalPersonTracker
        # Cross-camera identity inheritance
        self.inherited_identity = None      # Identity inherited from global tracker (e.g., "User_1")
        self.inherited_confidence = None    # Confidence of the inherited identity
        
        # --- Actions data (for async display) ---
        self.active_action = None           # Name of the currently detected action
        self.action_timestamp = 0.0          # Last time an action was detected
        
        # --- Debug data (for ghost check) ---
        self.hits = 0
        self.age = 0
        self.time_since_update = 0

        # --- Face size feedback ---
        self.too_small_rejections = 0
        self.too_small_logged = False

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
            
        if not self.faces:
            # If no faces but many size rejections, return feedback
            if getattr(self, 'too_small_rejections', 0) > 30:
                return "Too Distant"
            return "Unknown"

        # Prioritize faces that are NOT scanning and NOT unknown if possible
        valid_faces = [f for f in self.faces.values() if f.name != "Scanning..." and f.name != "Unknown"]
        if valid_faces:
            # Choose the face with highest confidence among valid faces
            best_valid = max(valid_faces, key=lambda f: f.confidence)
            return best_valid.name
            
        # Fallback: pick the most confident face overall
        best_face = max(self.faces.values(), key=lambda f: f.confidence)
        
        # If the best face is still Scanning/Unknown and we have many size rejections,
        # it might be better to show "Too Distant" if the size rejections are very high,
        # but usually if we have a face object, "Scanning..." is more accurate.
        # However, if the user specifically asked for "Too Distant" when face is small,
        # and we ARE getting size rejections even for existing face tracks (which we are tracking now),
        # we can show it.
        
        if best_face.name in ("Scanning...", "Unknown") and getattr(self, 'too_small_rejections', 0) > 30:
            return "Too Distant"
            
        return best_face.name


class DetectionSystem:
    def __init__(self, camera_name, db_path="Faces_db", camera_buffer=None, output_callback=None, frame_skip_interval=3, gui_fps_limit=15, global_tracker:GlobalPersonTracker=None, action_callback=None):
        print("[INFO] Initializing Detection System...")

        self.camera_name = camera_name
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        
        # Global person tracking
        self.global_tracker = global_tracker
        
        # Action detection callback (called on the AI thread, must be thread-safe)
        self.action_callback = action_callback
        
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
        
        # Action Queue (Buffer for async pose estimation)
        self.action_queue = queue.Queue(maxsize=10)
        
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        
        self.last_frame_buffer = {"frame": None, "timestamp": 0.0}
        
        # Debug: raw YOLO detections (for ghost check)
        self.raw_detections = []

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

        # --- Actions Configuration ---
        self.enabled_actions = self.settings.get("camera_actions", {}).get(self.camera_name, [])
        self.action_manager = ActionManager()
        self.reference_actions = {}
        for act in self.enabled_actions:
            data = self.action_manager.get_action_data(act)
            if data:
                self.reference_actions[act] = data

        # Cooldown: key = "action_name:person_id", value = last_fired timestamp
        self._action_cooldowns: dict = {}
        self.ACTION_COOLDOWN_SECONDS = 5.0

        self.initialize_models()
        
        # Get starting ID
        self.next_face_id = self.get_next_available_face_id()

        # Threads
        self.cam_thread = None
        self.proc_thread = None
        self.disp_thread = None
        self.recog_thread = None # RESTORED WORKER
        self.db_update_thread = None  # Database update worker
        self.action_thread = None     # Action detection worker
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
        
        # Initialize YOLOv8-Pose for actions
        self.pose_model = None
        if hasattr(self, 'enabled_actions') and self.enabled_actions:
            print(f"[{self.camera_name}] Loading YOLOv8-Pose for actions: {self.enabled_actions}")
            self.pose_model = YOLO("yolov8n-pose.pt")
            
        print("[INFO] Models loaded.")
        time.sleep(3.0)

    def reload_actions(self):
        """Hot-reload enabled actions from settings — can be called while the system is running."""
        self.settings.load()  # Re-read settings.json from disk
        self.action_manager.load_all_actions()  # Re-scan Actions_db
        new_enabled = self.settings.get("camera_actions", {}).get(self.camera_name, [])
        new_refs = {}
        for act in new_enabled:
            data = self.action_manager.get_action_data(act)
            if data:
                new_refs[act] = data
        with self.lock:
            self.enabled_actions = new_enabled
            self.reference_actions = new_refs
            # Lazy-load pose model if actions are being enabled for the first time
            if self.enabled_actions and self.pose_model is None:
                print(f"[{self.camera_name}] Lazy-loading YOLOv8-Pose for newly assigned actions")
                self.pose_model = YOLO("yolov8n-pose.pt")
        print(f"[{self.camera_name}] Actions reloaded: {new_enabled}")

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

            self.db_update_thread = threading.Thread(target=self.db_update_worker, daemon=True)
            self.db_update_thread.start()

            # NEW: Action Worker Thread
            self.action_thread = threading.Thread(target=self.action_worker_function, daemon=True)
            self.action_thread.start()

            self.watchdog_thread = threading.Thread(target=self.watchdog_thread_function, daemon=True)
            self.watchdog_thread.start()
        except Exception as e:
            print(f"[ERROR] Failed to start threads: {e}")

    def stop(self):
        print("[INFO] Stopping Detection System...")
        self.stop_event.set()
        
        # Wait for threads to finish
        for t in [self.proc_thread, self.disp_thread, self.recog_thread, self.db_update_thread, self.action_thread, self.watchdog_thread, self.cam_thread]:
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
                    # print(f"[DEBUG] Saved face {face_id_key} to debug_face_temp.jpg (shape={face_img.shape})")
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
                    # Check if this face's person has an inherited identity from global tracker
                    inherited_name = None
                    with self.lock:
                        person_id = face_obj.person_id
                        if person_id and person_id in self.tracked_persons:
                            person = self.tracked_persons[person_id]
                            if person.inherited_identity and person.inherited_identity not in ("Unknown", "Scanning..."):
                                inherited_name = person.inherited_identity
                                inherited_conf = person.inherited_confidence or 0.5
                    
                    if inherited_name:
                        # Use inherited identity instead of creating new user!
                        print(f"[INHERIT] Face {face_id_key} Unknown from face recog, but inheriting '{inherited_name}' from global tracker")
                        with self.lock:
                            face_obj.name = inherited_name
                            face_obj.locked_identity = inherited_name
                            face_obj.avg_confidence = inherited_conf
                            face_obj.unknown_count = 0
                            face_obj.is_recognizing = False
                            
                            # Report to global tracker for consolidation
                            if person_id and person_id in self.tracked_persons:
                                person = self.tracked_persons[person_id]
                                if person.global_id and self.global_tracker:
                                    self.global_tracker.update_face_identity(
                                        person.global_id,
                                        inherited_name,
                                        inherited_conf
                                    )
                        continue  # Skip Unknown threshold logic
                    
                    # No inherited identity - proceed with normal Unknown threshold logic
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

    # --- 1.6 ACTION WORKER ---
    def action_worker_function(self):
        """
        Background thread. Pulls person crops from action_queue,
        runs YOLOv8-pose, and processes any detected actions.
        """
        print("[THREAD] Action Worker started")
        
        while not self.stop_event.is_set():
            try:
                # Get task: (crop, person_id, frame_timestamp)
                task = self.action_queue.get(timeout=1.0)
                crop, person_id, _ = task
                
                # Find the person object
                with self.lock:
                    person_obj = self.tracked_persons.get(person_id)
                
                if person_obj:
                    self.process_actions(crop, person_obj)
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ACTION WORKER ERROR] {e}")
        
        print("[THREAD] Action Worker stopped")

    
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
            # print(f"[DETECTION] Running face detection for person {person_id} (tracked faces: {len(active_tracked_faces)})")
            person_crop = frame[py:py + ph, px:px + pw]
            if person_crop.size > 0:
                # DEBUG: Time the face detection
                import time as _time
                _face_start = _time.perf_counter()
                results = self.yolo_face_model(person_crop, verbose=False)
                _face_elapsed = (_time.perf_counter() - _face_start) * 1000

                for r in results:
                    for box in r.boxes:
                        # Face detection confidence
                        yolo_conf = float(box.conf[0]) if box.conf is not None else 0.0
                        
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
                            print(f"[VALIDATION] Skipping face at ({gx}, {gy}): size ({gw} x {gh}) is too small")
                            # Track rejections for the person
                            with self.lock:
                                person_obj = self.tracked_persons.get(person_id)
                                if person_obj:
                                    person_obj.too_small_rejections += 1
                                    # Log once per session when threshold reached
                                    if person_obj.too_small_rejections >= 30 and not person_obj.too_small_logged:
                                        from DataModel.LogManager import get_log_manager
                                        log_msg = f"Face too small for recognition ({gw}x{gh} < {min_width}x{min_height})"
                                        get_log_manager().add_log(
                                            log_type='detection',
                                            person_name=person_obj.get_primary_face_name(),
                                            cameras=[self.camera_name],
                                            message=log_msg
                                        )
                                        person_obj.too_small_logged = True
                                        print(f"[LOG] {log_msg} for person {person_id}")
                            continue
                        
                        # Reset size rejection counter if face is large enough
                        with self.lock:
                            person_obj = self.tracked_persons.get(person_id)
                            if person_obj:
                                person_obj.too_small_rejections = 0
                        
                        # Check confidence requirement
                        if yolo_conf < min_conf:
                            print(f"[VALIDATION] Skipping face at ({gx}, {gy}): confidence ({yolo_conf:.2f}) is too low")
                            continue
                        
                        new_center = (gx + gw // 2, gy + gh // 2)

                        # --- MATCH WITH ALL EXISTING FACES (locked AND unlocked) ---
                        matched_face = None
                        for face_obj in person_faces:
                            existing_center = face_obj.get_center()
                            dist = math.dist(new_center, existing_center)
                            if dist < self.DISTANCE_THRESHOLD:
                                matched_face = face_obj
                                # mathed face found
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
                                    print(f"[RE-QUEUE] Re-queuing unlocked Face {matched_face.face_id} for recognition (tracker_miscount={matched_face.tracker_miscount})for local id {person_id} ")
                                    try:
                                        face_img = frame[gy:gy + gh, gx:gx + gw].copy()
                                        if face_img.size > 0:
                                            matched_face.is_recognizing = True
                                            self.recognition_queue.put((matched_face.face_id, face_img), block=False)
                                            print(f"[QUEUE] Re-queued unlocked Face {matched_face.face_id} for recognition")
                                    except queue.Full:
                                        print(f"[QUEUE] Recognition queue is full for face {matched_face.face_id}; skipping.")
                                        pass  # Queue full, try next time
                                    except Exception as e:
                                        print(f"[QUEUE ERROR] Error occurred while re-queueing face {matched_face.face_id}: {e}")
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
                                print(f"new face detectet for {person_id} - face_id-{face_id}")
                                
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

                                # Try to push to recognition queue. If the queue is full,
                                # remove the temporary face to avoid leaving a face
                                # object with `is_recognizing=True` that will never be processed.
                                try:
                                    self.recognition_queue.put((face_id, face_img), block=False)
                                except queue.Full:
                                    # Clean up the partially-created face
                                    with self.lock:
                                        if face_id in self.identified_faces:
                                            del self.identified_faces[face_id]
                                    print(f"[QUEUE] Recognition queue full — discarded Face {face_id}")
                                    # Skip incrementing next_face_id so the id can be reused shortly
                                    continue

                                # SUCCESS: Now we finalize creation
                                self.next_face_id += 1
                                print(f"[QUEUE] Pushed Face {face_id} for recognition")
                                detected_face_ids.append(face_id)

                        except queue.Full:
                            #
                            # If queue is full, we DO NOT create the face object.
                            # We just ignore it this frame. It will be detected again in the next frame.
                            pass

        return detected_face_ids
        

    def process_actions(self, crop, person_obj):
        """Runs YOLOv8-Pose on person crop and checks for active actions."""
        try:
            # Run YOLOv8-Pose detection
            results = self.pose_model(crop, verbose=False)
            
            if len(results) > 0 and results[0].keypoints is not None and len(results[0].keypoints.data) > 0:
                h, w = crop.shape[:2]
                # Extract normalized xyn keypoints [17, 2]
                kpts = results[0].keypoints.xyn[0].cpu().numpy() # Normalized 0-1
                
                # Format to [17, 3] for compatibility (x, y, z=0)
                landmarks = np.zeros((17, 3))
                landmarks[:, :2] = kpts
                
                # Compare against reference actions
                for act_name, ref_data in self.reference_actions.items():
                    if "landmarks" in ref_data:
                        active_indices = ref_data.get("active_keypoints", list(range(17)))
                        
                        # Filter out indices that might be from old 33-point MediaPipe files
                        active_indices = [i for i in active_indices if i < 17]
                        
                        # Support dict format from new pose_creator
                        if isinstance(ref_data["landmarks"], dict):
                            # Try to extract 17 points, if the file has 33 it will just take the first 17
                            ref_marks_list = []
                            for i in range(17):
                                if str(i) in ref_data["landmarks"]:
                                    ref_marks_list.append([
                                        ref_data["landmarks"][str(i)]["x"],
                                        ref_data["landmarks"][str(i)]["y"],
                                        ref_data["landmarks"][str(i)].get("z", 0.0)
                                    ])
                                else:
                                    ref_marks_list.append([0, 0, 0])
                            ref_marks = np.array(ref_marks_list)
                        else:
                            ref_marks = np.array(ref_data["landmarks"])[:17]
                            
                        if ref_marks.shape == landmarks.shape:
                            # Filter to active keypoints
                            current_active = np.array([landmarks[i] for i in active_indices])
                            ref_active = np.array([ref_marks[i] for i in active_indices])
                            
                            if len(active_indices) > 0:
                                # Euclidean distance
                                dist = np.linalg.norm(current_active - ref_active) / len(active_indices)
                                if dist < 0.10: # Lower threshold for YOLO normalized coords
                                    # Update person object for display visibility
                                    person_obj.active_action = act_name
                                    person_obj.action_timestamp = time.time()

                                    # --- Cooldown check ---
                                    cooldown_key = f"{act_name}:{person_obj.person_id}"
                                    now = time.time()
                                    last_fired = self._action_cooldowns.get(cooldown_key, 0.0)
                                    if now - last_fired < self.ACTION_COOLDOWN_SECONDS:
                                        continue
                                    
                                    self._action_cooldowns[cooldown_key] = now
                                    person_name = person_obj.get_primary_face_name(self.global_tracker)
                                    print(f"[ACTION DETECTED] {act_name} detected for person {person_obj.person_id} ({person_name}) on {self.camera_name}!")
                                    
                                    # --- Fire callback to UI ---
                                    if self.action_callback:
                                        try:
                                            self.action_callback(self.camera_name, person_name, act_name, now)
                                        except Exception as cb_err:
                                            print(f"[ACTION CALLBACK ERROR] {cb_err}")
                                            
                    # Extend here for DTW / Angle Check or Custom Classifier based on pose format
        except Exception as e:
            print(f"[ACTION ERROR] Failed to process actions: {e}")

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
                    
                    with self.lock:
                        self.raw_detections = [([dx, dy, dw, dh], dc) for ([dx, dy, dw, dh], dc, _) in detections]
                        
                    # Only update tracker when we have fresh detections
                    tracks = self.person_tracker.update_tracks(detections, frame=frame) #check the track of user. i think this is local id
                else:
                    # Between detection frames, still update tracker with empty detections
                    # This keeps existing tracks alive
                    with self.lock:
                        self.raw_detections = []
                    tracks = self.person_tracker.update_tracks([], frame=frame) 

                # 3. Process tracked persons
                current_tracked_ids = [] #check the track of user. i think this is local id

                for track in tracks:
                    # Process only confirmed tracks
                    # With n_init=1, tracks confirm immediately after first detection
                    if not track.is_confirmed():
                        # print(f"deepsort track for user in {self.camera_name} is not yet confirmed")
                        continue

                    tid = track.track_id
                    current_tracked_ids.append(tid)
                    l, t, r, b = map(int, track.to_ltrb())
                    w, h = r - l, b - t

                    # Update/Create Person already tracked person
                    if tid in self.tracked_persons:
                        person_obj = self.tracked_persons[tid] 
                        person_obj.update_position(l, t, w, h, 0.9)
                        
                        # Store debug info (Ghost check)
                        person_obj.hits = track.hits
                        person_obj.age = track.age
                        person_obj.time_since_update = track.time_since_update
                    current_tracked_ids.append(tid)
                    l, t, r, b = map(int, track.to_ltrb())
                    w, h = r - l, b - t

                    # ── Minimum-size gate ──────────────────────────────────────────
                    # Ignore tiny/partial detections (person just entering the frame)
                    MIN_CROP_W = 100   # pixels
                    MIN_CROP_H = 200  # pixels
                    WARMUP_FRAMES = 5  # how many valid crops to collect before using the best one

                    # Update/Create Person already tracked person
                    if tid in self.tracked_persons:
                        person_obj = self.tracked_persons[tid] 
                        person_obj.update_position(l, t, w, h, 0.9)
                        
                        # --- Action Detection ---
                        if hasattr(self, 'pose_model') and self.pose_model and w > 50 and h > 100:
                            # Run pose estimation asynchronously
                            crop = frame[t:t+h, l:l+w]
                            if crop.size > 0:
                                try:
                                    self.action_queue.put_nowait((crop.copy(), tid, time.time()))
                                except queue.Full:
                                    pass # Busy, skip this frame
                                
                        # ── Warm-up buffer: collect crops, wait for best ────────
                        if person_obj.feature_vector is None:
                            if w >= MIN_CROP_W and h >= MIN_CROP_H:
                                crop = frame[t:t + h, l:l + w]
                                if crop.size > 0:
                                    if not hasattr(person_obj, '_crop_warmup_buffer'):
                                        person_obj._crop_warmup_buffer = []
                                    person_obj._crop_warmup_buffer.append((w * h, crop.copy()))
                                    
                                    if len(person_obj._crop_warmup_buffer) >= WARMUP_FRAMES:
                                        # Pick the crop with the largest area
                                        best_crop = max(person_obj._crop_warmup_buffer, key=lambda x: x[0])[1]
                                        person_obj.feature_vector = self.extract_person_features(best_crop)
                                        person_obj.color_hist = self.extract_color_features(best_crop, self.camera_name, tid)
                                        del person_obj._crop_warmup_buffer  # free memory
                                        print(f"[WARMUP] L:{tid} ({self.camera_name}): features extracted from best of {WARMUP_FRAMES} crops ({w}×{h}px)")
                            else:
                                # Detection too small — skip silently, wait for person to fully enter frame
                                pass
                                
                        if not hasattr(person_obj, '_no_feature_frames'):
                            person_obj._no_feature_frames = 0
                        
                        # Update global tracker if we have features but no global ID yet
                        if self.global_tracker and person_obj.global_id is None:
                            # If we have features, OR if we've waited 15 frames without features
                            if person_obj.feature_vector is not None or person_obj._no_feature_frames > 15:
                                # Try to get identity if already discovered locally
                                current_identity = person_obj.get_primary_face_name()
                                
                                global_id = self.global_tracker.create_or_update(
                                    camera_name=self.camera_name,
                                    local_id=tid,
                                    feature_vector=person_obj.feature_vector,
                                    color_hist=person_obj.color_hist,
                                    bbox=(l, t, w, h),
                                    frame_shape=(frame.shape[1], frame.shape[0]),
                                    name=current_identity
                                )
                                person_obj.global_id = global_id
                                
                                # Sync any faces that were identified BEFORE the global_id was assigned
                                for face_obj in person_obj.faces.values():
                                    if face_obj.locked_identity and face_obj.locked_identity not in ("Unknown", "Scanning..."):
                                        print(f"[SYNC] Reporting pre-identified face {face_obj.face_id} ({face_obj.locked_identity}) for new G:{global_id}")
                                        self.global_tracker.update_face_identity(
                                            global_id,
                                            face_obj.locked_identity,
                                            face_obj.avg_confidence
                                        )
                                        
                                # Hide obsolete same-camera fragments that merged into this ID
                                for other_tid, other_person in self.tracked_persons.items():
                                    if other_tid != tid and other_person.global_id == global_id:
                                        print(f"[CLEANUP] Track L:{tid} merged with Global G:{global_id}. Marking ghost track L:{other_tid} obsolete.")
                                        other_person.is_obsolete = True
                                        
                                # Check if this global person already has a known identity
                                existing_name, existing_conf = self.global_tracker.get_person_identity(global_id)
                                if existing_name not in ("Unknown", "Scanning..."):
                                    person_obj.inherited_identity = existing_name
                                    person_obj.inherited_confidence = existing_conf
                                    print(f"[INHERIT] Person L:{tid} inherited '{existing_name}' (conf={existing_conf:.3f}) from global G:{global_id}")
                            else:
                                person_obj._no_feature_frames += 1
                        
                        # --- POSITION UPDATE + FEATURE REFRESH for already-tracked persons ---
                        elif self.global_tracker and person_obj.global_id is not None:
                            # Track frame count for periodic feature refresh
                            if not hasattr(person_obj, '_feature_refresh_counter'):
                                person_obj._feature_refresh_counter = 0
                            person_obj._feature_refresh_counter += 1
                            
                            # Every 30 frames: re-extract Re-ID features (only if crop is big enough)
                            refreshed_features = None
                            refreshed_color = None
                            if person_obj._feature_refresh_counter >= 30:
                                person_obj._feature_refresh_counter = 0
                                if w >= MIN_CROP_W and h >= MIN_CROP_H:
                                    crop = frame[t:t + h, l:l + w]
                                    if crop.size > 0:
                                        refreshed_features = self.extract_person_features(crop)
                                        refreshed_color = self.extract_color_features(crop, self.camera_name, tid)
                                        if refreshed_features is not None:
                                            person_obj.feature_vector = refreshed_features
                                        if refreshed_color is not None:
                                            person_obj.color_hist = refreshed_color
                                else:
                                    # Crop too small for reliable refresh — skip this cycle
                                    print(f"[REFRESH SKIP] L:{tid} crop too small ({w}×{h}px), skipping feature refresh")
                            
                            # Every frame: update position on map (lightweight)
                            self.global_tracker.update_person_position(
                                person_obj.global_id,
                                self.camera_name,
                                bbox=(l, t, w, h),
                                feature_vector=refreshed_features,
                                color_hist=refreshed_color
                            )
                    else:
                        person_obj = Person(tid, l, t, w, h, 0.9)
                        person_obj._no_feature_frames = 0
                        person_obj._crop_warmup_buffer = []

                        # Only seed the warmup buffer if this first detection is big enough
                        if w >= MIN_CROP_W and h >= MIN_CROP_H:
                            crop = frame[t:t + h, l:l + w]
                            if crop.size > 0:
                                person_obj._crop_warmup_buffer.append((w * h, crop.copy()))

                        self.tracked_persons[tid] = person_obj
                        # Features will be extracted once warmup buffer is full (handled above on next frames)
                        print(f"[NEW TRACK] L:{tid} ({self.camera_name}): {w}×{h}px — warmup buffer started (need {WARMUP_FRAMES} valid crops)")


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

            with self.lock:
                display_persons = list(self.tracked_persons.values())
                raw_dets = list(self.raw_detections)
                q_size = self.recognition_queue.qsize()

            # 3. Drawing Loop
            current_time = time.time()
            
            # --- DEBUG: Raw YOLO Bboxes (Yellow) ---
            for box, conf in raw_dets:
                lx, ly, lw, lh = box
                cv2.rectangle(frame, (lx, ly), (lx + lw, ly + lh), (0, 255, 255), 1)
                cv2.putText(frame, f"YOLO:{conf:.2f}", (lx, ly + 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
            for person_obj in display_persons:
                # Skip drawing if marked obsolete (e.g. tracking fragment merged into new track)
                if getattr(person_obj, 'is_obsolete', False):
                    continue
                    
                # Skip drawing if person hasn't been seen recently
                if current_time - person_obj.last_seen > 1.0:
                    continue
                
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
                
                # --- Debug Label (Ghost check) ---
                debug_label = f"Hits:{person_obj.hits} Age:{person_obj.age} Upd:{person_obj.time_since_update}"
                cv2.putText(frame, debug_label, (px, py + ph + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                
                # Draw active action if recent (within 2 seconds)
                if getattr(person_obj, 'active_action', None) and (current_time - getattr(person_obj, 'action_timestamp', 0) < 2.0):
                    cv2.putText(frame, f"Action: {person_obj.active_action}", (px, py - 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            
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

    # Set to False once debugging is done to stop saving crops to disk
    COLOR_DEBUG_SAVE = True
    COLOR_DEBUG_DIR = "debug_crops"
    _color_debug_counter = 0

    def extract_color_features(self, person_crop, camera_name="cam", local_id="?"):
        """Extract high-precision 3D HSV color histogram from the exact center of the torso.
        
        If COLOR_DEBUG_SAVE is True, saves both the full person crop and the isolated
        torso crop to debug_crops/ so you can visually inspect the histogram input.
        """
        try:
            h, w = person_crop.shape[:2]
            if h <= 2 or w <= 2:
                return None
            
            # Isolate the center torso: 15% to 60% height, 25% to 75% width.
            # This completely removes backgrounds, arms, and legs.
            y_start = int(h * 0.35)
            y_end = int(h * 0.70)
            x_start = int(w * 0.25)
            x_end = int(w * 0.75)
            
            if y_end <= y_start or x_end <= x_start:
                return None
                
            torso_crop = person_crop[y_start:y_end, x_start:x_end]

            # ── Gray World colour normalisation ─────────────────────────────
            # Different camera models have different white balance, gamma, and
            # colour temperature. This compensates by scaling each RGB channel
            # so its mean equals 128, bringing both cameras to a common
            # neutral-grey reference before the histogram is computed.
            try:
                gw = torso_crop.astype(np.float32)
                means = gw.mean(axis=(0, 1))          # [mean_B, mean_G, mean_R]
                if all(m > 5 for m in means):          # skip on near-black crops
                    scale = 128.0 / means
                    gw *= scale
                    torso_crop = np.clip(gw, 0, 255).astype(np.uint8)
            except Exception:
                pass  # fall back to unnormalised crop if anything goes wrong
            # ─────────────────────────────────────────────────────────────────


            if DetectionSystem.COLOR_DEBUG_SAVE:
                import os, time
                DetectionSystem._color_debug_counter += 1
                # Only save every 30 extractions to avoid flooding disk
                if DetectionSystem._color_debug_counter % 2 == 0:
                    os.makedirs(DetectionSystem.COLOR_DEBUG_DIR, exist_ok=True)
                    ts = int(time.time() * 1000) % 100000  # short timestamp
                    safe_cam = str(camera_name).replace(" ", "_").replace("/", "-")
                    # Annotate the full crop with a rectangle showing the torso region
                    annotated = person_crop.copy()
                    cv2.rectangle(annotated, (x_start, y_start), (x_end, y_end), (0, 255, 0), 2)
                    cv2.putText(annotated, "torso", (x_start, y_start - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                    full_path = os.path.join(DetectionSystem.COLOR_DEBUG_DIR,
                                             f"{safe_cam}_L{local_id}_{ts}_full.jpg")
                    torso_path = os.path.join(DetectionSystem.COLOR_DEBUG_DIR,
                                              f"{safe_cam}_L{local_id}_{ts}_torso.jpg")
                    # cv2.imwrite(full_path, annotated)
                    # cv2.imwrite(torso_path, torso_crop)
                    # print(f"[COLOR DEBUG] Saved: {torso_path}")
            # ────────────────────────────────────────────────────────────────────

            hsv_crop = cv2.cvtColor(torso_crop, cv2.COLOR_BGR2HSV)
            
            # Compute 3D histogram (Hue, Saturation, Value)
            # Hue: 0-180, Saturation: 0-256, Value: 0-256
            # Bins: 8x8x8 = 512 dimensions. Captures black/white shirts via Value bins.
            hist = cv2.calcHist([hsv_crop], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
            cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
            return hist.flatten()
        except Exception as e:
            print(f"Error extracting color histogram: {e}")
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
