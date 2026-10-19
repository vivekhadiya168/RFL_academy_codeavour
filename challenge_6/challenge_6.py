
sprite = Sprite('Tobi')

import cv2
import numpy as np
import socket
import threading
import time

# ==========================================
# 1. SETTINGS
# ==========================================

POWER = 60
TURN_TIME = 1.0
INITIAL_FORWARD_TIME = 0
RETURN_TIME = 1.0
WAIT_TIME = 1.0

stop_event = threading.Event()
motor_busy = False
motor_lock = threading.Lock()

# ==========================================
# 2. HARDWARE SETUP
# ==========================================

intellio = QuarkyIntellio()
intellio.setspeakervolume(80)

mini = QuarkyMiniExpansion()
mini.miniinitialise()
mini.stoprobot()

# ==========================================
# 3. APRILTAG INFORMATION
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
# 4. MOTOR FUNCTIONS
# ==========================================

def stop_motors():
    mini.stoprobot()


def turn_left():
    if stop_event.is_set():
        return False

    print("Turning LEFT.")
    mini.runmotor("L", '1', POWER)

    completed = not stop_event.wait(TURN_TIME)
    stop_motors()
    return completed


def move_forward(duration):
    if stop_event.is_set():
        return False

    print("Moving FORWARD for", duration, "seconds.")

    mini.runmotor("L", "1", str(POWER))
    mini.runmotor("R", "1", str(POWER))

    completed = not stop_event.wait(duration)
    stop_motors()
    return completed


def turn_right():
    if stop_event.is_set():
        return False

    print("Turning RIGHT.")
    mini.runmotor("R", "1", POWER)

    completed = not stop_event.wait(TURN_TIME)
    stop_motors()
    return completed


def return_with_motor(motor_name, direction):
    if stop_event.is_set():
        return False

    print(
        "Returning using motor",
        motor_name,
        "direction",
        direction,
        "for",
        RETURN_TIME,
        "seconds."
    )

    mini.runmotor(motor_name, direction, str(POWER))

    completed = not stop_event.wait(RETURN_TIME)
    stop_motors()
    return completed


# ==========================================
# 5. SIX POWER-DEMAND COMBINATIONS
# ==========================================

def get_power_demand(detected_ids):
    ids = set(detected_ids) & {1, 2, 3, 4}

    # Residential zone
    if ids in ({1, 3}, {1, 2, 3}):
        return "RESIDENTIAL"

    # Business zone
    if ids in ({2, 4}, {2, 3, 4}, {1, 2, 4}):
        return "BUSINESS"

    # Residential higher power supply
    if ids == {1, 3, 4}:
        return "RESIDENTIAL"

    # Single-tag conditions from the original rules
    if ids == {1}:
        return "RESIDENTIAL"

    if ids == {2}:
        return "BUSINESS"

    return None


# ==========================================
# 6. VOICE ANNOUNCEMENTS
# ==========================================

def announce(message):
    print("ANNOUNCEMENT:", message)

    try:
        Sprite("Tobi").say(message)
    except Exception as error:
        print("Tobi announcement error:", error)

    try:
        intellio.speakTTS(message)
    except Exception as error:
        print("Speaker announcement error:", error)


def announce_tag(tag_id):
    if tag_id not in TAG_INFO:
        return

    name, description = TAG_INFO[tag_id]

    announce(
        "AprilTag ID " + str(tag_id) +
        ". " + name + ". " + description
    )


# ==========================================
# 7. ACTUAL MOVEMENT SEQUENCE
# ==========================================

def run_robot_sequence(demand):
    global motor_busy

    try:
        # Step 1: Wait 1 second after identifying the zone
        print("Power-demand condition identified.")
        print("Waiting 1 second.")

        if stop_event.wait(WAIT_TIME):
            return

        # Step 2: Initial left turn
        if not turn_left():
            return

        # Step 3: Move forward for 0.2 seconds
        if not move_forward(INITIAL_FORWARD_TIME):
            return

        # Step 4: Residential zone
        if demand == "RESIDENTIAL":

            print("Residential zone needs higher power supply.")
            announce("Residential zone needs higher power supply.")

            # Turn left one time
            if not turn_left():
                return

            # Return using motor L, direction 2, for 1 second
            if not return_with_motor("L", "2"):
                return

        # Step 5: Business zone
        elif demand == "BUSINESS":

            print("Business zone needs higher power supply.")
            announce("Business zone needs higher power supply.")

            # Turn right one time
            if not turn_right():
                return

            # Return using motor R, direction 2, for 1 second
            if not return_with_motor("R", "2"):
                return

    except Exception as error:
        print("Movement error:", error)

    finally:
        stop_motors()

        with motor_lock:
            motor_busy = False


def start_robot_sequence(demand):
    global motor_busy

    with motor_lock:
        if motor_busy or stop_event.is_set():
            return False

        motor_busy = True

    threading.Thread(
        target=run_robot_sequence,
        args=(demand,),
        daemon=True
    ).start()

    return True


# ==========================================
# 8. CAMERA RECEIVER
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

                    if not 0 < expected_size <= 2000000:
                        expected_size = 0
                        frame_buffer = bytearray()
                        continue

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


# ==========================================
# 9. APRILTAG DETECTOR
# ==========================================

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
    detection_frame = cv2.flip(frame, 1)

    gray = cv2.cvtColor(
        detection_frame,
        cv2.COLOR_BGR2GRAY
    )

    gray = clahe.apply(gray)

    corners, ids, _ = detector.detectMarkers(gray)

    detected_ids = (
        set()
        if ids is None
        else {int(tag_id) for tag_id in ids.flatten()}
    )

    return corners, ids, detected_ids


# ==========================================
# 10. MAIN PROGRAM
# ==========================================

camera = None
task_started = False

try:
    camera = IntellioCamera()
    cv2.namedWindow("AprilTag Scanner")

    previous_ids = set()

    print("Scanning AprilTags to identify power demand.")
    print("Press Q in the scanner window to stop.")

    while not stop_event.is_set():

        # Wait for the one-time movement sequence to finish
        if task_started:
            with motor_lock:
                still_moving = motor_busy

            if not still_moving:
                print("Movement sequence completed.")
                break

            if cv2.waitKey(1) & 0xFF == ord("q"):
                stop_event.set()
                stop_motors()
                break

            time.sleep(0.02)
            continue

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

            if cv2.waitKey(1) & 0xFF == ord("q"):
                stop_event.set()
                stop_motors()
                break

            time.sleep(0.02)
            continue

        corners, ids, current_ids = detect_tags(frame)

        # Display tag ID and name
        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                tag_id = int(marker_id)

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

                name = TAG_INFO.get(
                    tag_id,
                    ("Unknown", "")
                )[0]

                cv2.putText(
                    frame,
                    "ID: " + str(tag_id) + " - " + name,
                    (
                        max(5, int(points[:, 0].mean()) - 80),
                        max(25, int(points[:, 1].mean()) - 15)
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )

        # Announce each newly detected tag
        new_ids = current_ids - previous_ids

        for tag_id in sorted(new_ids):
            if tag_id in TAG_INFO:
                announce_tag(tag_id)

        # Determine demand from the complete set of visible IDs
        demand = get_power_demand(current_ids)

        # Start movement ONLY after a demand condition is identified
        if demand is not None and not task_started:

            print("Detected IDs:", sorted(current_ids))
            print("Selected power-demand zone:", demand)

            if start_robot_sequence(demand):
                task_started = True

        previous_ids = current_ids

        cv2.putText(
            frame,
            "APRILTAG MONITOR - Q TO EXIT",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2
        )

        cv2.imshow("AprilTag Scanner", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            stop_event.set()
            stop_motors()
            break

        time.sleep(0.02)

except Exception as error:
    print("Program error:", error)

finally:
    stop_event.set()
    stop_motors()

    if camera is not None:
        camera.close()

    cv2.destroyAllWindows()
    print("Session terminated.")
