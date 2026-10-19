sprite = Sprite('Tobi')

import cv2
import numpy as np
import socket
import threading
import time

# -------------------- MOTOR SETUP --------------------
mini = QuarkyMiniExpansion()
mini.miniinitialise()
mini.stoprobot()

POWER = 65
MOVE_TIME = 1.0
stop_event = threading.Event()

# -------------------- SERVO SETUP --------------------
# Servo connected to Intellio port S1
expansion = QuarkyIntellio()
SERVO_PORT = 'S1'

# Default servo position: 0 degrees
expansion.moveservointime(SERVO_PORT, 0, 1)


# -------------------- Q KEY STOP --------------------
def check_quit():
    if cv2.waitKey(1) & 0xFF == ord('q'):
        print("Q pressed. Terminating session...")
        stop_event.set()
        mini.stoprobot()
        return True

    return stop_event.is_set()


def wait_with_q(duration):
    start_time = time.time()

    while time.time() - start_time < duration:
        if check_quit():
            return False

        time.sleep(0.02)

    return not stop_event.is_set()


# -------------------- MOTOR MOVEMENTS --------------------
def turn_right():
    if stop_event.is_set():
        return

    print("Turning right for 1 second.")
    mini.runmotor("R", "1", POWER)

    completed = wait_with_q(1.0)
    mini.stoprobot()

    if not completed:
        return

    # After the initial right turn, move servo to 70 degrees
    print("Initial right turn completed. Moving servo to 70 degrees.")
    expansion.moveservointime(SERVO_PORT, 70, 1)


def turn_left():
    if stop_event.is_set():
        return

    print("Turning left for 1 second.")
    mini.runmotor("L", "2", POWER)

    wait_with_q(1.0)
    mini.stoprobot()


def move_backward(duration=1.0):
    if stop_event.is_set():
        return

    print(f"Moving backward for {duration} seconds.")

    mini.runmotor("L", "1", str(POWER))
    mini.runmotor("R", "2", str(POWER))

    wait_with_q(duration)
    mini.stoprobot()


def move_forward():
    if stop_event.is_set():
        return

    # 1. Move forward for 1 second
    print("Moving forward for 1 second.")

    mini.runmotor("L", "2", str(POWER))
    mini.runmotor("R", "1", str(POWER))

    completed = wait_with_q(1.0)
    mini.stoprobot()

    if not completed:
        return

    # 2. Move servo to 30 degrees
    print("Forward movement completed. Moving servo to 30 degrees.")
    expansion.moveservointime(SERVO_PORT, 30, 1)

    if stop_event.is_set():
        return

    # 3. Move backward for 1.2 seconds
    move_backward(1.2)

    if stop_event.is_set():
        return

    # 4. Wait 1 second before the final right turn
    print("Backward movement completed. Waiting 1 second.")

    if not wait_with_q(1.0):
        return

    # 5. Turn right for 1 second
    print("Turning right for 1 second.")
    mini.runmotor("R", "1", POWER)

    completed = wait_with_q(1.0)
    mini.stoprobot()

    if not completed:
        return

    # 6. After the final right turn, move servo to 70 degrees
    print("Final right turn completed. Moving servo to 70 degrees.")
    expansion.moveservointime(SERVO_PORT, 70, 1)

    if stop_event.is_set():
        return

    # 7. Move backward for 1 second
    move_backward(1.0)


# -------------------- CAMERA RECEIVER --------------------
class IntellioCamera:
    def __init__(self, host="127.0.0.1", port=6000):
        self.latest_frame = None
        self.lock = threading.Lock()
        self.running = True

        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        self.sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_RCVBUF,
            4 * 1024 * 1024
        )

        self.sock.bind((host, port))
        self.sock.settimeout(1.0)

        self.thread = threading.Thread(
            target=self.receive_frames,
            daemon=True
        )
        self.thread.start()

    def receive_frames(self):
        expected_size = 0
        frame_buffer = bytearray()

        while self.running:
            try:
                packet, _ = self.sock.recvfrom(65507)

            except socket.timeout:
                continue

            except OSError:
                break

            if packet.startswith(b"SIZE:"):
                try:
                    expected_size = int(
                        packet.split(b":", 1)[1]
                    )

                    if expected_size <= 0 or expected_size > 2000000:
                        expected_size = 0

                    frame_buffer = bytearray()

                except ValueError:
                    expected_size = 0
                    frame_buffer = bytearray()

                continue

            if expected_size > 0:
                if len(frame_buffer) + len(packet) > expected_size:
                    expected_size = 0
                    frame_buffer = bytearray()
                    continue

                frame_buffer.extend(packet)

                if len(frame_buffer) == expected_size:
                    encoded = np.frombuffer(
                        bytes(frame_buffer),
                        dtype=np.uint8
                    )

                    frame = cv2.imdecode(
                        encoded,
                        cv2.IMREAD_COLOR
                    )

                    if frame is not None:
                        with self.lock:
                            self.latest_frame = frame

                    expected_size = 0
                    frame_buffer = bytearray()

    def get_frame(self):
        with self.lock:
            if self.latest_frame is None:
                return None

            return self.latest_frame.copy()

    def close(self):
        self.running = False
        self.sock.close()


# -------------------- APRILTAG DETECTOR --------------------
dictionary = cv2.aruco.getPredefinedDictionary(
    cv2.aruco.DICT_APRILTAG_16h5
)

parameters = cv2.aruco.DetectorParameters()
parameters.minMarkerPerimeterRate = 0.01
parameters.cornerRefinementMethod = (
    cv2.aruco.CORNER_REFINE_SUBPIX
)

detector = cv2.aruco.ArucoDetector(
    dictionary,
    parameters
)

clahe = cv2.createCLAHE(
    clipLimit=2.0,
    tileGridSize=(8, 8)
)


def detect_tags(frame):
    # Preserve mirrored-frame detection
    detection_frame = cv2.flip(frame, 1)

    gray = cv2.cvtColor(
        detection_frame,
        cv2.COLOR_BGR2GRAY
    )

    gray = clahe.apply(gray)

    corners, ids, _ = detector.detectMarkers(gray)

    tag_ids = (
        set()
        if ids is None
        else {int(tag_id) for tag_id in ids.flatten()}
    )

    return corners, ids, tag_ids


# -------------------- MAIN TASK --------------------
camera = None

try:
    cv2.namedWindow("AprilTag Scanner")

    camera = IntellioCamera()

    print("Press Q in the scanner window to stop.")
    print("Starting initial right turn...")

    turn_right()

    if not stop_event.is_set():
        print("Scanning for AprilTags...")
        detected_ids = set()

        while not stop_event.is_set() and not detected_ids:
            frame = camera.get_frame()

            if frame is None:
                waiting = np.zeros(
                    (480, 640, 3),
                    dtype=np.uint8
                )

                cv2.putText(
                    waiting,
                    "Waiting for camera frames...",
                    (35, 240),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )

                cv2.imshow("AprilTag Scanner", waiting)

            else:
                corners, ids, detected_ids = detect_tags(frame)

                if ids is not None:
                    for i, tag_id in enumerate(ids.flatten()):
                        points = corners[i][0].copy()

                        points[:, 0] = (
                            frame.shape[1] - 1 - points[:, 0]
                        )

                        points = points.astype(np.int32)

                        cv2.polylines(
                            frame,
                            [points],
                            True,
                            (0, 255, 0),
                            3
                        )

                        cv2.putText(
                            frame,
                            "ID: " + str(int(tag_id)),
                            (
                                max(5, int(points[:, 0].mean()) - 40),
                                max(25, int(points[:, 1].mean()) - 15)
                            ),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7,
                            (0, 255, 0),
                            2
                        )

                cv2.putText(
                    frame,
                    "Scanning - press Q to stop",
                    (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 255, 0),
                    2
                )

                cv2.imshow("AprilTag Scanner", frame)

            if check_quit():
                break

            time.sleep(0.02)

        # -------------------- TAG-BASED MOVEMENT --------------------
        if not stop_event.is_set() and detected_ids:
            print("Detected AprilTag IDs:", sorted(detected_ids))

            if 6 in detected_ids:
                print("Organic tag ID 6 detected.")
                move_forward()

            else:
                print("ID 6 not found: turning left twice.")

                turn_left()

                if not stop_event.is_set():
                    if wait_with_q(1.0):
                        turn_left()

finally:
    stop_event.set()
    mini.stoprobot()

    if camera is not None:
        camera.close()

    cv2.destroyAllWindows()
    print("Session terminated.")
