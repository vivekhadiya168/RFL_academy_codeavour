import time

mini = QuarkyMiniExpansion()
mini.miniinitialise()


for i in range(4):
    mini.runmotor('L', '1', '100')
    mini.runmotor('R', '2', '100')
    time.sleep(3)

    mini.stoprobot()

    mini.runmotor('L', '1', '50')
    time.sleep(1)

    mini.stoprobot()