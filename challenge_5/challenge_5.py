sprite = Sprite('Stage')

import time

# Initialize Quarky Mini Expansion
mini = QuarkyMiniExpansion()
mini.miniinitialise()
mini.stoprobot()

# Initialize servo
expansion = QuarkyIntellio()

POWER = 80

# Step 1: Set servo to 90 degrees
expansion.moveservointime('S1', 90, 1)
time.sleep(1)

# Step 2: Move forward for 1 second
mini.runmotor("L", "1", str(POWER))
mini.runmotor("R", "1", str(POWER))
time.sleep(1)
mini.stoprobot()

# Step 3: Move servo to 0 degrees
expansion.moveservointime('S1', 0, 1)
time.sleep(1)

# Step 4: Move backward for 1 second
mini.runmotor("L", "2", str(POWER))
mini.runmotor("R", "2", str(POWER))
time.sleep(1)
mini.stoprobot()

print("Task completed.")
