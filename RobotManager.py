import asyncio
import logging
import math
import threading
from time import sleep
from gpiozero import Motor, Servo, DigitalInputDevice
import CommandManager

logger = logging.getLogger("RobotManager")
# Unchangeable variables
wheel_diameter = 7  # centimeters


class Robot:
    def __init__(self, leftDC_args, rightDC_args, servo_args):
        self.leftDC = DCMotor(forward_pin=leftDC_args["motor_pos"], backward_pin=leftDC_args["motor_neg"],
                              encoder_pins={"enc_a": leftDC_args["encoder_a"], "enc_b": leftDC_args["encoder_b"]},
                              pwm_pin=leftDC_args["pwm_pin"])
        self.rightDC = DCMotor(forward_pin=rightDC_args["motor_pos"], backward_pin=rightDC_args["motor_neg"],
                               encoder_pins={"enc_a": rightDC_args["encoder_a"], "enc_b": rightDC_args["encoder_b"]},
                               pwm_pin=rightDC_args["pwm_pin"])
        self.frontServo = ServoMotor(servo_pin=servo_args["servo_pin"])

        # How many centimeters to turn the wheels when turning around by 90 degrees
        self.turn_distance = 10
        # How much the front wheels should tilt when turning
        self.turn_degrees = 45

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
                    logger.debug("Running command: " + str(next_command.command))
                    await next_command.run(self)
                else:
                    await asyncio.sleep(1)
            else:
                await asyncio.sleep(1)

    async def drive(self, centimeters=100):
        # TODO maybe these functions should be async
        if not self.frontServo.is_centered():
            self.frontServo.center()

        # Wait for servo to center
        while self.frontServo.is_running():
            await asyncio.sleep(0.2)

        # Drive forwards or backwards depending on the distance
        if centimeters > 0:
            self.rightDC.forward(centimeters)
            self.leftDC.forward(centimeters)
        else:
            # It's already minus, so minus it again and get plus
            self.rightDC.backward(-centimeters)
            self.leftDC.backward(-centimeters)

        while self.isRunning():
            await asyncio.sleep(0.2)

    async def turn(self, degrees=90):
        # Over 0 = right, else turn left
        if degrees > 0:
            self.frontServo.turn(self.turn_degrees)
        else:
            self.frontServo.turn(-self.turn_degrees)

        # Wait for servo to turn
        while self.frontServo.is_running():
            await asyncio.sleep(0.2)

        # TODO: CALCULATE DISTANCE TO TURN FOR AMOUNT OF DEGREES
        # The distance that the wheels in the back travel to turn, is what we use together with degrees to variate the degrees at which we turn
        if degrees > 0:
            self.rightDC.forward(self.turn_distance)
            self.leftDC.backward(self.turn_distance)
        else:
            self.rightDC.backward(self.turn_distance)
            self.leftDC.forward(self.turn_distance)

        while self.isRunning():
            await asyncio.sleep(0.2)

    def isRunning(self):
        return bool(self.leftDC.is_running() or self.rightDC.is_running() or self.frontServo.is_running())

    def stop(self):
        self.leftDC.stop()
        self.rightDC.stop()
        self.frontServo.stop()


class PIDController:
    def __init__(self, encoder, pwm_pin):
        # Define pins
        self.encoder = encoder
        self.output_pin = pwm_pin


class Encoder:
    def __init__(self, pins):
        # Define pins
        self.outputA = DigitalInputDevice(pins["enc_a"])
        self.outputB = DigitalInputDevice(pins["enc_b"])

        # Variable to increase as we go
        self.position = 0

        # Variable to put current position in at start of tracking
        self.old_position = self.position

        # Variables for signal distance
        self.signals_per_rotation = 1350  # Measured by running a motor and stopping it at certain points, until it turned 360 degrees
        self.signal_centimeter_ratio = ((wheel_diameter*math.pi)/self.signals_per_rotation)  # Get circumference of wheel, and get the ratio between signals from encoder and distance

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
        centimeters_traveled = position_change*self.signal_centimeter_ratio
        meters_traveled = centimeters_traveled*100
        return {"cm": centimeters_traveled, "m": meters_traveled}


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
        # while self.encoder.getPositionChange() <= self.encoder.signals_per_rotation:
        #     sleep(0.001)
        # We wait until the distance travelled equals what we asked for
        while self.encoder.getDistance()["cm"] < distance:
            sleep(0.001)
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
