from deepface import DeepFace
import numpy as np
import os
import threading

# Global singleton instance and lock
_embedding_cache_instance = None
_embedding_cache_lock = threading.Lock()

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
        """Pre-compute AVERAGED embeddings for ALL users at startup using all images"""
        print("Building embedding cache (averaging all images per user)...")
        
        with self._lock:
            for user_folder in os.listdir(self.db_path):
                user_path = os.path.join(self.db_path, user_folder)
                if not os.path.isdir(user_path):
                    continue
                
                # Get ALL images
                images = [f for f in os.listdir(user_path) if f.endswith(('.jpg', '.png'))]
                if not images:
                    continue
                
                # Compute embeddings for ALL images and average them
                embeddings_list = []
                for img_file in images:
                    img_path = os.path.join(user_path, img_file)
                    try:
                        embedding = DeepFace.represent(
                            img_path=img_path,
                            model_name="ArcFace",
                            enforce_detection=False
                        )[0]["embedding"]
                        embeddings_list.append(np.array(embedding))
                    except Exception as e:
                        print(f"[CACHE] Error processing {img_file}: {e}")
                        continue
                
                if embeddings_list:
                    # Average all embeddings for more robust recognition
                    avg_embedding = np.mean(embeddings_list, axis=0)
                    self.embeddings[user_folder] = avg_embedding
                    print(f"Cached {user_folder} (averaged {len(embeddings_list)} images)")
    
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
        Refresh a user's embedding from disk using ALL images (averaged).
        Useful when images have been updated or merged from another user.
        """
        user_path = os.path.join(self.db_path, str(user_folder))
        if not os.path.isdir(user_path):
            return False
        
        images = [f for f in os.listdir(user_path) if f.endswith(('.jpg', '.png'))]
        if not images:
            return False
        
        # Compute embeddings for ALL images and average them
        embeddings_list = []
        for img_file in images:
            img_path = os.path.join(user_path, img_file)
            try:
                embedding = DeepFace.represent(
                    img_path=img_path,
                    model_name="ArcFace",
                    enforce_detection=False
                )[0]["embedding"]
                embeddings_list.append(np.array(embedding))
            except Exception as e:
                print(f"[CACHE] Error processing {img_file}: {e}")
                continue
        
        if embeddings_list:
            avg_embedding = np.mean(embeddings_list, axis=0)
            with self._lock:
                self.embeddings[user_folder] = avg_embedding
            print(f"[CACHE] Refreshed {user_folder} (averaged {len(embeddings_list)} images)")
            return True
        
        return False
    
    def merge_users(self, source_user: str, target_user: str):
        """
        Merge source user folder into target user folder.
        - Move all images from source to target
        - Delete source folder
        - Remove source from cache
        - Refresh target embedding with combined images
        
        Args:
            source_user: User folder to merge FROM (will be deleted)
            target_user: User folder to merge INTO (will keep)
        
        Returns:
            True if merge successful, False otherwise
        """
        import shutil
        
        source_path = os.path.join(self.db_path, source_user)
        target_path = os.path.join(self.db_path, target_user)
        
        # Validate paths
        if not os.path.isdir(source_path):
            print(f"[MERGE] Source folder {source_user} not found")
            return False
        if not os.path.isdir(target_path):
            print(f"[MERGE] Target folder {target_user} not found")
            return False
        if source_user == target_user:
            print(f"[MERGE] Cannot merge user into itself")
            return False
        
        print(f"[MERGE] Starting merge: {source_user} -> {target_user}")
        
        try:
            # Get source images
            source_images = [f for f in os.listdir(source_path) if f.endswith(('.jpg', '.png'))]
            moved_count = 0
            
            for img_file in source_images:
                src_img_path = os.path.join(source_path, img_file)
                # Rename to avoid conflicts (prefix with source user name)
                new_name = f"merged_{source_user}_{img_file}"
                dst_img_path = os.path.join(target_path, new_name)
                
                # Move file
                shutil.move(src_img_path, dst_img_path)
                moved_count += 1
            
            print(f"[MERGE] Moved {moved_count} images from {source_user} to {target_user}")
            
            # Delete empty source folder
            os.rmdir(source_path)
            print(f"[MERGE] Deleted empty folder {source_user}")
            
            # Remove source from embedding cache
            with self._lock:
                if source_user in self.embeddings:
                    del self.embeddings[source_user]
                    print(f"[MERGE] Removed {source_user} from embedding cache")
            
            # Refresh target user embedding with combined images
            self.refresh_user(target_user)
            
            print(f"[MERGE] Successfully merged {source_user} into {target_user}")
            return True
            
        except Exception as e:
            print(f"[MERGE] Error during merge: {e}")
            return False
    
    def remove_user(self, user_folder: str):
        """Remove a user from the embedding cache (does not delete files)."""
        with self._lock:
            if user_folder in self.embeddings:
                del self.embeddings[user_folder]
                print(f"[CACHE] Removed {user_folder} from cache")
                return True
        return False


def get_embedding_cache(db_path="Faces_db")-> EmbeddingCache:
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
