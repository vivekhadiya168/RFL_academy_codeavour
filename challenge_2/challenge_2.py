sprite = Sprite('Stage')

import time

# Initialize Quarky Mini Expansion
mini = QuarkyMiniExpansion()
mini.miniinitialise()
mini.stoprobot()

POWER = 60
MOVE_TIME = 1.0

# Step 1: Turn LEFT using both motors
# Left motor backward, right motor forward
mini.runmotor("L", "1", str(POWER))
mini.runmotor("R", "2", str(POWER))
time.sleep(0.5)
mini.stoprobot()

time.sleep(0.5)

# Step 2: Normal turn RIGHT
mini.runmotor("R", "1", str(POWER))
time.sleep(MOVE_TIME)
mini.stoprobot()

time.sleep(0.5)

# Step 3: Move FORWARD for 1 second
mini.runmotor("L", "1", str(POWER))
mini.runmotor("R", "1", str(POWER))
time.sleep(MOVE_TIME)
mini.stoprobot()

time.sleep(0.5)

# Step 4: Move BACKWARD for 1 second
mini.runmotor("L", "2", str(POWER))
mini.runmotor("R", "2", str(POWER))
time.sleep(1.2)
mini.stoprobot()

time.sleep(0.5)

# Step 5: Normal turn RIGHT
mini.runmotor("R", "1", 65)
time.sleep(MOVE_TIME)
mini.stoprobot()

time.sleep(0.5)

# Step 6: Normal turn LEFT
mini.runmotor("L", "1", str(POWER))
time.sleep(MOVE_TIME)
mini.stoprobot()

time.sleep(0.5)

# Step 7: Move FORWARD for 1 second
mini.runmotor("L", "1", str(POWER))
mini.runmotor("R", "1", str(POWER))
time.sleep(0.5)
mini.stoprobot()

time.sleep(0.5)

# Step 8: Move BACKWARD for 1 second
mini.runmotor("L", "2", str(POWER))
mini.runmotor("R", "2", str(POWER))
time.sleep(1.2)
mini.stoprobot()

time.sleep(0.5)

print("Task completed.")
