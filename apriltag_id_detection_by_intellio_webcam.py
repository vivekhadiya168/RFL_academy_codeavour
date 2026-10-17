sprite = Sprite('Stage')

import cv2
import numpy as np
import socket
import threading
import time

# ============== CONFIGURATION ==============
HOST = "127.0.0.1"
PORT = 6000

MAX_IMAGE_SIZE = 2_000_000
TRANSFER_TIMEOUT = 1.0
STALE_SECONDS = 2.0


# ============== INTELLIO CAMERA RECEIVER ==============
class IntellioCamera:

    def __init__(self):
        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        self.sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        self.sock.bind((HOST, PORT))
        self.sock.settimeout(0.25)

        self.lock = threading.Lock()
        self.running = True
        self.frame = None
        self.frame_time = 0
        self.frame_number = 0

        self.thread = threading.Thread(
            target=self.receive_frames,
            daemon=True
        )
        self.thread.start()

        print("Intellio camera receiver started.")


    def receive_frames(self):
        expected_size = 0
        image_data = bytearray()
        transfer_start = 0
        sender = None

        while self.running:
            try:
                packet, address = self.sock.recvfrom(65535)

            except socket.timeout:
                if (
                    expected_size > 0
                    and time.monotonic() - transfer_start
                    > TRANSFER_TIMEOUT
                ):
                    expected_size = 0
                    image_data.clear()
                    sender = None
                continue

            except OSError:
                break

            now = time.monotonic()

            if packet.startswith(b"SIZE:"):
                try:
                    size = int(packet[5:].strip())
                except ValueError:
                    size = 0

                expected_size = (
                    size if 0 < size <= MAX_IMAGE_SIZE else 0
                )

                image_data.clear()
                transfer_start = now
                sender = address if expected_size else None
                continue

            if expected_size == 0 or address != sender:
                continue

            if (
                now - transfer_start > TRANSFER_TIMEOUT
                or len(image_data) + len(packet) > expected_size
            ):
                expected_size = 0
                image_data.clear()
                sender = None
                continue

            image_data.extend(packet)

            if len(image_data) == expected_size:
                encoded = np.frombuffer(
                    bytes(image_data),
                    dtype=np.uint8
                )

                decoded = cv2.imdecode(
                    encoded,
                    cv2.IMREAD_COLOR
                )

                if decoded is not None:
                    with self.lock:
                        self.frame = decoded
                        self.frame_time = now
                        self.frame_number += 1

                expected_size = 0
                image_data.clear()
                sender = None


    def get_frame(self, previous_number):
        with self.lock:
            if (
                self.frame is None
                or self.frame_number == previous_number
                or time.monotonic() - self.frame_time > STALE_SECONDS
            ):
                return None, previous_number

            return self.frame.copy(), self.frame_number


    def close(self):
        self.running = False

        try:
            self.sock.close()
        except Exception:
            pass

        self.thread.join(timeout=1.0)


# ============== APRILTAG DETECTOR ==============
class AprilTagDetector:

    def __init__(self):
        aruco = cv2.aruco

        dictionary = aruco.getPredefinedDictionary(
            aruco.DICT_APRILTAG_16h5
        )

        parameters = aruco.DetectorParameters()
        parameters.minMarkerPerimeterRate = 0.01
        parameters.cornerRefinementMethod = (
            aruco.CORNER_REFINE_SUBPIX
        )

        self.detector = aruco.ArucoDetector(
            dictionary,
            parameters
        )

        self.clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8)
        )

        print("AprilTag 16h5 detector initialized.")


    def scan(self, original_frame):
        # Keep the original frame unchanged for display.
        # Create a separate copy for internal detection.
        detection_frame = cv2.flip(
            original_frame,
            1
        )

        gray = cv2.cvtColor(
            detection_frame,
            cv2.COLOR_BGR2GRAY
        )

        # First attempt: mirrored copy.
        corners, ids, rejected = (
            self.detector.detectMarkers(gray)
        )

        rejected_count = len(rejected)

        # Second attempt: contrast-enhanced mirrored copy.
        if ids is None or len(ids) == 0:
            enhanced = self.clahe.apply(gray)

            corners, ids, rejected = (
                self.detector.detectMarkers(enhanced)
            )

            rejected_count = max(
                rejected_count,
                len(rejected)
            )

        return ids, corners, rejected_count


# ============== ORIGINAL CAMERA DISPLAY ==============
def draw_results(original_frame, ids, corners, rejected_count):
    # Never flip the image used for display.
    output = original_frame.copy()

    if ids is not None and len(ids) > 0:

        for marker_id, corner in zip(
            ids.flatten(),
            corners
        ):
            marker_id = int(marker_id)

            # Detector coordinates belong to the mirrored frame.
            # Convert X coordinates back to original-frame coordinates.
            points = corner.reshape(4, 2).copy()

            points[:, 0] = (
                original_frame.shape[1] - 1 - points[:, 0]
            )

            points = points.astype(np.int32)

            center = points.mean(axis=0).astype(int)

            cv2.polylines(
                output,
                [points],
                True,
                (0, 255, 0),
                2
            )

            cv2.putText(
                output,
                "AprilTag ID: " + str(marker_id),
                (
                    max(5, int(center[0]) - 90),
                    max(30, int(center[1]) - 15)
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

    else:
        cv2.putText(
            output,
            "No AprilTag detected",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2
        )

        cv2.putText(
            output,
            "Rejected: " + str(rejected_count),
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 165, 255),
            2
        )

    cv2.putText(
        output,
        "Original Camera View",
        (10, output.shape[0] - 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 0),
        2
    )

    return output


# ============== MAIN PROGRAM ==============
def main():
    camera = None

    try:
        detector = AprilTagDetector()
        camera = IntellioCamera()

        last_number = -1
        previous_ids = set()
        last_status = time.monotonic()

        print("Scanner started.")
        print("Preview: original camera image.")
        print("Detection: internally mirrored image.")
        print("Press Q to quit.")

        while True:
            frame, number = camera.get_frame(last_number)

            if frame is None:
                time.sleep(0.02)
                continue

            last_number = number

            ids, corners, rejected_count = detector.scan(frame)

            current_ids = set()

            if ids is not None:
                current_ids = {
                    int(marker_id)
                    for marker_id in ids.flatten()
                }

            if current_ids != previous_ids:
                if current_ids:
                    for marker_id in sorted(current_ids):
                        print(
                            "APRILTAG DETECTED - ID:",
                            marker_id
                        )
                else:
                    print("No AprilTag detected.")

                previous_ids = current_ids

            # Display the original frame, not the detection copy.
            output = draw_results(
                frame,
                ids,
                corners,
                rejected_count
            )

            if time.monotonic() - last_status >= 3:
                print(
                    "Frame:", number,
                    "| IDs:", sorted(current_ids),
                    "| Rejected:", rejected_count
                )
                last_status = time.monotonic()

            cv2.imshow(
                "Original Intellio Camera - AprilTag Scanner",
                output
            )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except Exception as error:
        print("Scanner error:", error)

    finally:
        if camera is not None:
            camera.close()

        cv2.destroyAllWindows()
        print("Scanner stopped.")


main()
