# 👁️ ObserveAI  
**Real-time Object Detection • Tracking • Face Recognition • Deep Learning**

ObserveAI is an intelligent computer-vision system built with **PyTorch**, **TensorFlow**, **YOLO (Ultralytics)**, **Deep SORT**, and **DeepFace**.  
It provides real-time detection, tracking, and recognition through a PyQt6 graphical interface.Designed for CCTV detection systems.

Still on development

---

## 🚀 Features

- **Real-time Object Detection** using YOLO models  
- **Multi-Object Tracking** powered by Deep SORT  
- **Face Recognition & Analysis** with DeepFace  
- **Live Camera or Video Input**  
- **Exportable Logs & Analytics**  
- **Lightweight PyQt6 GUI**  
- **GPU acceleration** (CUDA, cuDNN, TensorRT when available)

---

## 📦 Installation

Before installing, ensure that your Python version is **3.10 or later**.

### 1️. Clone the Repository
```bash
git clone https://github.com/your-username/ObserveAI.git
cd ObserveAI

```

### 2. Install Dependencies
```bash
pip install torch torchvision torchaudio
pip install "tensorflow[and-cuda]"
pip install opencv-contrib-python numpy
pip install ultralytics deep-sort-realtime deepface
pip install PyQt6 psutil
```


### 13. Run the application
```bash
python test.py

```