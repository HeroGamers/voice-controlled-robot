from gpiozero import Motor
from time import sleep
from VoiceCommands import drive, stop


#setup
motor = Motor(forward=4, backward=14)



#main loop
while True:

    if drive == True:
        motor.forward()
        sleep(drive.distance)

    if stop == True:
        motor.stop()