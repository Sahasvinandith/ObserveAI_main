import time

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