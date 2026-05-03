#!/usr/bin/env bash
# Smart Parking Management System - Jetson Orin Nano setup
#
# Tested on JetPack 6.2 (CUDA 12.6, Python 3.10).
# Installs the NVIDIA-built CUDA wheel for PyTorch, cuSPARSELt, every
# Python dependency from requirements.txt, and builds the TensorRT
# engine for YOLOv8n.

set -e

echo "============================================================"
echo " Smart Parking Management System - Jetson Setup"
echo "============================================================"
echo

# --- 1. Sanity checks -------------------------------------------------------
echo "[1/6] Verifying Python and JetPack version..."
python3 --version
sudo apt show nvidia-jetpack 2>/dev/null | grep Version || true
echo

# --- 2. System packages -----------------------------------------------------
echo "[2/6] Installing system packages..."
sudo apt update
sudo apt install -y v4l-utils ffmpeg curl wget python3-pip
echo

# --- 3. NVIDIA PyTorch (CUDA-enabled) ---------------------------------------
echo "[3/6] Installing NVIDIA PyTorch wheel for JetPack..."
TORCH_WHL_URL="https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl"
pip3 install --no-cache --force-reinstall --no-deps "$TORCH_WHL_URL"
echo

# --- 4. cuSPARSELt (required by NVIDIA's torch wheel) -----------------------
echo "[4/6] Installing cuSPARSELt..."
if ! ldconfig -p | grep -q libcusparseLt; then
    cd /tmp
    wget -q "https://developer.download.nvidia.com/compute/cusparselt/redist/libcusparse_lt/linux-aarch64/libcusparse_lt-linux-aarch64-0.6.3.2-archive.tar.xz"
    tar xf libcusparse_lt-linux-aarch64-0.6.3.2-archive.tar.xz
    cd libcusparse_lt-linux-aarch64-0.6.3.2-archive
    sudo cp -P lib/* /usr/local/cuda/lib64/
    sudo cp -P include/* /usr/local/cuda/include/
    sudo ldconfig
    cd -
    echo "cuSPARSELt installed."
else
    echo "cuSPARSELt already present, skipping."
fi
echo

# --- 5. Python dependencies + matching torchvision --------------------------
echo "[5/6] Installing Python dependencies..."
pip3 install --no-cache "numpy<2"
pip3 install --no-cache --no-deps "opencv-python==4.10.0.84"
pip3 install --no-cache -r requirements.txt
# Build torchvision against the NVIDIA torch wheel only if it's missing
if ! python3 -c "import torchvision; from torchvision.ops import nms" 2>/dev/null; then
    echo "Building torchvision from source (this takes 20-30 minutes)..."
    sudo apt install -y libjpeg-dev zlib1g-dev libpython3-dev \
        libavcodec-dev libavformat-dev libswscale-dev ninja-build
    cd ~
    [ -d torchvision-src ] || git clone --branch v0.20.0 --depth 1 \
        https://github.com/pytorch/vision.git torchvision-src
    cd torchvision-src
    export BUILD_VERSION=0.20.0
    export FORCE_CUDA=1
    export TORCH_CUDA_ARCH_LIST="8.7"
    python3 setup.py install --user
    cd -
fi
echo

# --- 6. Database + TensorRT engine ------------------------------------------
echo "[6/6] Initializing database and building TensorRT engine..."
python3 init_camera_db.py

if [ ! -f yolov8n.engine ]; then
    echo "Building yolov8n.engine (one-time, ~10 minutes)..."
    python3 -c "from ultralytics import YOLO; \
                YOLO('yolov8n.pt').export(format='engine', half=True, imgsz=320)"
    sed -i 's|YOLO("yolov8n.pt")|YOLO("yolov8n.engine")|' bay_camera_service.py
fi
echo

# --- Verify ------------------------------------------------------------------
python3 -c "
import torch, torchvision, cv2
print('CUDA   :', torch.cuda.is_available())
print('Device :', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')
print('Torch  :', torch.__version__)
print('TV     :', torchvision.__version__)
print('OpenCV :', cv2.__version__)
"

echo
echo "============================================================"
echo " Setup complete."
echo "============================================================"
echo
echo "Run the demo with:"
echo "    sudo nvpmodel -m 0 && sudo jetson_clocks"
echo "    export SPMS_HEADLESS=1"
echo "    python3 run_camera_demo.py"
echo
echo "Then open http://<jetson-ip>:5000 in a browser."
