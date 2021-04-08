import asyncio
import json
import logging
import os
import re
import subprocess
import uuid
import platform

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay

ROOT = os.path.dirname(__file__)

logger = logging.getLogger("pc")
pcs = set()
relay = MediaRelay()

audio = None
video = None


def init(log_level):
    logging.basicConfig(level=log_level)


def getLocalMedia():
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

    player = None

    camera_num = 0
    options = {"framerate": "30", "video_size": "640x480", "rtbufsize": "1024M"}

    if platform.system() == "Darwin":
        player = MediaPlayer(
            "default:none", format="avfoundation", options=options
        )
    elif platform.system() == "Windows":
        dev_names = get_device_list_dshow()
        player = MediaPlayer("video={}".format(dev_names[camera_num]), format='dshow', options=options)
    else:
        player = MediaPlayer('/dev/video{}'.format(camera_num), format="v4l2", options=options)
    return None, relay.subscribe(player.video)


def addMediaTracks(pc):
    global audio, video

    for t in pc.getTransceivers():
        if t.kind == "audio":
            logger.info(msg="Yay audio")
            if not audio:
                audio = MediaPlayer(os.path.join(ROOT, "public/totally_not_a_rickroll.flac")).audio
            pc.addTrack(audio)
        elif t.kind == "video" and video:
            logger.info(msg="Yay video")
            pc.addTrack(video)


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pc_id = "PeerConnection(%s)" % uuid.uuid4()
    pcs.add(pc)

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    log_info("Created for %s", request.remote)

    global audio, video
    audio, video = getLocalMedia()

    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                if message.startswith("ping"):
                    channel.send("pong" + message[4:])
                elif message.startswith("command"):
                    logger.info("Command received: " + message[7:].strip())

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state is %s", pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        log_info("Track %s received", track.kind)

        @track.on("ended")
        async def on_ended():
            log_info("Track %s ended", track.kind)

    # handle offer
    await pc.setRemoteDescription(offer)

    # prepare local media
    addMediaTracks(pc)

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
