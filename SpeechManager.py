import asyncio
import concurrent
import logging

import av
import pyaudio
from aiortc.mediastreams import MediaStreamError
from danspeech import Recognizer
from danspeech.pretrained_models import TransferLearned
from danspeech.audio.resources import Microphone
from danspeech.language_models import DSL3gram
from pymitter import EventEmitter

logger = logging.getLogger("SpeechManager")
p = pyaudio.PyAudio()


class TrackStream:
    def __init__(self, track, samp_rate):
        self.track = track
        self.samp_rate = samp_rate
        self.stream = p.open(rate=samp_rate, format=pyaudio.paInt16, channels=1, output=True, input=True)
        self.thread_loop = None
        self.loop = asyncio.get_event_loop()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def startWriting(self):
        self.loop = asyncio.get_event_loop()
        # with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        #     self.executor = executor
        #     self.loop.run_in_executor(self.executor, self.executorRun)

    def executorRun(self):
        self.thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.thread_loop)
        self.thread_loop.run_until_complete(self.writeToStream())

    async def writeToStream(self):
        logger.info("Running audio track frames...")

        while True:
            await asyncio.sleep(0)
            try:
                # logger.info("Getting frame")
                frame = await self.track.recv()

                # logger.info("got frame")
                if type(frame) is av.audio.frame.AudioFrame:
                    # logger.info("write stream")
                    self.loop.run_in_executor(self.executor, self.stream.write, frame.to_ndarray().tobytes())
            except MediaStreamError as e:
                logger.error(str(e))
                return
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


class DanSpeecher():
    def __init__(self, mic: Microphone):
        # Variables
        self.transcribing = False

        # Init a microphone object
        self.m = mic

        # Init a DanSpeech model and create a Recognizer instance
        self.model = TransferLearned()
        self.recognizer = Recognizer(model=self.model)

        # Try using the DSL 3 gram language model
        try:
            self.lm = DSL3gram()
            self.recognizer.update_decoder(lm=self.lm)
        except ImportError:
            logger.info("ctcdecode not installed. Using greedy decoding.")

        logger.info("Speak a lot to adjust silence detection from microphone...")
        with self.m as source:
            self.recognizer.adjust_for_speech(source, duration=5)

        # Enable streaming
        self.recognizer.enable_streaming()

        # Create the streaming generator which runs a background thread listening to the microphone stream
        self.generator = self.recognizer.streaming(source=self.m)

    def get_transcription(self):
        return next(self.generator)

    def startTranscriber(self, emitter: EventEmitter):
        self.transcribing = True
        while True:
            if not self.transcribing:
                break
            transcription = self.get_transcription()
            logger.debug("Transcription: " + str(transcription))
            emitter.emit("command", transcription)

    def stop(self):
        self.transcribing = False
