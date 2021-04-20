import asyncio
import audioop
import concurrent
import logging
import av
import numpy as np
import pyaudio
from aiortc.mediastreams import MediaStreamError
from danspeech import Recognizer
from danspeech.errors.recognizer_errors import NoDataInBuffer
from danspeech.pretrained_models import TransferLearned
from danspeech.audio.resources import Microphone, SpeechSource
from danspeech.language_models import DSL3gram
from pymitter import EventEmitter

logger = logging.getLogger("SpeechManager")
# np.set_printoptions(threshold=numpy.inf)
p = pyaudio.PyAudio()


class TrackStream:
    def __init__(self, track):
        self.track = track
        self.samp_rate = 16000
        self.channels = 1
        self.format = pyaudio.paInt16
        self.stream = None
        self.thread_loop = None
        self.use_blocking = True
        self.loop = asyncio.get_event_loop()
        self.chunk_size = 1024
        self.buffer = []
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def callback(self):
        print("mmmh")

    def startWriting(self):
        self.loop = asyncio.get_event_loop()
        # with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        #     self.executor = executor
        #     self.loop.run_in_executor(self.executor, self.executorRun)

    def executorRun(self):
        self.thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.thread_loop)
        self.thread_loop.run_until_complete(self.writeToStream())

    async def intializeStream(self):
        # Get one frame and use it for the stream info
        await self.getFrame()

    async def getFrame(self):
        try:
            # logger.info("Getting frame")
            frame: av.audio.frame.AudioFrame = await self.track.recv()
            frame_arr: np.ndarray = frame.to_ndarray()

            if type(frame) is not av.audio.frame.AudioFrame:
                print("Not audio frame")
                return
            # logger.info("got frame")

            if not self.stream:
                print("Audio stream information:")
                print("--------------------")
                print("Frame: " + str(frame))
                print("Format: " + str(frame.format))
                print("Layout name: " + str(frame.layout.name))
                print("Layout channels: " + str(len(frame.layout.channels)))
                print("Planes: " + str(frame.planes))
                print("Bits: " + str(frame.format.bits))
                print("Sample rate: " + str(frame.sample_rate))
                print("Samples: " + str(frame.samples))
                print("Array size: " + str(len(frame_arr[0])))
                print("--------------------")
                if frame.sample_rate:
                    self.samp_rate = frame.sample_rate
                self.channels = len(frame.layout.channels)

                if frame.format.bits == 16:
                    self.format = pyaudio.paInt16

                if self.use_blocking:
                    self.stream = p.open(rate=self.samp_rate*self.channels, format=self.format, channels=self.channels,
                                         output=True, input=True, frames_per_buffer=int(self.chunk_size*self.channels))
                else:
                    self.stream = p.open(rate=self.samp_rate, format=self.format, channels=self.channels,
                                         output=True, frames_per_buffer=self.chunk_size,
                                         stream_callback=self.callback)

            # Add to buffer
            self.buffer = self.buffer + frame_arr[0].tolist()

            # print("Frame " + str(i) + ":")
            # print("--------------------")
            # print("Time: " + str(frame.time))
            # print("Array: " + str(frame_arr))
            # # print(frame_arr.tobytes())
            # # print(len(frame_arr))
            # print("Current buffer size: " + str(len(self.buffer)))
            # print("--------------------")
        except MediaStreamError as e:
            logger.error(str(e))
            return
        except Exception as e:
            logger.error(str(e))
            return

    async def writeToStream(self):
        logger.info("Running audio track frames...")

        i = 0
        while True:
            i += 1
            await asyncio.sleep(0)
            # await asyncio.sleep(0.02)
            try:
                # Get a new frame and add it to the buffer
                await self.getFrame()

                # Write frames from the buffer
                if self.use_blocking:
                    to_write = self.chunk_size*self.channels
                    if len(self.buffer) > to_write:
                        # print("More than buffer size")
                        toWrite = np.array(self.buffer[:to_write])
                        self.buffer = self.buffer[to_write:]
                        self.loop.run_in_executor(self.executor, self.stream.write, toWrite.tobytes())
                        # self.stream.write(toWrite.tobytes())
            except Exception as e:
                logger.error(str(e))
                return


class MicInput(Microphone):
    def __init__(self, sampling_rate=16000, chunk_size=1024, pyaudio_stream=None):
        super().__init__(sampling_rate=sampling_rate, chunk_size=chunk_size)
        self.pyaudio_stream = pyaudio_stream

    def __enter__(self):
        assert self.stream is None, "This audio source is already inside a context manager"
        self.audio = self.pyaudio_module.PyAudio()
        try:
            self.stream = Microphone.MicrophoneStream(self.pyaudio_stream)
        except Exception:
            self.audio.terminate()
        return self


class CustomRecognizer(Recognizer):
    def __init__(self, model):
        super().__init__(model=model)

    async def adjust_for_speech(self, source, duration=4):
        """
        Adjusts the energy level threshold required for the :meth:`audio.Microphone` to detect
        speech in background.

        **Warning:** You need to talk after calling this method! Else, the energy level will be too low. If talking
        to adjust energy level is not an option, use :meth:`Recognizer.adjust_for_ambient_noise` instead.

        Only use if the default energy level does not match your use case.

        :param Microphone source: Source of audio.
        :param float duration: Maximum duration of adjusting the energy threshold

        """
        assert isinstance(source, SpeechSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before adjusting, " \
                                          "see documentation for ``AudioSource``; are you using ``source``" \
                                          " outside of a ``with`` statement?"
        assert self.pause_threshold >= self.non_speaking_duration >= 0

        seconds_per_buffer = (source.chunk + 0.0) / source.sampling_rate
        elapsed_time = 0

        energy_levels = []
        # adjust energy threshold until a phrase starts
        while True:
            await asyncio.sleep(0.02)
            elapsed_time += seconds_per_buffer
            if elapsed_time > duration:
                break

            buffer = source.stream.read(source.chunk)
            energy = audioop.rms(buffer, source.sampling_width)  # energy of the audio signal
            energy_levels.append(energy)

        energy_average = sum(energy_levels) / len(energy_levels)

        # Subtract some ekstra energy, since we take average
        if energy_average > 80:
            self.energy_threshold = energy_average - 80
        else:
            self.energy_threshold = energy_average

    async def streaming(self, source):
        """
        Generator class for a stream audio source a :meth:`Microphone`

        Spawns a background thread and uses the loaded model to continuously transcribe audio input between
        detected silences from the :meth:`Microphone` stream.

        **Warning:** Requires that :meth:`Recognizer.enable_streaming` has been called.

        :param Microphone source: Source of audio.

        :example:

            .. code-block:: python

                generator = recognizer.streaming(source=m)

                # Runs for a long time. Insert your own stop condition.
                for i in range(100000):
                    trans = next(generator)
                    print(trans)

        """
        stopper, data_getter = self.listen_in_background(source)
        self.stream_thread_stopper = stopper

        is_last = False
        is_first_data = False
        data_array = []

        while self.stream:
            # Loop for data (gets all the available data from the stream)
            while True:
                await asyncio.sleep(0)
                # If it is the last one in a stream, break and perform recognition no matter what
                if is_last:
                    is_first_data = True
                    break

                # Get all available data
                try:
                    if is_first_data:
                        is_last, data_array = data_getter()
                        is_first_data = False
                    else:
                        is_last, temp = data_getter()
                        data_array = np.concatenate((data_array, temp))
                # If this exception is thrown, then we no available data
                except NoDataInBuffer:
                    # If no data in buffer, we sleep and wait
                    await asyncio.sleep(0.2)

            # Since we only break out of data loop, if we need a prediction, the following works
            # We only do a prediction if the length of gathered audio is above a threshold
            if len(data_array) > self.mininum_required_speaking_seconds * source.sampling_rate:
                yield self.recognize(data_array)

            is_last = False
            data_array = []


class DanSpeecher():
    def __init__(self, mic: Microphone):
        # Variables
        self.transcribing = False

        # Init a microphone object
        self.m = mic

        # Init a DanSpeech model and create a Recognizer instance
        self.model = TransferLearned()
        self.recognizer = CustomRecognizer(model=self.model)

        # Try using the DSL 3 gram language model
        try:
            self.lm = DSL3gram()
            self.recognizer.update_decoder(lm=self.lm)
        except ImportError:
            logger.info("ctcdecode not installed. Using greedy decoding.")

        # Enable streaming
        self.recognizer.enable_streaming()

        # Generator
        self.generator = None

    async def adjust(self):
        logger.info("Speak a lot to adjust silence detection from microphone...")
        with self.m as source:
            await self.recognizer.adjust_for_speech(source, duration=5)

    async def createGenerator(self):
        # Create the streaming generator which runs a background thread listening to the microphone stream
        self.generator = self.recognizer.streaming(source=self.m)

    async def get_transcription(self):
        return next(self.generator)

    async def startTranscriber(self, emitter: EventEmitter):
        self.transcribing = True
        while True:
            if not self.transcribing:
                break
            transcription = await self.get_transcription()
            logger.debug("Transcription: " + str(transcription))
            emitter.emit("command", transcription)

    def stop(self):
        self.transcribing = False
