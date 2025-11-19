import cv2
import torch
import torch.nn as nn
from torchvision.transforms import transforms
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort


# --- Re-ID Model using ResNet-50 ---
class ReIDModel(nn.Module):
    """
    A Re-ID model using a pre-trained ResNet-50.
    The final classification layer is removed to get the feature vector.
    """

    def __init__(self):
        super(ReIDModel, self).__init__()
        # Load a pre-trained ResNet-50 from PyTorch Hub.
        # This model is excellent for extracting rich visual features.
        self.model = torch.hub.load('pytorch/vision:v0.10.0', 'resnet50', pretrained=True)
        # Replace the final fully connected layer with an identity function.
        # This gives us the feature vector (the embedding) instead of a classification output.
        self.model.fc = nn.Identity()

    def forward(self, x):
        return self.model(x)


# Initialize the Re-ID model and move to the appropriate device (GPU or CPU)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
reid_model = ReIDModel().to(device)
reid_model.eval()

# Image preprocessing for the Re-ID model
# We've added ToPILImage and Resize to match the input size expected by ResNet-50
preprocess = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((256, 128)),  # Re-ID models are often trained on this size
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def extract_features(person_crop):
    """
    Extracts a feature vector from a cropped image of a person.

    Args:
        person_crop (np.array): The cropped image of the person (H, W, C).

    Returns:
        np.array: A feature vector.
    """
    try:
        if person_crop.shape[0] == 0 or person_crop.shape[1] == 0:
            return None

        processed_image = preprocess(cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB))
        processed_image = processed_image.unsqueeze(0).to(device)  # Add batch dimension

        with torch.no_grad():
            features = reid_model(processed_image)

        return features.squeeze().cpu().numpy()

    except Exception as e:
        print(f"Error extracting features: {e}")
        return None


# Main function for tracking
def main():
    # Load the YOLOv8 model for object detection
    model = YOLO('yolov8n.pt')

    # Initialize the DeepSORT tracker
    tracker = DeepSort(max_age=300, n_init=3)

    # Open the video source (e.g., webcam)
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Could not open video stream.")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Get object detections from YOLO
        results = model(frame)
        detections = []
        for r in results:
            for box in r.boxes:
                # Filter for 'person' class (class ID 0 in COCO dataset)
                if int(box.cls[0]) == 0:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    # Add detection in the format [x1, y1, x2, y2, confidence, class_id]
                    detections.append(([x1, y1, x2 - x1, y2 - y1], conf, int(box.cls[0])))

        # Update the tracker
        tracks = tracker.update_tracks(detections, frame=frame)

        # Iterate over the tracks and draw bounding boxes
        for track in tracks:
            if not track.is_confirmed():  # check for false positive
                continue

            track_id = track.track_id
            ltrb = track.to_ltrb()
            bbox_x1, bbox_y1, bbox_x2, bbox_y2 = map(int, ltrb)

            # Draw the bounding box
            cv2.rectangle(frame, (bbox_x1, bbox_y1), (bbox_x2, bbox_y2), (0, 255, 0), 2)

            # Put the track ID text
            cv2.putText(frame, f"ID: {track_id}", (bbox_x1, bbox_y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        # Display the resulting frame
        cv2.imshow('YOLOv8 + DeepSORT', frame)

        # Break the loop on 'q' key press
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Release resources
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
