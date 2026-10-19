
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

mini = QuarkyMiniExpansion()
mini.miniinitialise()
mini.stoprobot()

motor_busy = False
motor_lock = threading.Lock()
stop_event = threading.Event()
session_completed = False

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

    if ids == {1}:
        return "Residential zone."

    if ids == {2}:
        return "Business zone has higher power demand."

    if ids in ({1, 3}, {1, 2, 3}):
        return "Residential zone has higher power demand."

    if ids == {1, 3, 4}:
        return "Residential zone has higher power supply."

    if ids in ({2, 4}, {2, 3, 4}, {1, 2, 4}):
        return "Business zone has higher power demand."

    return None


# ==========================================
# 4. MOTOR MOVEMENT
# ==========================================

def motor_sequence(action, duration):
    global motor_busy

    try:
        print("Waiting 1 second before movement...")
        if stop_event.wait(1) or stop_event.is_set():
            return

        if action == "LEFT":
            print("Turning left: M2, power 60, for 1 second.")
            mini.runmotor("L", "2", 60)
            if stop_event.wait(duration):
                return

        elif action == "RIGHT":
            print("Turning right: M1, power 60, for 1 second.")
            mini.runmotor("R", "1", 60)
            if stop_event.wait(duration):
                return

        elif action == "FORWARD":
            print("Moving forward for", duration, "second(s).")
            mini.runmotor("L", "2", str(MOTOR_SPEED))
            mini.runmotor("R", "1", str(MOTOR_SPEED))
            if stop_event.wait(duration):
                return

        elif action == "BACKWARD":
            print("Moving backward for", duration, "second(s).")
            mini.runmotor("L", "1", str(MOTOR_SPEED))
            mini.runmotor("R", "2", str(MOTOR_SPEED))
            if stop_event.wait(duration):
                return

    except Exception as error:
        print("Motor error:", error)

    finally:
        try:
            mini.stoprobot()
            print("Motors stopped.")
        except Exception as error:
            print("Motor stop error:", error)

        with motor_lock:
            motor_busy = False


def start_motor(action, duration):
    global motor_busy

    with motor_lock:
        if motor_busy or stop_event.is_set():
            return False

        motor_busy = True

    threading.Thread(
        target=motor_sequence,
        args=(action, duration),
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
        print("Tobi error:", error)

    try:
        intellio.speakTTS(message)
    except Exception as error:
        print("Speaker error:", error)


def announce_tag(tag_id):
    if tag_id not in TAG_INFO:
        return

    category, description = TAG_INFO[tag_id]

    announce(
        "AprilTag ID " + str(tag_id) +
        ". " + category + ". " + description
    )


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
# 8. MAIN PROGRAM + STARTUP NAVIGATION
# ==========================================

camera = None


def run_motor_once(port, direction, power, duration):
    """Run one motor command, then stop both motors safely."""
    if stop_event.is_set():
        return
    try:
        mini.runmotor(port, direction, power)
        if stop_event.wait(duration):
            return
    finally:
        mini.stoprobot()


def startup_navigation(camera, tag_detector):
    """Turn left, then scan until any AprilTag is detected."""
    global session_completed

    print("STARTUP: Turning left with M2 at power 60 for 1 second.")
    run_motor_once("L", "2", 60, 1)
    if stop_event.is_set():
        return set()

    print("STARTUP: Scanning until any AprilTag is detected...")
    startup_ids = set()

    while not stop_event.is_set():
        frame = camera.get_frame()

        if frame is None:
            waiting = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(waiting, "Waiting for camera frames...", (35, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Intellio AprilTag Scanner", waiting)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                emergency_stop()
                return set()
            time.sleep(0.02)
            continue

        corners, ids, _ = tag_detector.scan(frame)
        detected_ids = set() if ids is None else {int(x) for x in ids.flatten()}

        # Show the startup scan with detected tag IDs.
        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                points = corners[i][0].copy()
                points[:, 0] = frame.shape[1] - 1 - points[:, 0]
                points = points.astype(np.int32)
                cv2.polylines(frame, [points], True, (0, 255, 0), 3)
                center_x = int(points[:, 0].mean())
                center_y = int(points[:, 1].mean())
                cv2.putText(frame, "ID: " + str(int(marker_id)),
                            (max(5, center_x - 50), max(25, center_y - 15)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.putText(frame, "STARTUP SCAN - Q TO EXIT", (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.imshow("Intellio AprilTag Scanner", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            emergency_stop()
            return set()

        # Keep scanning until at least one AprilTag of any ID appears.
        if detected_ids:
            startup_ids = detected_ids
            break

        time.sleep(0.02)

    if stop_event.is_set() or not startup_ids:
        return startup_ids

    print("Startup detected IDs:", sorted(startup_ids))

    if 6 in startup_ids:
        print("Organic tag ID 6 detected: moving forward for 1 second.")
        try:
            if not stop_event.is_set():
                mini.runmotor("L", "2", str(MOTOR_SPEED))
                mini.runmotor("R", "1", str(MOTOR_SPEED))
                stop_event.wait(1)
        finally:
            mini.stoprobot()

        # This startup task is a one-time task: terminate the session
        # after the forward movement instead of starting normal scanning.
        session_completed = True
        print("Organic-tag task completed. Terminating session.")
    else:
        print("Organic tag ID 6 not detected: turning right twice.")

        # Right turn 1: M1 for 1 second.
        run_motor_once("R", "1", 60, 1)
        if stop_event.is_set():
            return startup_ids

        # Stop for 1 second between the two right turns.
        if stop_event.wait(1):
            return startup_ids

        # Right turn 2: M1 again for 1 second.
        run_motor_once("R", "1", 60, 1)

    return startup_ids


try:
    print("Starting camera receiver...")

    camera = IntellioCamera(host="127.0.0.1", port=6000)
    tag_detector = AprilTagDetector()

    # Run the new startup navigation before normal tag processing.
    startup_ids = startup_navigation(camera, tag_detector)
    if stop_event.is_set():
        raise KeyboardInterrupt("Stopped by user")

    # Prevent the startup-detected tags from immediately retriggering
    # the waste-tag event just because they remain in view.
    previous_ids = set(startup_ids)

    if session_completed:
        print("Session completed after the one-time organic-tag movement.")
    else:
        print("Startup navigation finished. Normal AprilTag scanning started. Press Q to stop.")

    while not session_completed and not stop_event.is_set():
        original_frame = camera.get_frame()

        if original_frame is None:
            waiting_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(waiting_frame, "Waiting for camera frames...", (35, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Intellio AprilTag Scanner", waiting_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                emergency_stop()
                break
            time.sleep(0.02)
            continue

        corners, ids, rejected_count = tag_detector.scan(original_frame)
        current_ids = set()

        if ids is not None:
            for i, marker_id in enumerate(ids.flatten()):
                tag_id = int(marker_id)
                current_ids.add(tag_id)

                points = corners[i][0].copy()
                points[:, 0] = original_frame.shape[1] - 1 - points[:, 0]
                points = points.astype(np.int32)
                cv2.polylines(original_frame, [points], True, (0, 255, 0), 3)

                center_x = int(points[:, 0].mean())
                center_y = int(points[:, 1].mean())
                category = TAG_INFO.get(tag_id, ("Unknown", ""))[0]
                cv2.putText(original_frame, "ID: " + str(tag_id) + " - " + category,
                            (max(5, center_x - 80), max(25, center_y - 15)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        new_ids = current_ids - previous_ids
        power_message = get_power_demand_message(current_ids)

        if power_message is not None:
            # Announce once for this visible tag combination.
            if current_ids != previous_ids:
                announce(power_message)

            if power_message in (
                "Residential zone has higher power demand.",
                "Business zone has higher power demand."
            ):
                session_completed = start_motor("LEFT", 1)
            elif current_ids != previous_ids:
                # Existing single-tag/supply announcements do not move.
                session_completed = True

        elif 6 in new_ids:
            announce_tag(6)
            session_completed = start_motor("FORWARD", 3)

        elif 5 in new_ids:
            announce_tag(5)
            session_completed = start_motor("BACKWARD", 2)

        else:
            for tag_id in sorted(new_ids):
                if tag_id in (7, 8):
                    announce_tag(tag_id)

        previous_ids = current_ids

        cv2.putText(original_frame, "APRILTAG MONITOR - Q TO EXIT", (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.imshow("Intellio AprilTag Scanner", original_frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            emergency_stop()
            break

        if session_completed:
            while motor_busy and not stop_event.is_set():
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    emergency_stop()
                    break
                time.sleep(0.02)
            break

except KeyboardInterrupt:
    print("Program stopped by user.")
except Exception as error:
    print("Program error:", error)
finally:
    emergency_stop()
    if camera is not None:
        camera.close()
    cv2.destroyAllWindows()
    print("Session terminated.")
