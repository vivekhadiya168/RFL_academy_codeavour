mini = QuarkyMiniExpansion()
mini.miniinitialise()
import time

# Forward movement
mini.runmotor('L', '2', '40')
mini.runmotor('R', '2', '40')
time.sleep(3)
mini.stoprobot()
time.sleep(1)

# Backward movement
mini.runmotor('L', '1', '40')
mini.runmotor('R', '1', '40')
time.sleep(2)
mini.stoprobot()