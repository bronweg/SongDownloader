import logging
import os
import re
from typing import Optional, Callable

import math
import socket
import subprocess
from threading import Thread
import contextlib

logger = logging.getLogger(__name__)

class ListenerParser(Thread):
    def __init__(self, connection, final_duration, count_str, progress_callback, **kwargs):
        super().__init__(**kwargs)
        self.connection = connection
        self.final_duration = final_duration
        self.count_str = count_str
        self.progress_callback = progress_callback


    def run(self):
        logger.debug('parsing postprocess data')
        data = b''
        try:
            while True:
                more_data = self.connection.recv(16)
                if not more_data:
                    break
                data += more_data
                lines = data.split(b'\n')
                for line in lines[:-1]:
                    self.parse_ffmpeg_data(line)
                data = lines[-1]
        finally:
            self.connection.close()
            logger.debug('parsing postprocess data finished')


    def parse_ffmpeg_data(self, line: bytes):
        line = line.decode()
        parts = line.split('=')
        key = parts[0] if len(parts) > 0 else None
        value = parts[1] if len(parts) > 1 else None
        if key == 'out_time_ms':
            duration = int(value) / 1000000 if value.isdigit() else 0
            update_progress(duration, self.final_duration, self.progress_callback,
                            label='postprocess', part_n=2, part_i=1, count=self.count_str)
        elif key == 'progress' and value == 'end':
            update_progress_percent(100, self.progress_callback,
                                    label='postprocess', part_n=2, part_i=1, count=self.count_str)


class ListenerThread(Thread):
    def __init__(self, sock: Optional[socket.socket], listen_on: Optional[str], progress_callback: Callable, **kwargs):
        super().__init__(**kwargs)
        self.sock = sock
        self.listen_on = listen_on
        self.progress_callback = progress_callback
        self.part_n = 1 + (1 if self.sock else 0)
        self.final_duration = None
        self.current = 0
        self.total = 0
        self.length = 0
        self.parsers = list()

    def set_info(self, duration: float, current: int, total: int, length: int):
        self.final_duration = duration
        self.current = current
        self.total = total
        self.length = length

    def run(self):
        while True:
            try:
                connection, client_address = self.sock.accept()
                logger.debug('Postprocess process started')
                self.parsers.append(ListenerParser(
                    connection, self.final_duration, self.get_count_str(), self.progress_callback
                ))
                self.parsers[-1].start()
            except (ConnectionAbortedError, OSError) as e:
                logger.debug('Postprocess process finished')
                return


    def get_count_str(self):
        return f'{str(self.current)}/{str(self.total)}'


    def parse_yt_dlp_data(self, bin_line: bytes):
        line = bin_line.decode()
        info_pattern = ',\\s+'.join((
            'duration:(?P<duration>\\d+(\\.\\d+))',
            'current:(?P<current>\\d+)',
            'total:(?P<total>\\d+)',
            'length:(?P<length>\\d+)',
            'max-playlist:(?P<max_playlist>-?\\d+)',
            'abort-on-long:(?P<abort_on_long>\\d+)',
        ))
        if match := re.search(info_pattern, line):
            logger.info(f'Download info: {line}')
            if (int(match.group('abort_on_long')) and
                    int(match.group('length')) > int(match.group('max_playlist'))):
                return 'playlist_too_long', match.group('max_playlist'), match.group('length')
            self.set_info(
                float(match.group('duration')),
                int(match.group('current')),
                int(match.group('total')),
                int(match.group('length')),
            )
        elif match := re.search('\\[download\\]\\s+(\\d+(\\.\\d+))\\%\\s+of', line):
            update_progress_percent(float(match.group(1)), self.progress_callback, label='download',
                                    part_n=self.part_n, part_i=0, count=self.get_count_str())


@contextlib.contextmanager
def get_progress_listener(use_socket: bool, progress_callback: Callable):
    sock = type("Closable", (object,), {"close": lambda self: "closed"})
    listener = type("Joinable", (object,), {"join": lambda self: "joined" })

    try:
        if use_socket:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('localhost', 0))
            listen_on = '{}:{:d}'.format(*sock.getsockname())
            sock.listen(1)
            listener = ListenerThread(sock, listen_on, progress_callback)
            listener.start()
        else:
            listener = ListenerThread(None, None, progress_callback)
        yield listener
    finally:
        for parser in listener.parsers:
            parser.join()
        with contextlib.suppress(Exception):
            sock.close()
        with contextlib.suppress(Exception):
            listener.is_alive() and listener.join()


def default_progress_callback(percent: int, label: str=None, count: str=None):
    if label:
        print(f'REPORTING ON {label} for {count}')
    for _ in range(percent):
        print('+', end = '')
    for _ in range(percent, 100):
        print('-', end = '')
    print()


def update_progress_percent(percent: float, progress_callback: Callable,
                            label: Optional[str] = None, part_n: int = 1, part_i: int = 0, count: str = ''
                            ) -> float:
    process = label.upper() if label else 'PROCESS'
    logger.debug(f'{count} -> {process} IS DONE for {str(percent)}%')
    progress_callback(int(percent)//part_n + 100//part_n * part_i, label, count)
    return percent


def update_progress(done: float, total: float, progress_callback: Callable,
                    label: Optional[str] = None, part_n: int = 1, part_i: int = 0, count: str = '') -> int:
    calculated_progress = math.floor((done / total)*100)
    process = label.upper() if label else 'PROCESS'
    logger.debug(f'{count} -> {process} IS DONE for {str(calculated_progress)}%: {str(done)} of {str(total)}')
    progress_callback(calculated_progress//part_n + 100//part_n * part_i, label, count)
    return calculated_progress


def prepare_subprocess(youtube_url: str, audio_only: bool, output_path: str,
                       max_playlist: int, abort_on_long_playlist: bool, do_postprocess: bool,
                       progress_path: str) -> tuple[list[str], dict]:
    cmd = [
        'yt-dlp',
        '--progress', '--newline',
        #'--restrict-filenames',
        '--force-overwrites',
        '--playlist-items', f'1:{max_playlist}'
    ]

    print_info = ', '.join((
        'duration:%(duration)f',
        'current:%(playlist_autonumber|1)d',
        'total:%(n_entries|1)d',
        'length:%(playlist_count|1)d',
        f'max-playlist:{max_playlist}',
        f'abort-on-long:{int(abort_on_long_playlist)}',
    ))

    cmd.extend([
        '--print',
        print_info,
        '--no-simulate',
    ])

    if audio_only:
        cmd.extend([
            '-x', '--audio-format', 'mp3',
        ])
    else:
        cmd.extend([
            '--format', 'mp4',
            '--format-sort', 'codec:h265',
        ])
        if do_postprocess:
            cmd.extend([
                '--use-postprocessor', 'FFmpegCopyStream',
                '--postprocessor-args', "CopyStream: -c:a aac -c:v libx265 -tag:v hvc1",
            ])

    if audio_only or do_postprocess:
        cmd.extend([
            '--postprocessor-args', "ffmpeg:-progress {}".format(progress_path),
        ])

    cmd.extend([
        youtube_url,
    ])

    if not output_path or os.path.isdir(output_path):
        cmd.extend([
            '-o', os.path.join(output_path, '%(playlist_autonumber|)s%(playlist_autonumber&_|)s%(title)s.%(ext)s'),
        ])
    else:
        cmd.extend([
            '-o', os.path.join(
                os.path.dirname(output_path),
                ''.join(('%(playlist_autonumber|)s%(playlist_autonumber&_|)s', os.path.basename(output_path)))
            ),
        ])

    kwargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE
    }
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    return cmd, kwargs


def check_ffmpeg_available():
    try:
        subprocess.run(
            ['ffmpeg', '-version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, PermissionError) as e:
        logger.error('ffmpeg is not usable: %s', e)
        return False


def download(youtube_url: str, audio_only: bool, output_path: str,
             max_playlist: int = -1, abort_on_long_playlist: bool = False, do_postprocess: bool = True,
             progress_callback: Callable = default_progress_callback):

    use_ffmpeg = audio_only or do_postprocess

    if use_ffmpeg and not check_ffmpeg_available():
        raise EnvironmentError("FFmpeg is not available or not usable. Please ensure it is installed and accessible.")

    with get_progress_listener(use_ffmpeg, progress_callback) as listener:
        cmd, kwargs = prepare_subprocess(youtube_url, audio_only, output_path,
                                         max_playlist, abort_on_long_playlist, do_postprocess,
                                         progress_path='http://{}'.format(listener.listen_on))
        process = subprocess.Popen(cmd, **kwargs)
        for line in process.stdout:
            if err := listener.parse_yt_dlp_data(line):
                process.terminate()
                logger.error('error occurred when downloading: %s', err)
                raise ValueError(*err)
    logger.info('Download finished')




if __name__ == "__main__":
    # youtube_url = 'https://www.youtube.com/watch?v=YG9otasNmxI'
    # youtube_url = 'https://www.youtube.com/watch?v=-4_bi5E6Z1E'
    # youtube_url = 'https://www.youtube.com/playlist?list=PL8-QChleIXYoF73aPIswV0umaJLPJ7Jod'         # short list
    # youtube_url = 'https://www.youtube.com/playlist?list=PL8-QChleIXYo1bmmKrbh5H52IsJWnJ_8L'       # long list
    # youtube_url = 'https://www.youtube.com/watch?v=cC1xVOiCAwc'
    youtube_url = 'https://www.youtube.com/watch?v=VQX_achGHew'
    # output_mp3_path = '/Users/betty/projects/2024-03-20/talelle/song.mp3'
    output_mp3_path = '/Users/betty/projects/2025-03-25/vetochka/2025-03-25_vetochka.mp3'
    output_mp4_path = '/Users/betty/projects/2024-03-20/yona'
    # download(youtube_url, True, output_path=output_mp3_path, do_postprocess=False)
    download(youtube_url = 'https://www.youtube.com/watch?v=VQX_achGHew', audio_only = True,
             output_path = '/Users/betty/projects/2025-03-25/vetochka/2025-03-25_vetochka.mp3',
             max_playlist = 10, abort_on_long_playlist = True, do_postprocess = False)