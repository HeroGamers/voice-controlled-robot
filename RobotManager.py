from gpiozero import DigitalOutputDevice, Motor, Servo, CompositeDevice
from time import sleep

# Unchangeable variables

# Arrays
motors = []


class Robot:
    def __init__(self, leftDC_args, rightDC_args, servo_args):
        self.leftDC = DCMotor(*leftDC_args)
        self.rightDC = DCMotor(*rightDC_args)

        self.frontServo = Servo(*servo_args)

    def forward(self, centimeters):
        # TODO maybe these functions should be async
        self.leftDC.forward(centimeters)
        self.rightDC.forward(centimeters)

    def turn_right(self):
        print("aaaaaa")

    def turn_left(self):
        print("bbbbbb")


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

    def off(self):
        self.motor.stop()


class ServoMotor(MotorFactory):
    def __init__(self, servo_pin):
        super().__init__("ServoMotor", servo_pin)

    def turn(self, degrees):
        # TODO calculate value between -1 and +1 (min and max), for degrees given
        self.motor.value = 1


# Shared functions
def turnAllOff():
    for motor in motors:
        if callable(getattr(motor, "off", None)):
            motor.off()


def turnAllOn():
    for motor in motors:
        if callable(getattr(motor, "on", None)):
            motor.on()
