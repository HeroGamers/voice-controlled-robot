import asyncio
import concurrent
import json
import logging
import os
import re
import subprocess
import threading
import uuid
import platform
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay
from pymitter import EventEmitter
import SpeechManager

ROOT = os.path.dirname(__file__)

logger = logging.getLogger("pc")
pcs = set()
players = []
relay = MediaRelay()

RTCMessage = EventEmitter()
enableOnBoardSpeechRecognizion = False

audio = None
video = None
client_audio = None
danspeecher = None


def init(log_level):
    logging.basicConfig(level=log_level)


def getLocalMedia(params):
    def get_device_list_dshow():
        """
        Code to get get device name list under windows directshow from ffmpeg
        From https://pyacq.readthedocs.io/en/latest/_modules/pyacq/devices/webcam_av.html
        """
        cmd = "ffmpeg -list_devices true -f dshow -i dummy"
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        txt = proc.stdout.read().decode('ascii')
        txt = txt.split("DirectShow video devices")[1].split("DirectShow audio devices")[0]
        pattern = '"([^"]*)"'
        l = re.findall(pattern, txt, )
        l = [e for e in l if not e.startswith('@')]
        return l

    global relay, audio, video

    audio = None
    video = None

    camera_num = 0
    options = {"framerate": params["video_fps"], "video_size": params["video_res"], "rtbufsize": params["video_buffer"]}

    if platform.system() == "Darwin":
        video = MediaPlayer(
            "default:none", format="avfoundation", options=options
        )
    elif platform.system() == "Windows":
        dev_names = get_device_list_dshow()
        print("Cameras: ", dev_names)
        video = MediaPlayer("video={}".format(dev_names[camera_num]), format='dshow', options=options)
    else:
        video = MediaPlayer('/dev/video{}'.format(camera_num), format="v4l2", options=options)
    players.append(video)

    # if not audio:
    #     test_audio = random.randint(0, 1)
    #     if test_audio == 0:
    #         audio = MediaPlayer(os.path.join(ROOT, "public/totally_not_a_rickroll.flac"))
    #     elif test_audio == 1:
    #         audio = MediaPlayer(os.path.join(ROOT, "public/Raining Tacos - Parry Gripp & BooneBum.mp3"))
    # players.append(audio)

    return audio, relay.subscribe(video.video)


def addMediaTracks(pc, params):
    global audio, video, players

    # if not players:
    #     audio, video = getLocalMedia(params)

    for t in pc.getTransceivers():
        if t.kind == "audio" and audio:
            logger.info(msg="adding audio")
            if audio.audio:
                pc.addTrack(relay.subscribe(audio.audio))
        elif t.kind == "video" and video:
            logger.info(msg="adding video")
            pc.addTrack(video)


async def offer(request):
    global pcs
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pc_id = "PeerConnection(%s)" % uuid.uuid4()
    pcs.add(pc)

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    log_info("Created for %s", request.remote)

    # recorder = MediaRecorder("./temp_media/temp_audio.wav")

    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                if message.startswith("ping"):
                    channel.send("pong" + message[4:])
                elif message.startswith("command"):
                    command = message[9:].strip()
                    logger.info("Command received: " + command)
                    RTCMessage.emit("command", command)

    async def close():
        global pcs
        if pc in pcs:
            pcs.discard(pc)
            await pc.close()

        # If there are no more connections left
        if not pcs:
            logger.info("No more connections left - stopping players")
            for player in players:
                try:
                    player.video.stop()
                except Exception as e:
                    logger.info(str(e))

                try:
                    player.audio.stop()
                except Exception as e:
                    logger.info(str(e))
                players.remove(player)

    async def speechRecognizion(track):
        global danspeecher
        if not danspeecher:
            log_info("Creating danspeecher")
                # loop.run_in_executor(executor, speechRecognizion, client_audio)

                # loop = asyncio.new_event_loop()
                # asyncio.set_event_loop(loop)
            print("trackstream")
            trackStream = SpeechManager.TrackStream(track)
            await trackStream.intializeStream()
            # Run on another thread - so we can continue
            asyncio.ensure_future(trackStream.writeToStream())
                # Run on another thread - so we can continue
                # threading.Thread(target=sendAudio, args=(client_audio, stream), daemon=True)
                # loop.run_in_executor(pool, sendAudio, client_audio, stream)
                # loop.run_in_executor(executor, asyncio.ensure_future, sendAudio(client_audio, stream))
                # executor.submit(sendAudio, client_audio, stream)

            await asyncio.sleep(1)
            print("micsetup")
            mic = SpeechManager.MicInput(sampling_rate=trackStream.samp_rate, pyaudio_stream=trackStream.stream)

            def doDanSpeecher():
                danSpeecher = SpeechManager.DanSpeecher(mic=mic)
                # danSpeecher.adjust()
                # danSpeecher.createGenerator()
                # danSpeecher.startTranscriber(RTCMessage)

                t1 = threading.Thread(target=danSpeecher.adjust, daemon=True)
                print("running adjuster task")
                t1.start()
                t1.join()
                t2 = threading.Thread(target=danSpeecher.createGenerator, daemon=True)
                print("running generator task")
                t2.start()
                t2.join()
                t3 = threading.Thread(target=danSpeecher.startTranscriber, args=(RTCMessage,), daemon=True)
                print("running transcriber task")
                t3.start()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(executor, doDanSpeecher)



            # executor = concurrent.futures.ProcessPoolExecutor(2)
            #     danspeecherFuture = asyncio.ensure_future(loop.run_in_executor(executor, SpeechManager.DanSpeecher, mic))

                # danSpeecher = await newloop.run_in_executor(executor, SpeechManager.DanSpeecher, mic)
                # danSpeecher = await asyncio.wait([SpeechManager.DanSpeecher(mic=mic)])
                # danSpeecher = SpeechManager.DanSpeecher(mic=mic)
                # await danSpeecher.adjust()
                # await danSpeecher.createGenerator()
                # await danSpeecher.startTranscriber(RTCMessage)

                # Run on another thread - so we can continue
                # newloop.run_in_executor(executor, danSpeecher.startTranscriber, RTCMessage)
            # threading.Thread(target=danspeecher.startTranscriber, args=(RTCMessage,), daemon=True)
            # danspeecher.startTranscriber(RTCMessage)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state is %s", pc.connectionState)
        if pc.connectionState == "failed":
            await close()
        if pc.connectionState == "connected":
            if client_audio:
                if enableOnBoardSpeechRecognizion:
                    if not danspeecher:
                        await speechRecognizion(client_audio)
                else:
                    print("On board speech recognition is disabled.")

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        log_info("ICE connection state %s", pc.iceConnectionState)

        if pc.iceConnectionState == "failed":
            await close()

    @pc.on("track")
    def on_track(track):
        log_info("Track %s received", track.kind)

        if track.kind == "audio":
            global client_audio
            client_audio = track

        @track.on("ended")
        async def on_ended():
            log_info("Track %s ended", track.kind)

    # handle offer
    await pc.setRemoteDescription(offer)

    # prepare local media
    addMediaTracks(pc, params)

    # send answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return json.dumps(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    )


async def on_shutdown():
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

    global danspeecher
    if danspeecher:
        danspeecher.stop()
