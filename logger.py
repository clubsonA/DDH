import logging
import colorlog

log_colors = {
    'DEBUG':    'cyan',
    'INFO':     'green',
    'WARNING':  'yellow',
    'ERROR':    'red',
    'CRITICAL': 'bold_red',
}

formatter = colorlog.ColoredFormatter(
    fmt='%(log_color)s[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%d-%m-%Y %H:%M:%S',
    log_colors=log_colors
)

stream_handler = colorlog.StreamHandler()
stream_handler.setFormatter(formatter)

file_handler = logging.FileHandler("delta_hedger.log", mode='a', encoding='utf-8')
file_handler.setFormatter(logging.Formatter(
    fmt='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%d-%m-%Y %H:%M:%S'
))

logger = logging.getLogger("delta_hedger")
logger.setLevel(logging.DEBUG)
#logger.addHandler(stream_handler)
logger.addHandler(file_handler)
