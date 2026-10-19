import time

mini = QuarkyMiniExpansion()
mini.miniinitialise()


for i in range(4):
    mini.runmotor('L', '1', 60)
    time.sleep(1)
    mini.stopmotor('L')
    time.sleep(1)

for i in range(4):
    mini.runmotor('R', '1', 60)
    time.sleep(1)
    mini.stopmotor('L')
    time.sleep(1)