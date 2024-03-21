import os
import re
import math
import random
import string
import socket
import subprocess
from threading import Thread
import contextlib


class ListenerThread(Thread):
    def __init__(self, sock, listen_on, progress_callback, **kwargs):
        super().__init__(**kwargs)
        self.sock = sock
        self.listen_on = listen_on
        self.progress_callback = progress_callback
        self.final_duration = None

    def set_duration(self, duration):
        self.final_duration = duration

    def run(self):
        try:
            connection, client_address = self.sock.accept()
        except socket.timeout:
            print("Timeout occurred while waiting for a connection")
            return

        data = b''
        try:
            while True:
                more_data = connection.recv(16)
                if not more_data:
                    break
                data += more_data
                lines = data.split(b'\n')
                for line in lines[:-1]:
                    self.parse_ffmpeg_data(line)
                data = lines[-1]
        finally:
            connection.close()


    def parse_ffmpeg_data(self, line):
        line = line.decode()
        parts = line.split('=')
        key = parts[0] if len(parts) > 0 else None
        value = parts[1] if len(parts) > 1 else None
        if key == 'out_time_ms':
            duration = int(value) / 1000000 if value.isdigit() else 0
            updateProgress(duration, self.final_duration, self.progress_callback,
                           label='postprocess', part_n=2, part_i=1)
        elif key == 'progress' and value == 'end':
            updateProgressPercent(100, self.progress_callback,
                                  label='postprocess', part_n=2, part_i=1)


    def parse_yt_dlp_data(self, line):
        line = line.decode()
        if match := re.search('duration:(\\d+(\\.\\d+))', line):
            self.set_duration(float(match.group(1)))
        elif match := re.search('\\[download\\]\\s+(\\d+(\\.\\d+))\\%\\s+of', line):
            updateProgressPercent(float(match.group(1)), self.progress_callback,
                                  label='download', part_n=2, part_i=0)



@contextlib.contextmanager
def get_progress_listener(progress_callback):
    HOST = 'localhost'  # Standard loopback interface address (localhost)
    PORT = 65432  # Port to listen on (non-privileged ports are > 1023)
    sock = type("Closable", (object,), {"close": lambda self: "closed"})
    listener = type("Joinable", (object,), {"join": lambda self: "joined" })

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((HOST, PORT))
        listen_on = '{}:{:d}/{}/{}'.format(
            HOST, PORT, 'mp3downloader',
            ''.join(random.choices(string.ascii_lowercase, k=8)))
        sock.settimeout(10)
        sock.listen(1)
        listener = ListenerThread(sock, listen_on, progress_callback)
        listener.start()
        yield listener
    finally:
        with contextlib.suppress(Exception):
            listener.join()
        with contextlib.suppress(Exception):
            sock.close()


def default_progress_callback(value, label=None):
    if label:
        print(f'START REPORTING ON {label}')
    for _ in range(value):
        print('+', end = '')
    for _ in range(value, 100):
        print('-', end = '')
    print()


def updateProgressPercent(percent, progress_callback, label=None, part_n=1, part_i=0):
    process = label.upper() if label else 'PROCESS'
    print(f'{process} IS DONE for {str(percent)}%')
    progress_callback(int(percent)//part_n + 100//part_n * part_i, label)
    return percent


def updateProgress(done, total, progress_callback, label=None, part_n=1, part_i=0):
    calculated_progress = math.floor((done / total)*100)
    process = label.upper() if label else 'PROCESS'
    print(f'{process} IS DONE for {str(calculated_progress)}%: {str(done)} of {str(total)}')
    progress_callback(calculated_progress//part_n + 100//part_n * part_i, label)
    return calculated_progress



def prepare_subprocess(youtube_url, output_mp3_path, progress_path):
    cmd = [
        'yt-dlp',
        '--progress', '--newline',
        '--print', 'duration:%(duration)f', '--no-simulate',
        '--restrict-filenames',
        '--force-overwrites',
        '-x', '--audio-format', 'mp3',
        '--postprocessor-args', "ffmpeg:-progress {}".format(progress_path),
        youtube_url,
        '-o', output_mp3_path
    ]

    kwargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE
    }
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    return cmd, kwargs



def download_song(youtube_url, output_mp3_path, progress_callback=default_progress_callback):
    with get_progress_listener(progress_callback) as listener:

        cmd, kwargs = prepare_subprocess(youtube_url, output_mp3_path,
                                         progress_path='http://{}'.format(listener.listen_on))
        process = subprocess.Popen(cmd, **kwargs)
        for line in process.stdout:
            listener.parse_yt_dlp_data(line)


if __name__ == "__main__":
    youtube_url = 'https://youtu.be/KFkoy5yYR0k?si=I769lfJRAKg_CIoF'
    output_mp3_path = 'song.mp3'
    download_song(youtube_url, output_mp3_path)
