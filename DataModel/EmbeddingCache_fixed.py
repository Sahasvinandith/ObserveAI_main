from deepface import DeepFace
import numpy as np
import os
import cv2
import tempfile

class EmbeddingCache:
    def __init__(self, db_path="Faces_db"):
        self.db_path = db_path
        self.embeddings = {}  # user_name -> embedding vector
        self.load_all_embeddings()
    
    def load_all_embeddings(self):
        """Pre-compute embeddings for ALL users at startup"""
        print("Building embedding cache...")
        
        if not os.path.exists(self.db_path):
            print(f"Database path {self.db_path} does not exist")
            return
        
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
        """Fast comparison using pre-computed embeddings"""
        try:
            # Save numpy array to temporary file
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                temp_path = tmp.name
                cv2.imwrite(temp_path, face_img)
            
            try:
                # Compute embedding for new face
                query_embedding = DeepFace.represent(
                    img_path=temp_path,
                    model_name="ArcFace",
                    detector_backend="skip",
                    enforce_detection=False
                )[0]["embedding"]
                
                query_embedding = np.array(query_embedding)
                
                # Compare with ALL cached embeddings (vectorized)
                best_match = None
                best_distance = float('inf')
                
                for user_name, stored_embedding in self.embeddings.items():
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
                
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except:
                    pass
                
        except Exception as e:
            print(f"Recognition error: {e}")
            import traceback
            traceback.print_exc()
            return "Unknown", 1.0
    
    def add_new_user(self, user_folder, face_img):
        """Add new user to cache"""
        try:
            # Save numpy array to temporary file
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                temp_path = tmp.name
                cv2.imwrite(temp_path, face_img)
            
            try:
                embedding = DeepFace.represent(
                    img_path=temp_path,
                    model_name="ArcFace",
                    detector_backend="skip",
                    enforce_detection=False
                )[0]["embedding"]
                
                self.embeddings[user_folder] = np.array(embedding)
                print(f"Added {user_folder} to cache")
                
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error adding to cache: {e}")
            import traceback
            traceback.print_exc()
