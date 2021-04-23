import asyncio
from time import sleep

from gpiozero import Motor, Servo
import CommandManager

# Unchangeable variables

# Arrays
motors = []


class Robot:
    def __init__(self, leftDC_args, rightDC_args, servo_args):
        self.leftDC = DCMotor(*leftDC_args)
        self.rightDC = DCMotor(*rightDC_args)
        self.frontServo = ServoMotor(*servo_args)

        # Make new command queue for robot
        self.queue = CommandManager.CommandQueue()

        self.running = True
        self.current_command = None

        # Get a new loop that we can use for the looping task
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Start the check for command loop
        asyncio.ensure_future(self.run())

    async def run(self):
        # Main loop for checking for commands and running them
        while True:
            # If robot is running
            if self.running:
                # If any commands in queue
                if self.queue.queue:
                    next_command: CommandManager.Command = self.queue.queue[0]
                    self.queue.queue.pop(0)
                    print("Running command: " + str(next_command.command))
                    await next_command.run(self)
                else:
                    await asyncio.sleep(1)
            else:
                await asyncio.sleep(1)

    async def forward(self, centimeters):
        # TODO maybe these functions should be async
        if not self.frontServo.is_centered():
            self.frontServo.center()

        # Wait for servo to center
        while self.frontServo.is_running():
            await asyncio.sleep(0.2)

        self.rightDC.forward(centimeters)
        self.leftDC.forward(centimeters)

        while self.isRunning():
            await asyncio.sleep(0.2)

    async def backward(self, centimeters):
        # TODO maybe these functions should be async
        if not self.frontServo.is_centered():
            self.frontServo.center()

        # Wait for servo to center
        while self.frontServo.is_running():
            await asyncio.sleep(0.2)

        self.rightDC.backward(centimeters)
        self.leftDC.backward(centimeters)

        while self.isRunning():
            await asyncio.sleep(0.2)

    async def turn_right(self, degrees):
        self.frontServo.turn(degrees)

        # Wait for servo to turn
        while self.frontServo.is_running():
            await asyncio.sleep(0.2)

        # TODO: CALCULATE DISTANCE TO TURN
        self.rightDC.forward(10)
        self.leftDC.backward(10)

        while self.isRunning():
            await asyncio.sleep(0.2)

    async def turn_left(self, degrees):
        self.frontServo.turn(-degrees)

        # Wait for servo to turn
        while self.frontServo.is_running():
            await asyncio.sleep(0.2)

        # TODO: CALCULATE DISTANCE TO TURN
        self.rightDC.backward(10)
        self.leftDC.forward(10)

        while self.isRunning():
            await asyncio.sleep(0.2)

    def forward_nonasync(self, centimeters):
        self.frontServo.center()
        self.rightDC.forward(centimeters)
        self.leftDC.forward(centimeters)

    def backward_nonasync(self, centimeters):
        self.frontServo.center()
        self.rightDC.backward(centimeters)
        self.leftDC.backward(centimeters)

    def turn_right_nonasync(self, degrees):
        self.frontServo.turn(degrees)
        self.rightDC.forward(10)
        self.leftDC.backward(10)

    def turn_left_nonasync(self, degrees):
        self.frontServo.turn(-degrees)
        self.rightDC.backward(10)
        self.leftDC.forward(10)

    def isRunning(self):
        return bool(self.leftDC.is_running() or self.rightDC.is_running() or self.frontServo.is_running())

    def stop(self):
        self.leftDC.stop()
        self.rightDC.stop()
        self.frontServo.stop()

    def test_nonasync(self):
        self.forward_nonasync(10)
        sleep(5)
        self.backward_nonasync(10)
        sleep(5)
        self.turn_right_nonasync(1)
        sleep(5)
        self.turn_left_nonasync(1)
        sleep(5)


class MotorFactory:
    def __init__(self, type: str, *args):
        # Define pins
        self.motor = None
        if type == "DCMotor":
            self.motor = Motor(*args)
        elif type == "ServoMotor":
            self.motor = Servo(*args)

        # Append motor to motors
        motors.append(self)


class DCMotor(MotorFactory):
    def __init__(self, forward_pin, backward_pin, speed=0.5):
        super().__init__("DCMotor", forward_pin, backward_pin)
        self.speed = speed

    def forward(self, distance):
        self.motor.forward(distance)
        # TODO some function to check distance with encoder
        # maybe this function should be async - since when we have to wait for encoder to give distance,
        # everything else will be stopped while we wait for the motor to reach the set distance

    def backward(self, distance):
        self.motor.backward(distance)

    def stop(self):
        self.motor.stop()

    def is_running(self):
        return self.motor.is_active


class ServoMotor(MotorFactory):
    def __init__(self, servo_pin):
        super().__init__("ServoMotor", servo_pin)

    def is_centered(self):
        return bool(self.motor.value == 0)

    def center(self):
        self.motor.value = 0

    def turn(self, degrees):
        # TODO calculate value between -1 and +1 (min and max), for degrees given
        self.motor.value = 1

    def stop(self):
        self.motor.detach()

    def is_running(self):
        # TODO: can we check if servo is running?
        # return self.motor.is_active
        return False


# Shared functions
def turnAllOff():
    for motor in motors:
        if callable(getattr(motor, "off", None)):
            motor.off()


def turnAllOn():
    for motor in motors:
        if callable(getattr(motor, "on", None)):
            motor.on()
