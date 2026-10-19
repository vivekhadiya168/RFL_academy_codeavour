sprite = Sprite('Stage')

sprite = Sprite('Stage')

import cv2
import numpy as np
import socket
import threading
import time

# ==========================================
# 1. INTELLIO SPEAKER AND MOTOR SETUP
# ==========================================

intellio = QuarkyIntellio()
intellio.setspeakervolume(80)

tobi = Sprite("Tobi")


MOTOR_SPEED = 40

# Separate motor controller
mini = QuarkyMiniExpansion()
mini.miniinitialise()
mini.stoprobot()

motor_busy = False
motor_lock = threading.Lock()
stop_event = threading.Event()

# ==========================================
# 2. APRILTAG INFORMATION
# ==========================================

TAG_INFO = {
    1: ("Residential Zone", "Residential zone marker."),
    2: ("Business Zone", "Business zone marker."),
    3: ("Residential Zone", "Residential zone marker."),
    4: ("Business Zone", "Business zone marker."),
    5: ("Inorganic", "This is inorganic waste."),
    6: ("Organic", "This is organic waste."),
    7: ("Home Point 1", "This is home point one."),
    8: ("Home Point 2", "This is home point two.")
}

# ==========================================
# 3. POWER-DEMAND RULES
# ==========================================

def get_power_demand_message(detected_ids):
    ids = set(detected_ids) & {1, 2, 3, 4}

    # Individual tags
    if ids == {1}:
        return "Residential zone."

    if ids == {2}:
        return "Business zone has higher power demand."

    # Residential demand
    if ids in ({1, 3}, {1, 2, 3}):
        return "Residential zone has higher power demand."

    # Residential supply
    if ids == {1, 3, 4}:
        return "Residential zone has higher power supply."

    # Business demand
    if ids in ({2, 4}, {2, 3, 4}, {1, 2, 4}):
        return "Business zone has higher power demand."

    return None


# ==========================================
# 4. MOTOR CONTROL
# ==========================================

def motor_sequence(direction, duration):
    global motor_busy

    try:
        print("Waiting 1 second before movement.")

        # Q can cancel the delay.
        if stop_event.wait(1):
            return

        if stop_event.is_set():
            return

        if direction == "FORWARD":
            print("Moving FORWARD for", duration, "seconds.")

            mini.runmotor("L", "2", str(MOTOR_SPEED))
            mini.runmotor("R", "1", str(MOTOR_SPEED))

        elif direction == "BACKWARD":
            print("Moving BACKWARD for", duration, "seconds.")

            mini.runmotor("L", "1", str(MOTOR_SPEED))
            mini.runmotor("R", "2", str(MOTOR_SPEED))

        # Stop early if Q is pressed.
        stop_event.wait(duration)

    except Exception as error:
        print("Motor error:", error)

    finally:
        # Always stop the SAME object that started the motors.
        try:
            mini.stoprobot()
            print("Motors stopped.")
        except Exception as error:
            print("Motor stop error:", error)

        with motor_lock:
            motor_busy = False


def start_motor(direction, duration):
    global motor_busy

    with motor_lock:
        if motor_busy or stop_event.is_set():
            return False

        motor_busy = True

    threading.Thread(
        target=motor_sequence,
        args=(direction, duration),
        daemon=True
    ).start()

    return True


def emergency_stop():
    stop_event.set()

    try:
        mini.stoprobot()
        print("EMERGENCY STOP: Motors stopped.")
    except Exception as error:
        print("Emergency stop error:", error)


# ==========================================
# 5. VOICE ANNOUNCEMENTS
# ==========================================

def announce(message):
    print("ANNOUNCEMENT:", message)

    try:
        tobi.say(message)
    except Exception as error:
        print("Tobi message error:", error)

    try:
        intellio.speakTTS(message)
    except Exception as error:
        print("Intellio speaker error:", error)


def announce_tag(tag_id):
    if tag_id not in TAG_INFO:
        return

    category, description = TAG_INFO[tag_id]

    message = (
        "AprilTag ID " + str(tag_id) +
        ". " + category + ". " + description
    )

    announce(message)


# ==========================================
# 6. CAMERA FRAME RECEIVER
# ==========================================

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
                packet, address = self.sock.recvfrom(65507)

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
                        continue

                    frame_buffer = bytearray()

                except ValueError:
                    expected_size = 0
                    frame_buffer = bytearray()

                continue

            if expected_size > 0:
                remaining = expected_size - len(frame_buffer)

                if len(packet) > remaining:
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


# ==========================================
# 7. APRILTAG DETECTOR
# ==========================================

class AprilTagDetector:
    def __init__(self):
        self.dictionary = cv2.aruco.getPredefinedDictionary(
            cv2.aruco.DICT_APRILTAG_16h5
        )

        self.parameters = cv2.aruco.DetectorParameters()
        self.parameters.minMarkerPerimeterRate = 0.01

        self.parameters.cornerRefinementMethod = (
            cv2.aruco.CORNER_REFINE_SUBPIX
        )

        self.detector = cv2.aruco.ArucoDetector(
            self.dictionary,
            self.parameters
        )

        self.clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8)
        )

    def scan(self, original_frame):
        detection_frame = cv2.flip(original_frame, 1)

        gray = cv2.cvtColor(
            detection_frame,
            cv2.COLOR_BGR2GRAY
        )

        gray = self.clahe.apply(gray)

        corners, ids, rejected = self.detector.detectMarkers(
            gray
        )

        return corners, ids, len(rejected)


# ==========================================
# 8. MAIN PROGRAM
# ==========================================

camera = None

# Once a movement-triggering event occurs,
# no further tags will trigger another action.
session_completed = False

try:
    print("Starting camera receiver...")

    camera = IntellioCamera(
        host="127.0.0.1",
        port=6000
    )

    tag_detector = AprilTagDetector()

    previous_ids = set()
    last_power_message = None

    print("Scanner started.")
    print("Press Q in the camera window to stop immediately.")

    while True:

        # --------------------------------------
        # AFTER A MOVEMENT EVENT
        # Wait for movement to finish, or Q.
        # --------------------------------------

        if session_completed:
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                emergency_stop()
                break

            with motor_lock:
                still_moving = motor_busy

            if not still_moving:
                print("One-time task completed. Session terminated.")
                break

            time.sleep(0.02)
            continue

        original_frame = camera.get_frame()

        # Display a waiting screen before first frame.
        if original_frame is None:
            waiting_frame = np.zeros(
                (480, 640, 3),
                dtype=np.uint8
            )

            cv2.putText(
                waiting_frame,
                "Waiting for camera frames...",
                (35, 240),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )

            cv2.imshow(
                "Intellio AprilTag Scanner",
                waiting_frame
            )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                emergency_stop()
                break

            time.sleep(0.02)
            continue

        corners, ids, rejected_count = tag_detector.scan(
            original_frame
        )

        current_ids = set()

        # --------------------------------------
        # DRAW DETECTED APRILTAGS
        # --------------------------------------

        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                tag_id = int(marker_id)
                current_ids.add(tag_id)

                points = corners[i][0].copy()

                # Convert flipped coordinates back.
                points[:, 0] = (
                    original_frame.shape[1] - 1 - points[:, 0]
                )

                points = points.astype(np.int32)

                cv2.polylines(
                    original_frame,
                    [points],
                    True,
                    (0, 255, 0),
                    3
                )

                center_x = int(points[:, 0].mean())
                center_y = int(points[:, 1].mean())

                category = TAG_INFO.get(
                    tag_id,
                    ("Unknown", "")
                )[0]

                label = "ID: " + str(tag_id) + " - " + category

                cv2.putText(
                    original_frame,
                    label,
                    (
                        max(5, center_x - 80),
                        max(25, center_y - 15)
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )

        # --------------------------------------
        # POWER-DEMAND EVENT
        # --------------------------------------

        power_message = get_power_demand_message(current_ids)

        if power_message is not None:
            if power_message != last_power_message:
                announce(power_message)

                direction = None
                duration = 0

                if power_message == (
                    "Residential zone has higher power demand."
                ):
                    direction = "FORWARD"
                    duration = 3

                elif power_message == (
                    "Business zone has higher power demand."
                ):
                    direction = "BACKWARD"
                    duration = 2

                if direction is not None:
                    if start_motor(direction, duration):
                        session_completed = True

                last_power_message = power_message

        else:
            last_power_message = None

        # --------------------------------------
        # WASTE TAG EVENT
        # ID 6 = ORGANIC: FORWARD 3 SECONDS
        # ID 5 = INORGANIC: BACKWARD 2 SECONDS
        # --------------------------------------

        if not session_completed:
            new_ids = current_ids - previous_ids

            if 6 in new_ids:
                announce_tag(6)

                if start_motor("FORWARD", 3):
                    session_completed = True

            elif 5 in new_ids:
                announce_tag(5)

                if start_motor("BACKWARD", 2):
                    session_completed = True

            # Announce home-point tags without motor movement.
            if not session_completed:
                for tag_id in sorted(new_ids):
                    if tag_id in (7, 8):
                        announce_tag(tag_id)

        previous_ids = current_ids

        # --------------------------------------
        # CAMERA DISPLAY
        # --------------------------------------

        cv2.putText(
            original_frame,
            "APRILTAG MONITOR - Q TO EXIT",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )

        cv2.imshow(
            "Intellio AprilTag Scanner",
            original_frame
        )

        if cv2.waitKey(1) & 0xFF == ord("q"):
            emergency_stop()
            break

except Exception as error:
    print("Program error:", error)

finally:
    # Always stop motors when the program exits.
    emergency_stop()

    if camera is not None:
        camera.close()

    cv2.destroyAllWindows()

    print("Scanner stopped.")
