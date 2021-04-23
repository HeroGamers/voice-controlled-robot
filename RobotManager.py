import asyncio
import threading
from time import sleep

from gpiozero import Motor, Servo, DigitalInputDevice
import CommandManager

# Unchangeable variables


class Robot:
    def __init__(self, leftDC_args, rightDC_args, servo_args):
        self.leftDC = DCMotor(forward_pin=leftDC_args["motor_pos"], backward_pin=leftDC_args["motor_neg"],
                              encoder_pins={"enc_a": leftDC_args["encoder_a"], "enc_b": leftDC_args["encoder_b"]},
                              pwm_pin=leftDC_args["pwm_pin"])
        self.rightDC = DCMotor(forward_pin=rightDC_args["motor_pos"], backward_pin=rightDC_args["motor_neg"],
                               encoder_pins={"enc_a": rightDC_args["encoder_a"], "enc_b": rightDC_args["encoder_b"]},
                               pwm_pin=rightDC_args["pwm_pin"])
        self.frontServo = ServoMotor(servo_pin=servo_args["servo_pin"])

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


class PIDController:
    def __init__(self, encoder, pwm_pin):
        # Define pins
        self.encoder = encoder
        self.output_pin = pwm_pin


class Encoder:
    def __init__(self, pins):
        # Define pins
        self.signals_per_rotation = 1350
        self.signals_per_meter = self.signals_per_rotation*10  # needs more
        self.outputA = DigitalInputDevice(pins["enc_a"])
        self.outputB = DigitalInputDevice(pins["enc_b"])

        # Variable to increase as we go
        self.position = 0

        # Variable to put current position in at start of tracking
        self.old_position = self.position

        # Listen for changes
        self.outputB.when_activated = self._increment
        self.outputB.when_deactivated = self._increment

    def _increment(self):
        self.position += 1

    def startDistanceTracking(self):
        self.old_position = self.position

    def getPositionChange(self):
        return self.position-self.old_position

    def getDistance(self):
        position_change = self.getPositionChange()
        meters_traveled = position_change/self.signals_per_meter
        centimeters = meters_traveled*100
        return {"cm": centimeters, "m": meters_traveled}


class DCMotor:
    def __init__(self, forward_pin, backward_pin, encoder_pins, pwm_pin, speed=1):
        self.motor = Motor(forward_pin, backward_pin)
        self.encoder = Encoder(encoder_pins)
        self.pid = PIDController(self.encoder, pwm_pin)
        self.speed = speed

    def forward(self, distance):
        self.encoder.startDistanceTracking()
        self.motor.forward(self.speed)
        thread = threading.Thread(target=self.wait_distance, args=(distance,))
        thread.daemon = True
        thread.start()

    def backward(self, distance):
        self.encoder.startDistanceTracking()
        self.motor.backward(self.speed)
        thread = threading.Thread(target=self.wait_distance, args=(distance,))
        thread.daemon = True
        thread.start()

    def wait_distance(self, distance):
        while self.encoder.getPositionChange() <= self.encoder.signals_per_rotation:
            sleep(0.001)
        # TODO some function to check distance with encoder
        # maybe this function should be async - since when we have to wait for encoder to give distance,
        # everything else will be stopped while we wait for the motor to reach the set distance
        self.stop()

    def stop(self):
        self.motor.stop()

    def is_running(self):
        return self.motor.is_active


class ServoMotor:
    def __init__(self, servo_pin, min_pulse_width=0.4/1000, max_pulse_width=2.4/1000, frame_width=20/1000):
        self.motor = Servo(servo_pin, min_pulse_width=min_pulse_width, max_pulse_width=max_pulse_width, frame_width=frame_width)

    def is_centered(self):
        return bool(self.motor.value == 0)

    def center(self):
        self.motor.value = 0

    def turn(self, degrees):
        assert -90 <= degrees <= 90, "Degrees should be within -60 degrees and 60 degrees"
        # Calculates value between -1 and +1 (min and max), for degrees given
        self.motor.value = degrees/90

    def stop(self):
        self.motor.detach()

    def is_running(self):
        # TODO: can we check if servo is running?
        # return self.motor.is_active
        return False


# # Shared functions
# def turnAllOff():
#     for motor in motors:
#         if callable(getattr(motor, "off", None)):
#             motor.off()
#
#
# def turnAllOn():
#     for motor in motors:
#         if callable(getattr(motor, "on", None)):
#             motor.on()
