const API_URL = "http://127.0.0.1:5000";

let selectedFile = null;
let selectedVideo = null;
let cameraStream = null;

const imageInput = document.getElementById("imageInput");
const videoInput = document.getElementById("videoInput");
const previewImage = document.getElementById("previewImage");
const previewText = document.getElementById("previewText");
const detectButton = document.getElementById("detectButton");
const detectVideoButton = document.getElementById("detectVideoButton");
const resultCard = document.getElementById("resultCard");
const resultImage = document.getElementById("resultImage");
const resultInfo = document.getElementById("resultInfo");
const videoResultCard = document.getElementById("videoResultCard");
const resultVideo = document.getElementById("resultVideo");
const videoResultInfo = document.getElementById("videoResultInfo");
const loading = document.getElementById("loading");
const loadingText = document.getElementById("loadingText");
const errorMessage = document.getElementById("errorMessage");

const cameraButton = document.getElementById("cameraButton");
const cameraContainer = document.getElementById("cameraContainer");
const cameraVideo = document.getElementById("cameraVideo");
const captureButton = document.getElementById("captureButton");
const closeCameraButton = document.getElementById("closeCameraButton");
const cameraCanvas = document.getElementById("cameraCanvas");

resultCard.style.display = "none";
videoResultCard.style.display = "none";
loading.style.display = "none";
errorMessage.style.display = "none";
previewImage.style.display = "none";
resultImage.style.display = "none";
resultVideo.style.display = "none";
cameraContainer.style.display = "none";
detectButton.disabled = true;
detectVideoButton.disabled = true;

// UPLOAD IMAGE
imageInput.addEventListener("change", function () {
    const file = this.files[0];

    if (!file) return;

    if (!file.type.startsWith("image/")) {
        alert("Please select an image file.");
        return;
    }

    selectedFile = file;
    selectedVideo = null;

    const imageURL = URL.createObjectURL(file);

    previewImage.src = imageURL;
    previewImage.style.display = "block";
    previewText.style.display = "none";

    detectButton.disabled = false;
    detectVideoButton.disabled = true;

    resultCard.style.display = "none";
    videoResultCard.style.display = "none";
    resultImage.style.display = "none";
    resultVideo.style.display = "none";
    resultInfo.innerHTML = "";
    videoResultInfo.innerHTML = "";
    errorMessage.style.display = "none";

    console.log("Image selected:", file.name);
});

// UPLOAD VIDEO
videoInput.addEventListener("change", function () {
    const file = this.files[0];

    if (!file) return;

    if (!file.type.startsWith("video/")) {
        alert("Please select a video file.");
        return;
    }

    selectedVideo = file;
    selectedFile = null;

    previewImage.src = "";
    previewImage.style.display = "none";

    previewText.style.display = "block";
    previewText.textContent = "🎥 Video selected: " + file.name;

    detectVideoButton.disabled = false;
    detectButton.disabled = true;

    resultCard.style.display = "none";
    videoResultCard.style.display = "none";
    resultImage.style.display = "none";
    resultVideo.style.display = "none";
    resultInfo.innerHTML = "";
    videoResultInfo.innerHTML = "";
    errorMessage.style.display = "none";

    console.log("Video selected:", file.name);
});

// OPEN CAMERA
cameraButton.addEventListener("click", async function () {
    try {
        if (!navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia) {
            alert("Camera is not supported by this browser.");
            return;
        }

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: "environment"
            },
            audio: false
        });

        cameraVideo.srcObject = cameraStream;
        cameraContainer.style.display = "block";
    }
    catch (error) {
        console.error("Camera error:", error);
        alert("Cannot open camera. Please allow camera permission.");
    }
});

// CAPTURE PHOTO
captureButton.addEventListener("click", function () {
    if (!cameraStream) {
        alert("Camera is not running.");
        return;
    }

    const width = cameraVideo.videoWidth;
    const height = cameraVideo.videoHeight;

    if (width === 0 || height === 0) {
        alert("Camera is not ready. Please wait.");
        return;
    }

    cameraCanvas.width = width;
    cameraCanvas.height = height;

    const context = cameraCanvas.getContext("2d");

    context.drawImage(
        cameraVideo,
        0,
        0,
        width,
        height
    );

    cameraCanvas.toBlob(function (blob) {
        if (!blob) {
            alert("Could not capture photo.");
            return;
        }

        selectedFile = new File(
            [blob],
            "camera-photo.jpg",
            {
                type: "image/jpeg"
            }
        );

        selectedVideo = null;

        const imageURL = URL.createObjectURL(selectedFile);

        previewImage.src = imageURL;
        previewImage.style.display = "block";
        previewText.style.display = "none";

        detectButton.disabled = false;
        detectVideoButton.disabled = true;

        resultCard.style.display = "none";
        videoResultCard.style.display = "none";
        errorMessage.style.display = "none";

        stopCamera();
    }, "image/jpeg", 0.9);
});

// CLOSE CAMERA
closeCameraButton.addEventListener("click", function () {
    stopCamera();
});

// STOP CAMERA
function stopCamera() {
    if (cameraStream) {
        cameraStream
            .getTracks()
            .forEach(function (track) {
                track.stop();
            });

        cameraStream = null;
    }

    cameraVideo.srcObject = null;
    cameraContainer.style.display = "none";
}

// IMAGE DETECTION
detectButton.addEventListener("click", async function () {
    if (!selectedFile) {
        alert("Please select or capture an image first.");
        return;
    }

    loading.style.display = "block";
    loadingText.textContent = "AI is analyzing the image...";
    errorMessage.style.display = "none";
    resultCard.style.display = "none";
    detectButton.disabled = true;

    const formData = new FormData();
    formData.append("image", selectedFile);

    try {
        const response = await fetch(
            API_URL + "/detect",
            {
                method: "POST",
                body: formData
            }
        );

        if (!response.ok) {
            throw new Error(
                "Flask server error: " + response.status
            );
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(
                data.error || "Detection failed"
            );
        }

        let resultURL = data.image_url;
        resultURL += "?t=" + Date.now();

        resultImage.src = resultURL;
        resultImage.style.display = "block";
        resultCard.style.display = "block";

        if (data.pothole_detected && data.detections) {
            let detectionHTML = "";

            data.detections.forEach(function (detection, index) {
                detectionHTML += `
                    <div class="result-box">
                        <h3>🚧 Pothole ${index + 1}</h3>
                        <p>
                            <strong>Class:</strong>
                            ${detection.class}
                        </p>
                        <p>
                            <strong>Confidence:</strong>
                            <span class="confidence">
                                ${detection.confidence}%
                            </span>
                        </p>
                    </div>
                `;
            });

            resultInfo.innerHTML = `
                <div class="result-box">
                    <h3>🚧 Potholes Detected!</h3>
                    <p>
                        <strong>Total Potholes:</strong>
                        ${data.detections.length}
                    </p>
                    <p>
                        <strong>Highest Confidence:</strong>
                        <span class="confidence">
                            ${data.confidence}%
                        </span>
                    </p>
                </div>
                ${detectionHTML}
            `;
        }
        else {
            resultInfo.innerHTML = `
                <div class="no-pothole">
                    ✅ No Pothole Detected
                    <p>
                        The YOLOv8 model did not detect
                        any potholes in this image.
                    </p>
                </div>
            `;
        }

        resultCard.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    }
    catch (error) {
        console.error("Image detection error:", error);

        errorMessage.style.display = "block";

        errorMessage.innerHTML = `
            ⚠️ <strong>Detection Error</strong>
            <br><br>
            ${error.message}
        `;
    }
    finally {
        loading.style.display = "none";
        detectButton.disabled = false;
    }
});

// VIDEO DETECTION
detectVideoButton.addEventListener("click", async function () {
    if (!selectedVideo) {
        alert("Please select a video first.");
        return;
    }

    console.log("Starting video detection...");

    loading.style.display = "block";
    loadingText.textContent =
        "AI is analyzing the video. Please wait...";

    errorMessage.style.display = "none";
    videoResultCard.style.display = "none";
    detectVideoButton.disabled = true;

    const formData = new FormData();
    formData.append("video", selectedVideo);

    try {
        console.log("Sending video to Flask...");

        const response = await fetch(
            API_URL + "/detect-video",
            {
                method: "POST",
                body: formData
            }
        );

        console.log("Flask status:", response.status);

        if (!response.ok) {
            const errorText = await response.text();
            console.error(errorText);

            throw new Error(
                "Flask server error: " + response.status
            );
        }

        const data = await response.json();

        console.log("Video detection result:", data);

        if (!data.success) {
            throw new Error(
                data.error || "Video detection failed"
            );
        }

        let videoURL = data.video_url;
        videoURL += "?t=" + Date.now();

        resultVideo.src = videoURL;
        resultVideo.preload = "auto";
        resultVideo.style.display = "block";
        resultVideo.load();

        videoResultCard.style.display = "block";

        resultVideo.play().catch(function () {
            console.log("Autoplay blocked by browser; user can press play manually.");
        });

        if (data.pothole_detected) {
            videoResultInfo.innerHTML = `
                <div class="result-box">
                    <h3>🚧 Potholes Detected!</h3>
                    <p>
                        <strong>Total Frame Detections:</strong>
                        ${data.total_detections}
                    </p>
                    <p>
                        <strong>Highest Confidence:</strong>
                        <span class="confidence">
                            ${data.confidence}%
                        </span>
                    </p>
                </div>
            `;
        }
        else {
            videoResultInfo.innerHTML = `
                <div class="no-pothole">
                    ✅ No Pothole Detected
                    <p>
                        No potholes were detected
                        in the video.
                    </p>
                </div>
            `;
        }

        videoResultCard.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    }
    catch (error) {
        console.error("Video detection error:", error);

        errorMessage.style.display = "block";

        errorMessage.innerHTML = `
            ⚠️ <strong>Video Detection Error</strong>
            <br><br>
            ${error.message}
            <br><br>
            Make sure Flask is running at:
            <br>
            <strong>http://127.0.0.1:5000</strong>
        `;
    }
    finally {
        loading.style.display = "none";
        detectVideoButton.disabled = false;
    }
});