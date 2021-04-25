import asyncio
import audioop
import collections
from concurrent.futures import ThreadPoolExecutor
import logging
import math
import threading
import av
import librosa
import numpy as np
import pyaudio
from aiortc.mediastreams import MediaStreamError
from danspeech import Recognizer
from danspeech.errors.recognizer_errors import NoDataInBuffer, WaitTimeoutError, WrongUsageOfListen
from danspeech.pretrained_models import TransferLearned
from danspeech.audio.resources import Microphone, SpeechSource, AudioData
from danspeech.language_models import DSL3gram
from pymitter import EventEmitter

logger = logging.getLogger("SpeechManager")
# np.set_printoptions(threshold=numpy.inf)
p = pyaudio.PyAudio()


class TrackStream:
    def __init__(self, track):
        self.track = track
        self.samp_rate = 48000
        self.channels = 2
        self.chunk_size = int(512*2)
        # self.chunk_size = 1280
        # self.chunk_size = 960
        self.format = pyaudio.paInt16
        self.stream = None
        self.thread_loop = None
        self.use_blocking = True
        self.loop = asyncio.get_event_loop()
        self.buffer = []
        self.executor = ThreadPoolExecutor(max_workers=3)

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
            frame = await self.track.recv()

            if type(frame) is not av.audio.frame.AudioFrame:
                logger.error("Not audio frame")
                return

            if not self.stream:
                logger.debug("Audio stream frame information:")
                logger.debug("--------------------")
                logger.debug("Frame: " + str(frame))
                logger.debug("Format: " + str(frame.format))
                logger.debug("Layout name: " + str(frame.layout.name))
                logger.debug("Layout channels: " + str(len(frame.layout.channels)))
                logger.debug("Planes: " + str(frame.planes))
                logger.debug("Bits: " + str(frame.format.bits))
                logger.debug("Sample rate: " + str(frame.sample_rate))
                logger.debug("Samples: " + str(frame.samples))
                logger.debug("Original array size: " + str(len(frame.to_ndarray().reshape(1920, ))))
                logger.debug("--------------------")
                # if frame.sample_rate:
                #     self.samp_rate = frame.sample_rate
                # self.channels = len(frame.layout.channels)

                self.stream = p.open(rate=self.samp_rate*self.channels, format=self.format, channels=self.channels,
                                     output=True, input=True, frames_per_buffer=int(self.chunk_size*self.channels))

                logger.debug("Stream information:")
                logger.debug("--------------------")
                logger.debug("Format: " + str(int(self.format*2)))
                logger.debug("Channels: " + str(self.channels))
                logger.debug("Sample rate: " + str(self.samp_rate*self.channels) + " ("+str(self.samp_rate)+")")
                logger.debug("Cache size: " + str(int(self.chunk_size*self.channels)))
                logger.debug("--------------------")

            # self.writeToBuffer(frame)
            await self.loop.run_in_executor(self.executor, self.writeToBuffer, frame)
        except MediaStreamError as e:
            logger.error(str(e))
            return
        except Exception as e:
            logger.error(str(e))
            return

    def writeToBuffer(self, frame):
        # logger.info("got frame")
        frame_arr: np.ndarray = frame.to_ndarray().reshape(1920, )

        # Transform frame if needed
        re_sampled = None
        if frame.sample_rate != self.samp_rate:
            frame_float = frame_arr.astype(dtype='float32')
            re_sampled = librosa.resample(frame_float, frame.sample_rate, self.samp_rate, res_type='zero_order_hold')

        if (len(frame.layout.channels) == 2) and (self.channels == 1):
            if re_sampled is not None:
                re_sampled = re_sampled[::2]
                frame_arr = re_sampled.astype(dtype='int16')
            else:
                frame_arr = frame_arr[::2]
        else:
            if re_sampled is not None:
                frame_arr = re_sampled.astype(dtype='int16')

        # Add to buffer
        self.buffer = self.buffer + frame_arr.tolist()

        # logger.debug("Frame " + str(i) + ":")
        # logger.debug("--------------------")
        # logger.debug("Time: " + str(frame.time))
        # logger.debug("Array: " + str(frame_arr))
        # # logger.debug(frame_arr.tobytes())
        # # logger.debug(len(frame_arr))
        # logger.debug("Current buffer size: " + str(len(self.buffer)))
        # logger.debug("--------------------")

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

    def __exit__(self, exc_type, exc_value, traceback):
        print("STOPPING STREAM!")
        # try:
        #     self.stream.close()
        # finally:
        self.stream = None
        self.audio.terminate()


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
        print("adjusting...")
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
        print("done adjusting")

    async def listen_in_background(self, source):
        """
        Spawns a thread which listens to the source of data

        :param source: Source of stream/frames
        :param first_required_frames: Required frames before yielding data for the first pass to the streaming model
        :param general_required_frames: Minimum required frames for passes after the first pass of the streaming model.

        :return: Stopper function used to stop the thread, and a data_getter which returns data from the thread
        according current steps.
        """
        assert isinstance(source, SpeechSource), "Source must be an audio source"

        # These act as globals variables for thread helper functions
        running = [True]
        data = []

        def threaded_listen_sync():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

            # new_loop.run_in_executor(None, threaded_listen)
            asyncio.ensure_future(threaded_listen())
            new_loop.run_forever()

        async def threaded_listen():
            # Thread to run in background
            with source as s:
                while running[0]:
                    await asyncio.sleep(0)
                    generator = self.listen_stream(s)
                    try:  # Listen until stream detects silence
                        while True:
                            await asyncio.sleep(0)
                            # is_last_, temp = next(generator)
                            print("get shit from generator")
                            is_last_, temp = await(generator.__anext__())
                            if isinstance(temp, list):
                                temp = self.get_audio_data(temp, source)
                            else:
                                temp = self.get_audio_data([temp], source)

                            # Append data
                            print("add data")
                            data.append((is_last_, temp))

                            # If is last, we start new listen generator
                            if is_last_:
                                break

                    except WaitTimeoutError:  # listening timed out, just try again
                        pass

        def stopper(wait_for_stop=True):
            running[0] = False

            if wait_for_stop:
                listener_thread.join()  # block until the background thread is done, which can take around 1 second

        async def get_data():
            print("getdata")
            while True:
                await asyncio.sleep(0)
                try:
                    is_last_, audio = data[0]
                    # Remove from buffer
                    data.pop(0)
                    break
                except IndexError:
                    raise NoDataInBuffer

            return is_last_, audio

        listener_thread = threading.Thread(target=threaded_listen_sync)
        listener_thread.daemon = True
        listener_thread.start()
        return stopper, get_data

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
        print("streaming - 1")
        stopper, data_getter = await self.listen_in_background(source)
        print("streaming - 2")
        self.stream_thread_stopper = stopper

        is_last = False
        is_first_data = False
        data_array = []

        while self.stream:
            # Loop for data (gets all the available data from the stream)
            while True:
                print("streaming - 3")
                await asyncio.sleep(0)
                # If it is the last one in a stream, break and perform recognition no matter what
                if is_last:
                    is_first_data = True
                    break

                # Get all available data
                try:
                    if is_first_data:
                        print("streaming - 4")
                        is_last, data_array = await data_getter()
                        is_first_data = False
                    else:
                        print("streaming - 5")
                        is_last, temp = await data_getter()
                        data_array = np.concatenate((data_array, temp))
                # If this exception is thrown, then we no available data
                except NoDataInBuffer:
                    # If no data in buffer, we sleep and wait
                    await asyncio.sleep(0.2)

            # Since we only break out of data loop, if we need a prediction, the following works
            # We only do a prediction if the length of gathered audio is above a threshold
            print("streaming - 6")
            if len(data_array) > self.mininum_required_speaking_seconds * source.sampling_rate:
                yield self.recognize(data_array)

            is_last = False
            data_array = []
            print("streaming - 7")

    async def real_time_streaming(self, source):
        """
        Generator class for a real-time stream audio source a :meth:`Microphone`.

        Spawns a background thread and uses the loaded model(s) to continuously transcribe an audio utterance
        while it is being spoken.

        **Warning:** Requires that :meth:`Recognizer.enable_real_time_streaming` has been called.

        :param Microphone source: Source of audio.

        :example:

            .. code-block:: python

                generator = r.real_time_streaming(source=m)

                iterating_transcript = ""
                print("Speak!")
                while True:
                    is_last, trans = next(generator)

                    # If the transcription is empty, it means that the energy level required for data
                    # was passed, but nothing was predicted.
                    if is_last and trans:
                        print("Final: " + trans)
                        iterating_transcript = ""
                        continue

                    if trans:
                        iterating_transcript += trans
                        print(iterating_transcript)
                        continue

        The generator yields both a boolean (is_last) to indicate whether it is a full utterance
        (detected by silences in audio input) and the (current/part) transcription. If the is_last boolean is true,
        then it is a full utterance determined by a silence.

        **Warning:** This method assumes that you use a model with default spectrogram/audio parameters i.e. 20ms
        audio for each stft and 50% overlap.
        """

        lookahead_context = self.danspeech_recognizer.model.context
        required_spec_frames = (lookahead_context - 1) * 2

        samples_pr_10ms = int(source.sampling_rate / 100)

        # First takes two samples pr 10ms, the rest needs 160 due to overlapping
        general_sample_requirement = samples_pr_10ms * 2 + (samples_pr_10ms * (required_spec_frames - 1))

        # First pass, we need more samples due to padding of initial conv layers
        first_sample_requirement = general_sample_requirement + (samples_pr_10ms * 15)

        data_array = []
        is_first_data = True
        is_first_pass = True
        stopper, data_getter = await self.listen_in_background(source)
        self.stream_thread_stopper = stopper
        is_last = False
        output = None
        consecutive_fails = 0
        data_success = False
        # Wait 0.2 seconds before we start processing to let the background thread spawn
        await asyncio.sleep(0.2)
        while self.stream:

            # Loop for data (gets all the available data from the stream)
            while True:

                # If it is the last one in a stream, break and perform recognition no matter what
                if is_last:
                    break

                # Get all available data
                try:
                    if is_first_data:
                        is_last, data_array = await data_getter()
                        is_first_data = False
                        data_success = True
                    else:
                        is_last, temp = await data_getter()
                        data_array = np.concatenate((data_array, temp))
                        data_success = True
                # If this exception is thrown, then we have no available data
                except NoDataInBuffer:
                    # If it is first data and no data in buffer, then do not break but sleep.

                    # We got some data, now process
                    if data_success:
                        data_success = False
                        consecutive_fails = 0
                        break

                    # We did not get data and it was the first try, sleep for 0.4 seconds
                    if is_first_data:
                        await asyncio.sleep(0.4)
                    else:
                        consecutive_fails += 1

                    # If two fails happens in a row, we sleep for 0.3 seconds
                    if consecutive_fails == 2:
                        consecutive_fails = 0
                        await asyncio.sleep(0.3)

            # If it is the first pass, then we try to pass it
            if is_first_pass:

                # If is last and we have not performed first pass, then it should be discarded and we continue
                if is_last:
                    output = None

                # Check if we have enough frames for first pass
                elif len(data_array) >= first_sample_requirement:
                    output = self.danspeech_recognizer.streaming_transcribe(data_array,
                                                                            is_last=False,
                                                                            is_first=True)
                    # Now first pass has been performed
                    is_first_pass = False

                    # Gather new data buffer
                    data_array = []
                    is_first_data = True
            else:

                # If is last, we do not care about general sample requirement but just pass it through
                if is_last:
                    output = self.danspeech_recognizer.streaming_transcribe(data_array,
                                                                            is_last=is_last,
                                                                            is_first=False)
                    # Gather new data buffer
                    data_array = []
                    is_first_data = True

                # General case! We need some data.
                elif len(data_array) >= general_sample_requirement:
                    output = self.danspeech_recognizer.streaming_transcribe(data_array,
                                                                            is_last=is_last,
                                                                            is_first=False)

                    # Gather new data buffer
                    data_array = []
                    is_first_data = True

            # Is last should always generate output!
            if is_last and output:
                yield is_last, output

            elif output:
                yield is_last, output
                output = None

            # Reset streaminng
            if is_last:
                is_first_pass = True
                is_last = False
                output = None

    async def listen(self, source, timeout=None, phrase_time_limit=None):
        """
        Source: https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/__init__.py
        Modified for DanSpeech.

        Listens to a stream of audio.

        """
        assert isinstance(source, SpeechSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before listening, see documentation for ``AudioSource``; are you using ``source`` outside of a ``with`` statement?"
        assert self.pause_threshold >= self.non_speaking_duration >= 0

        seconds_per_buffer = float(source.chunk) / source.sampling_rate
        pause_buffer_count = int(math.ceil(
            self.pause_threshold / seconds_per_buffer))  # number of buffers of non-speaking audio during a phrase, before the phrase should be considered complete
        phrase_buffer_count = int(math.ceil(
            self.phrase_threshold / seconds_per_buffer))  # minimum number of buffers of speaking audio before we consider the speaking audio a phrase
        non_speaking_buffer_count = int(math.ceil(
            self.non_speaking_duration / seconds_per_buffer))  # maximum number of buffers of non-speaking audio to retain before and after a phrase

        # read audio input for phrases until there is a phrase that is long enough
        elapsed_time = 0  # number of seconds of audio read

        while True:
            await asyncio.sleep(0)
            frames = collections.deque()

            # store audio input until the phrase starts
            while True:
                await asyncio.sleep(0.02)
                # handle waiting too long for phrase by raising an exception
                elapsed_time += seconds_per_buffer
                if timeout and elapsed_time > timeout:
                    raise WaitTimeoutError("listening timed out while waiting for phrase to start")

                buffer = source.stream.read(source.chunk)
                if len(buffer) == 0: break  # reached end of the stream
                frames.append(buffer)
                if len(
                        frames) > non_speaking_buffer_count:  # ensure we only keep the needed amount of non-speaking buffers
                    frames.popleft()

                # detect whether speaking has started on audio input
                energy = audioop.rms(buffer, source.sampling_width)  # energy of the audio signal
                if energy > self.energy_threshold: break

                # dynamically adjust the energy threshold using asymmetric weighted average
                if self.dynamic_energy_threshold:
                    damping = self.dynamic_energy_adjustment_damping ** seconds_per_buffer  # account for different chunk sizes and rates
                    target_energy = energy * self.dynamic_energy_ratio
                    self.energy_threshold = self.energy_threshold * damping + target_energy * (1 - damping)

            # read audio input until the phrase ends
            pause_count, phrase_count = 0, 0
            phrase_start_time = elapsed_time
            while True:
                await asyncio.sleep(0)
                # handle phrase being too long by cutting off the audio
                elapsed_time += seconds_per_buffer
                if phrase_time_limit and elapsed_time - phrase_start_time > phrase_time_limit:
                    break

                buffer = source.stream.read(source.chunk)
                if len(buffer) == 0: break  # reached end of the stream
                frames.append(buffer)
                phrase_count += 1

                # check if speaking has stopped for longer than the pause threshold on the audio input
                energy = audioop.rms(buffer, source.sampling_width)  # unit energy of the audio signal within the buffer
                if energy > self.energy_threshold:
                    pause_count = 0
                else:
                    pause_count += 1
                if pause_count > pause_buffer_count:  # end of the phrase
                    break

            # check how long the detected phrase is, and retry listening if the phrase is too short
            phrase_count -= pause_count  # exclude the buffers for the pause before the phrase
            if phrase_count >= phrase_buffer_count or len(
                    buffer) == 0: break  # phrase is long enough or we've reached the end of the stream, so stop listening

        # obtain frame data
        for i in range(
                pause_count - non_speaking_buffer_count): frames.pop()  # remove extra non-speaking frames at the end
        frame_data = b"".join(frames)

        return AudioData(frame_data, source.sampling_rate, source.sampling_width)

    async def listen_stream(self, source, timeout=None, phrase_time_limit=None):
        """
        Adapted from: https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/__init__.py

        Generator used to listen to the audio from a source e.g. a microphone. This generator is used
        by the streaming models.

        :param source: Source of audio. Needs to be a Danspeech.audio.resources.SpeechSource instance
        :param frames_first: Required frames before yielding data for the first pass to the streaming model
        :param frames_rest: Minimum required frames for passes after the first pass of the streaming model.
        :param timeout: Maximum number of seconds that this will wait until a phrase starts
        :param phrase_time_limit: Maxumum number of seconds to that will allow a phrase to continue before stopping
        :return: Data and an indicator whether it is the last part of a streaming part
        """
        # ToDO: Change the assertions
        assert isinstance(source, SpeechSource), "Source must be an audio source"
        assert source.stream is not None, "Audio source must be entered before listening, " \
                                          "see documentation for ``AudioSource``; are you using " \
                                          "``source`` outside of a ``with`` statement?"
        assert self.pause_threshold >= self.non_speaking_duration >= 0

        seconds_per_buffer = float(source.chunk) / source.sampling_rate
        pause_buffer_count = int(math.ceil(
            self.pause_threshold / seconds_per_buffer))  # number of buffers of non-speaking audio during a phrase, before the phrase should be considered complete
        phrase_buffer_count = int(math.ceil(
            self.phrase_threshold / seconds_per_buffer))  # minimum number of buffers of speaking audio before we consider the speaking audio a phrase
        non_speaking_buffer_count = int(math.ceil(
            self.non_speaking_duration / seconds_per_buffer))  # maximum number of buffers of non-speaking audio to retain before and after a phrase

        # read audio input for phrases until there is a phrase that is long enough
        elapsed_time = 0  # number of seconds of audio read
        buffer = []
        while self.stream:
            await asyncio.sleep(0)
            frames = []

            # store audio input until the phrase starts
            while True and self.stream:
                await asyncio.sleep(0.2)
                # handle waiting too long for phrase by raising an exception
                elapsed_time += seconds_per_buffer
                if timeout and elapsed_time > timeout:
                    raise WaitTimeoutError("listening timed out while waiting for phrase to start")

                print("reading from stream")
                print(source.chunk)
                print(source.stream)
                try:
                    buffer = source.stream.read(source.chunk)
                except Exception as e:
                    print("fuck - " + str(e))
                if len(buffer) == 0:
                    break  # reached end of the stream
                frames.append(buffer)

                if len(frames) > non_speaking_buffer_count:
                    # ensure we only keep the needed amount of non-speaking buffers
                    frames.pop(0)

                # detect whether speaking has started on audio input
                energy = audioop.rms(buffer, source.sampling_width)  # energy of the audio signal
                if energy > self.energy_threshold:
                    break

            # If streaming has stopped while looking for speech, break out of thread so it can stop
            if not self.stream:
                yield False, []

            # Yield the silence in the beginning
            yield False, frames

            # read audio input until the phrase ends
            pause_count, phrase_count = 0, 0
            phrase_start_time = elapsed_time
            while True:
                await asyncio.sleep(0.2)
                buffer = source.stream.read(source.chunk)
                if len(buffer) == 0:
                    break  # reached end of the stream

                # handle phrase being too long by cutting off the audio
                elapsed_time += seconds_per_buffer
                if phrase_time_limit and elapsed_time - phrase_start_time > phrase_time_limit:
                    break

                phrase_count += 1

                # check if speaking has stopped for longer than the pause threshold on the audio input
                energy = audioop.rms(buffer, source.sampling_width)  # unit energy of the audio signal within the buffer

                if energy > self.energy_threshold:
                    pause_count = 0
                else:
                    pause_count += 1

                if pause_count > pause_buffer_count:  # end of the phrase
                    break

                # If data is being processed
                yield False, buffer

            # check how long the detected phrase is, and retry listening if the phrase is too short
            phrase_count -= pause_count  # exclude the buffers for the pause before the phrase
            if phrase_count >= phrase_buffer_count or len(buffer) == 0:
                break  # phrase is long enough or we've reached the end of the stream, so stop listening

        # Ending of stream, should start a new stream
        if len(buffer) == 0:
            yield True, []
        else:
            yield True, buffer

        # If we go here, then it is wrong usage of stream
        raise WrongUsageOfListen("Wrong usage of stream. Overwrite the listen generator with a new generator instance"
                                 "since this instance has completed a full listen.")


class DanSpeecher():
    def __init__(self, mic: Microphone):
        # Variables
        self.transcribing = False

        # Init a microphone object
        self.m = mic

        # Init a DanSpeech model and create a Recognizer instance
        self.model = TransferLearned()
        self.recognizer = Recognizer(model=self.model)
        # self.recognizer = CustomRecognizer(model=self.model)

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

    # async def adjust(self):
    #     logger.info("Speak a lot to adjust silence detection from microphone...")
    #     with self.m as source:
    #         await self.recognizer.adjust_for_speech(source, duration=5)

    # async def createGenerator(self):
    #     # Create the streaming generator which runs a background thread listening to the microphone stream
    #     self.generator = self.recognizer.streaming(source=self.m)
    #
    # async def get_transcription(self):
    #     # return next(self.generator)
    #     print("get_transcription")
    #     return await(self.generator.__anext__())
    #
    # async def startTranscriber(self, emitter: EventEmitter):
    #     self.transcribing = True
    #     while True:
    #         if not self.transcribing:
    #             break
    #         transcription = await self.get_transcription()
    #         logger.debug("Transcription: " + str(transcription))
    #         emitter.emit("command", transcription)

    def adjust(self):
        logger.info("Speak a lot to adjust silence detection from microphone...")
        with self.m as source:
            self.recognizer.adjust_for_speech(source, duration=5)

    def createGenerator(self):
        # Create the streaming generator which runs a background thread listening to the microphone stream
        try:
            self.generator = self.recognizer.streaming(source=self.m)
        except Exception as e:
            logger.error("bbbb - " + str(e))

    def get_transcription(self):
        logger.debug("get_transcription")
        try:
            return next(self.generator)
        except Exception as e:
            logger.error("error getting transcription - " + str(e))

    def startTranscriber(self, emitter: EventEmitter):
        self.transcribing = True
        while True:
            if not self.transcribing:
                logger.debug("breaking")
                break
            transcription = self.get_transcription()
            logger.info("Transcription: " + str(transcription))
            if transcription:
                emitter.emit("command", transcription)

    def stop(self):
        self.transcribing = False
