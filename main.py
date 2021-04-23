import platform
import CommandManager
import RobotManager
import WebApp

debug = False

robot = None

RTCMessage = WebApp.WebRTCManager.RTCMessage


# Command listener from the client webpage - all text commands are recieved here
@RTCMessage.on("command")
async def onCommand(command):
    print("Main received command: " + command)
    # Parse the different commands into separate Command's, for example:
    # "to frem og to tilbage" > [Command<to frem>, Command<to tilbage>]
    commands = CommandManager.CommandParser(command).commands

    if not commands:
        print("No commands?")
        return

    # If a robot is available
    if robot:
        # If first command is stop in the list of commands, then run command immediately
        if commands[0].command == 0:
            robot.queue.empty()
            await commands[0].run(robot)
        else:
            # add commands to queue
            robot.queue.addToQueue(commands)


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
    if platform.system() == "Linux":
        print("Using Linux - creating Robot...")
        # Create a robot with our pins
        robot = RobotManager.Robot(leftDC_args=("BOARD3", "BOARD5"), rightDC_args=("BOARD11", "BOARD13"), servo_args=("BOARD19",))

    print("Starting WebApp...")
    WebApp.start_app(WebAppArgs())
