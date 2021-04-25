import logging as command_logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

logger = command_logging.getLogger("CommandManager")


def setup_logger():
    if not os.path.exists("logs"):
        os.makedirs("logs")

    formatter = command_logging.Formatter(fmt='%(asctime)s %(levelname)-8s %(message)s', datefmt='%H:%M:%S')
    handler = TimedRotatingFileHandler("logs/commandLog.log", when="midnight", interval=1, encoding="UTF-8")
    handler.suffix = "%Y%m%d"
    handler.setFormatter(formatter)
    screen_handler = command_logging.StreamHandler(stream=sys.stdout)
    screen_handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.addHandler(screen_handler)
    logger.setLevel(command_logging.DEBUG)


setup_logger()


class Command:
    def __init__(self, commandDict: dict):
        self.command = commandDict["command"]
        self.distance = commandDict["distance"] if "distance" in commandDict else None
        self.number = commandDict["number"] if "number" in commandDict else None
        self.debug_words = {"commandWord": commandDict["word"],
                            "distanceWord": commandDict["distance_word"] if "distance_word" in commandDict else None,
                            "numberWord": commandDict["number_word"] if "number_word" in commandDict else None}

    # GPIO kode:
    async def run(self, robot):
        robot.current_command = self

        # Stop command
        if self.command == 0:
            # Empty queue and stop robot
            robot.running = False
            robot.queue.empty()
            # some stop stuff, to cancel a command that is currently running
            robot.stop()
        else:
            robot.running = True
            # Forward command
            if self.command == 1:
                await robot.drive(self.number*self.distance)
            # Backwards command
            elif self.command == -1:
                await robot.drive(-(self.number*self.distance))
            # Turn right command
            elif self.command == 2:
                await robot.turn(90)
            # Turn left command
            elif self.command == 3:
                await robot.turn(-90)
            # Turn 180 degrees command
            elif self.command == 4:
                await robot.turn(180)
            else:
                logger.error("fuck?")

            # Do something


class CommandQueue:
    def __init__(self):
        self.queue: [Command] = []

    def addToQueue(self, commandList: list):
        self.queue = self.queue + commandList

    def empty(self):
        self.queue = []


class CommandParser:
    def __init__(self, text: str):
        self.raw_text = text
        self.commands = []
        logger.debug("Raw text command: " + self.raw_text)
        self.textToCommands()
        logger.debug("Commands: " + str(self.commands))

    def textToCommands(self):
        # TODO: Better text to command parser
        command_keywords = {"stop": 0,
                            "frem": 1,  # "kør": 1,
                            "tilbage": -1, "baglæns": -1, "bagud": -1,
                            "højre": 2,
                            "venstre": 3}
        distance_keywords = {"millimeter": 0.001, "centimeter": 0.01,
                             "meter": 1}
        number_keywords = {"en": 1, "1": 1,
                           "to": 2, "2": 2,
                           "tre": 3, "3": 3}

        text_list = self.raw_text.split(" ")

        i = 0
        while True:
            if i >= len(text_list):
                break

            current_word = text_list[i].lower()
            # If our word is in commands
            if current_word in command_keywords:
                logger.debug(text_list)
                logger.debug("Current i: " + str(i) + " - " + str(current_word))
                if command_keywords[current_word] == 0 or command_keywords[current_word] == 100:
                    self.commands.append(Command({"command": command_keywords[current_word], "word": current_word}))
                    text_list.pop(i)
                    # do not increment i
                    continue

                # set defaults
                command = {"command": command_keywords[current_word], "word": current_word,
                           "distance": 100, "distance_word": None,
                           "number": 1, "number_word": None}

                def searchAround(keyword_list: dict, max_search: int = 2, negative=False):
                    for y in range(1, max_search + 1):
                        number = None
                        if negative and (i - y) >= 0:
                            number = i - y
                        elif not negative and (i + y) < len(text_list):
                            number = i + y

                        if isinstance(number, int):
                            current_word = text_list[number].lower()
                            if current_word in command_keywords:
                                continue
                            if current_word in keyword_list:
                                text_list.pop(number)
                                return current_word
                    return None

                # Search around word for distance keyword
                search_word = searchAround(distance_keywords, negative=True)
                if search_word:
                    command["distance"] = distance_keywords[search_word]
                    command["distance_word"] = search_word
                    i -= 1
                else:
                    search_word = searchAround(distance_keywords, negative=False)
                    if search_word:
                        command["distance"] = distance_keywords[search_word]
                        command["distance_word"] = search_word
                # Search around for number keyword
                search_word = searchAround(number_keywords, negative=True)
                if search_word:
                    command["number"] = number_keywords[search_word]
                    command["number_word"] = search_word
                    i -= 1
                else:
                    search_word = searchAround(number_keywords, negative=False)
                    if search_word:
                        command["number"] = number_keywords[search_word]
                        command["number_word"] = search_word

                self.commands.append(Command(command))
                text_list.pop(i)
            i += 1
