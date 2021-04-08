import platform

import RobotManager
import WebApp

debug = True

robot = None
if platform.system() == "Linux":
    print("Using Linux - creating Robot")
    # Create a robot with our pins
    robot = RobotManager.Robot(leftDC_args=(2, 3), rightDC_args=(4, 5), servo_args=(6))


RTCMessage = WebApp.WebRTCManager.RTCMessage


@RTCMessage.on("command")
def onCommand(command):
    print("Main received command: " + command)


@RTCMessage.on("message")
def onMessage(message):
    print("Received message: " + message)


# Arguments for the webapp
class WebAppArgs:
    def __init__(self):
        self.host = "0.0.0.0"
        self.port = "8080"
        self.cert_file = None
        self.key_file = None
        self.verbose = debug


if __name__ == "__main__":
    WebApp.start_app(WebAppArgs())
