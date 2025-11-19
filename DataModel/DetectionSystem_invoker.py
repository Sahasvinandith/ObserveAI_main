import time
import threading  # Import threading to run the DetectionSystem in a separate thread
from DetectionSystem import DetectionSystem

def run_detection_system():
    """Function to run the DetectionSystem in a separate thread."""
    print("[THREAD] Starting detection system...")

    # Create an instance of the DetectionSystem
    system = DetectionSystem(
        video_path="test_videos/my_test_video.mp4",  # Path to the test video
        db_path="my_face_database"  # Path to the face database
    )

    # Start the DetectionSystem
    system.start()

    # Keep the thread alive until the stop event is set
    try:
        while not system.stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[THREAD] KeyboardInterrupt received. Stopping detection system...")
    finally:
        # Stop the DetectionSystem gracefully
        system.stop()
        print("[THREAD] Detection system stopped.")

def main():
    print("[MAIN] Initializing detection system thread...")

    # Create a thread for the DetectionSystem
    detection_thread = threading.Thread(target=run_detection_system, daemon=True)

    # Start the thread
    detection_thread.start()
    print("[MAIN] Detection system thread started.")

    # Keep the main thread alive to monitor the detection thread
    try:
        while detection_thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[MAIN] KeyboardInterrupt received. Exiting...")
    finally:
        print("[MAIN] Waiting for detection thread to finish...")
        detection_thread.join()  # Wait for the detection thread to finish
        print("[MAIN] Detection thread finished. Exiting program.")

if __name__ == "__main__":
    main()