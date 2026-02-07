from deepface import DeepFace
import numpy as np
import os
import threading

# Global singleton instance and lock
_embedding_cache_instance = None
_embedding_cache_lock = threading.Lock()


def get_embedding_cache(db_path="Faces_db"):
    """
    Get the singleton EmbeddingCache instance.
    Thread-safe: only one instance will be created even if called from multiple threads.
    """
    global _embedding_cache_instance
    
    if _embedding_cache_instance is None:
        with _embedding_cache_lock:
            # Double-check locking pattern
            if _embedding_cache_instance is None:
                _embedding_cache_instance = EmbeddingCache(db_path=db_path, _internal=True)
    
    return _embedding_cache_instance


class EmbeddingCache:
    def __init__(self, db_path="Faces_db", _internal=False):
        # Prevent direct instantiation - use get_embedding_cache() instead
        if not _internal:
            print("[WARNING] EmbeddingCache should be accessed via get_embedding_cache()")
            # Still allow for backward compatibility
        
        self.db_path = db_path
        self.embeddings = {}  # user_name -> embedding vector
        self._lock = threading.RLock()  # Thread-safe access to embeddings (RLock for reentrant calls)
        self._computing_embeddings = set()  # Track users currently being added (prevent duplicates)
        self.load_all_embeddings()
    
    def load_all_embeddings(self):
        """Pre-compute embeddings for ALL users at startup"""
        print("Building embedding cache...")
        
        with self._lock:
            for user_folder in os.listdir(self.db_path):
                user_path = os.path.join(self.db_path, user_folder)
                if not os.path.isdir(user_path):
                    continue
                
                # Get first image
                images = [f for f in os.listdir(user_path) if f.endswith(('.jpg', '.png'))]
                if not images:
                    continue
                
                img_path = os.path.join(user_path, images[0])
                
                # Compute embedding ONCE
                try:
                    embedding = DeepFace.represent(
                        img_path=img_path,
                        model_name="ArcFace",
                        enforce_detection=False
                    )[0]["embedding"]
                    
                    self.embeddings[user_folder] = np.array(embedding)
                    print(f"Cached embedding for {user_folder}")
                except Exception as e:
                    print(f"Error caching {user_folder}: {e}")
    
    def find_match(self, face_img):
        """
        Fast comparison using pre-computed embeddings.
        Thread-safe: reads are protected by lock.
        """
        try:
            # Compute embedding for new face (outside lock - expensive operation)
            query_embedding = DeepFace.represent(
                img_path=face_img,
                model_name="ArcFace",
                detector_backend="skip",
                enforce_detection=False
            )[0]["embedding"]
            
            query_embedding = np.array(query_embedding)
            
            # Compare with ALL cached embeddings (under lock for thread safety)
            best_match = None
            best_distance = float('inf')
            
            with self._lock:
                embeddings_snapshot = dict(self.embeddings)  # Snapshot for iteration
            
            for user_name, stored_embedding in embeddings_snapshot.items():
                # Cosine distance
                distance = 1 - np.dot(query_embedding, stored_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
                )
                
                if distance < best_distance:
                    best_distance = distance
                    best_match = user_name
            
            # ArcFace threshold
            if best_distance < 0.5:
                return best_match, best_distance
            
            return "Unknown", 1.0
            
        except Exception as e:
            print(f"Recognition error: {e}")
            return "Unknown", 1.0
    
    def add_new_user(self, user_folder, face_img):
        """
        Add new user to cache. Thread-safe.
        Prevents duplicate additions when multiple cameras detect the same new user.
        """
        # Check if this user is already being computed by another thread
        with self._lock:
            if user_folder in self.embeddings:
                print(f"[CACHE] {user_folder} already in cache, skipping")
                return True
            if user_folder in self._computing_embeddings:
                print(f"[CACHE] {user_folder} already being computed, skipping")
                return False
            self._computing_embeddings.add(user_folder)
        
        try:
            # Compute embedding outside lock (expensive operation)
            embedding = DeepFace.represent(
                img_path=face_img,
                model_name="ArcFace",
                detector_backend="skip",
                enforce_detection=False
            )[0]["embedding"]
            
            # Update cache under lock
            with self._lock:
                self.embeddings[user_folder] = np.array(embedding)
                self._computing_embeddings.discard(user_folder)
            
            print(f"[CACHE] Added {user_folder} to cache")
            return True
            
        except Exception as e:
            print(f"[CACHE] Error adding {user_folder}: {e}")
            with self._lock:
                self._computing_embeddings.discard(user_folder)
            return False
    
    def refresh_user(self, user_folder):
        """
        Refresh a user's embedding from disk. 
        Useful when their images have been updated with higher quality ones.
        """
        with self._lock:
            user_path = os.path.join(self.db_path, str(user_folder))
            if not os.path.isdir(user_path):
                return False
            
            images = [f for f in os.listdir(user_path) if f.endswith(('.jpg', '.png'))]
            if not images:
                return False
            
            # Use the highest quality image (sorted by quality score in filename)
            def get_quality(fname):
                if '_q' in fname:
                    try:
                        return float(fname.split('_q')[1].split('.')[0])
                    except:
                        return 0
                return 0
            
            images.sort(key=get_quality, reverse=True)
            img_path = os.path.join(user_path, images[0])
        
        try:
            embedding = DeepFace.represent(
                img_path=img_path,
                model_name="ArcFace",
                enforce_detection=False
            )[0]["embedding"]
            
            with self._lock:
                self.embeddings[user_folder] = np.array(embedding)
            
            print(f"[CACHE] Refreshed embedding for {user_folder}")
            return True
            
        except Exception as e:
            print(f"[CACHE] Error refreshing {user_folder}: {e}")
            return False