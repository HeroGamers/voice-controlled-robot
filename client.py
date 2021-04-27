import threading
import time
from danspeech.audio import Microphone
from pymitter import EventEmitter
from selenium import webdriver
import SpeechManager

SpeechTranscription = EventEmitter()

input("Press Enter to start setting up the SpeechManager.")

mic_list = Microphone.list_microphone_names()
mic_list_with_numbers = list(zip(range(len(mic_list)), mic_list))
print("Available microphones: {0}".format(mic_list_with_numbers))
mic_number = input("Pick the number of the microphone you would like to use: ")
m = Microphone(sampling_rate=16000, device_index=int(mic_number))

ds = SpeechManager.DanSpeecher(m)

print("Speak a lot to adjust the volume")
ds.adjust()
print("Adjustment done.")
ds.createGenerator()

transcriber = threading.Thread(target=ds.startTranscriber, args=(SpeechTranscription,), daemon=True)
print("Running transcriber")
transcriber.start()

input("Press Enter to open webbrowser.")
driver = webdriver.Chrome()  # Optional argument, if not specified will search path.
driver.get('http://192.168.0.100')

time.sleep(5)

# Get input box
command_input = driver.find_element_by_id('command-input')


@SpeechTranscription.on("command")
def inputCommand(command):
    if command_input:
        if command_input.is_displayed() and command_input.is_enabled():
            command_input.clear()
            command_input.send_keys(command)
            driver.find_element_by_id("submit-command").click()


input("Press Enter to exit the application...")
driver.quit()
