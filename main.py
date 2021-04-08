import json
import math
import RobotManager as RM
import asyncio
import websockets

# Unchangeable variables
moveDelay = 100  # The delay between each move, in milliseconds
gearPitchDiameter = 20  # The pitch diameter of the gear, in millimeters
moveStepperDistance = 1000  # The distance for the move stepper to move, in millimeters
moveStepperDegrees = 360*(moveStepperDistance/(math.pi*gearPitchDiameter))  # The amount of degrees the move stepper should move to fit/unfit

# Changeable variables
debug = True
stop = False
running = False
ws_uri = "ws://play.nfs.codes:8080"  # URI for the websocket


def log(message):
    print(str(message))


def logDebug(message):
    if debug:
        print("[DEBUG]: " + str(message))


# Turn all the steppers off
SF.turnAllOff()


# Function to do a certain move
async def do_move(notation):
    logDebug(notation)
    # Find the stepper motor
    motor = None
    if "D" in notation:
        logDebug("Selected DownStepper")
        motor = SF.DownStepper
    elif "R" in notation:
        logDebug("Selected RightStepper")
        motor = SF.RightStepper
    elif "L" in notation:
        logDebug("Selected LeftStepper")
        motor = SF.LeftStepper
    elif "F" in notation:
        logDebug("Selected FrontStepper")
        motor = SF.FrontStepper
    elif "B" in notation:
        logDebug("Selected BackStepper")
        motor = SF.BackStepper

    if motor:
        if "'" in notation:  # The left turning notation
            logDebug("Moving left once...")
            motor.set_direction("LEFT")
            motor.move(90)
            motor.set_direction("RIGHT")
        elif "2" in notation:  # The move 180 notation
            logDebug("Moving 180 degrees...")
            motor.move(180)
        else:  # Normal notation
            logDebug("Moving right once...")
            motor.move(90)

        # Delay after the move
        logDebug("Done moving, sleeping...")
        await asyncio.sleep(moveDelay*10**(-3))  # milliseconds to seconds
        logDebug("Done sleeping!")
        return True

    logDebug("Didn't find a motor, returning false...")
    return False


# The run function
async def run(moves, websocket=None):
    global stop
    global running

    # Change running variable to True
    running = True
    if websocket:
        # Send to websocket that we're running
        await websocket.send("The robot is running! Do not touch!")

    # Move the move stepper to the correct position...
    log("Moving move stepper...")
    SF.MoveStepper.on()
    SF.MoveStepper.set_direction("RIGHT")
    SF.MoveStepper.move(moveStepperDegrees, acceleration=0.01, max_rpm=200)
    log("Done moving the move stepper!")

    # Turn all drives on
    SF.turnAllOn()
    # Do the moves
    moves = moves.split()  # Split at space

    log("Doing moves...")
    # Do moves
    count_moves = len(moves)
    i = 1
    for move in moves:
        if not stop:  # If stop is not true
            log("Doing move " + str(i) + "/" + str(count_moves) + "...")
            status = await do_move(move)
            if not status:
                log("Move didn't complete...")
            i += 1
    log("Done with the moves!")
    # Turn the rubik's steppers off again
    SF.DownStepper.off()
    SF.FrontStepper.off()
    SF.BackStepper.off()
    SF.RightStepper.off()
    SF.LeftStepper.off()

    log("Moving the move stepper... Please wait...")
    SF.MoveStepper.set_direction("LEFT")
    SF.MoveStepper.move(moveStepperDegrees, acceleration=1)
    # Turn all off
    SF.turnAllOff()
    log("Done moving the move stepper, feel free to pull out cube!")

    # Set running variable to False
    running = False
    if websocket:
        # Send to websocket that we're done running
        await websocket.send("The robot is done running! Feel free to pull it out!")
    # Be sure that stop is set to False, if it has been stopped
    stop = False


async def websocketlistener():
    log("Starting listener...")
    # Loop the connection itself
    while True:
        try:  # Try to catch if it fails connecting instead of throwing error
            async with websockets.connect(ws_uri) as websocket:
                log("Connected!")
                # Loop this
                while True:
                    # Look for a response
                    try:
                        res = await websocket.recv()
                        if res:
                            logDebug(res)
                            res_json = None
                            try:
                                res_json = json.loads(res)
                            except Exception as e:
                                logDebug("The response received is not JSON")
                            if res_json:
                                logDebug(res_json)
                                if 'messagecode' in res_json:
                                    messagecode = res_json['messagecode']
                                    if "stop" in messagecode.lower():
                                        global stop
                                        stop = True
                                    elif "moves" in messagecode.lower():
                                        if not running:
                                            moves = res_json['data']
                                            logDebug("Moves received - " + moves)
                                            log("Running...")
                                            try:
                                                asyncio.ensure_future(run(moves))  # Do moves, but continue with other stuff
                                            except Exception as e:
                                                log("Error while doing moves! - " + str(e))
                                        else:
                                            log("Cannot do moves when running!")
                                            await websocket.send("Cannot do moves while running!")
                    except Exception as e:
                        log("Error while receiving response from websocket! - " + str(e))
                        if "code = 1006 (connection closed abnormally [internal]), no reason" in str(e):
                            break
                log("Loop broken")
                await websocket.close()
                log("Websocket connection closed")
        except Exception as e:
            log("Error while running websocket! - " + str(e))
        await asyncio.sleep(10)

# Start the Websocket Listener
asyncio.get_event_loop().run_until_complete(websocketlistener())
