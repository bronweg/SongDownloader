import os
import re
import math
import socket
import subprocess
from threading import Thread
import contextlib


class ListenerParser(Thread):
    def __init__(self, connection, final_duration, count_str, progress_callback, **kwargs):
        super().__init__(**kwargs)
        self.connection = connection
        self.final_duration = final_duration
        self.count_str = count_str
        self.progress_callback = progress_callback


    def run(self):
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
            print('VETOCHKA ANOTHER CONNECTION CLOSED')


    def parse_ffmpeg_data(self, line):
        line = line.decode()
        parts = line.split('=')
        key = parts[0] if len(parts) > 0 else None
        value = parts[1] if len(parts) > 1 else None
        if key == 'out_time_ms':
            duration = int(value) / 1000000 if value.isdigit() else 0
            updateProgress(duration, self.final_duration, self.progress_callback,
                           label='postprocess', part_n=2, part_i=1, count=self.count_str)
        elif key == 'progress' and value == 'end':
            updateProgressPercent(100, self.progress_callback,
                                  label='postprocess', part_n=2, part_i=1, count=self.count_str)


class ListenerThread(Thread):
    def __init__(self, sock, listen_on, progress_callback, **kwargs):
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

    def set_info(self, duration, current, total, length):
        self.final_duration = duration
        self.current = current
        self.total = total
        self.length = length

    def run(self):
        while True:
            try:
                connection, client_address = self.sock.accept()
                print('VETOCHKA ANOTHER CONNECTION OPENED')
                self.parsers.append(ListenerParser(
                    connection, self.final_duration, self.get_count_str(), self.progress_callback
                ))
                self.parsers[-1].start()
            except (ConnectionAbortedError, OSError) as e:
                print('VETOCHKA SOCKET CLOSED')
                return


    def get_count_str(self):
        return f'{str(self.current)}/{str(self.total)}'

    def parse_yt_dlp_data(self, line):
        line = line.decode()
        info_pattern = ',\\s+'.join((
            'duration:(?P<duration>\\d+(\\.\\d+))',
            'current:(?P<current>\\d+)',
            'total:(?P<total>\\d+)',
            'length:(?P<length>\\d+)',
            'max-playlist:(?P<max_playlist>-?\\d+)',
            'abort-on-long:(?P<abort_on_long>\\d+)',
        ))
        if match := re.search(info_pattern, line):
            print(f'TALELLE {line}')
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
            updateProgressPercent(float(match.group(1)), self.progress_callback, label='download',
                                  part_n=self.part_n, part_i=0, count=self.get_count_str())


@contextlib.contextmanager
def get_progress_listener(use_socket, progress_callback):
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


def default_progress_callback(percent, label=None, count=None):
    if label:
        print(f'REPORTING ON {label} for {count}')
    for _ in range(percent):
        print('+', end = '')
    for _ in range(percent, 100):
        print('-', end = '')
    print()


def updateProgressPercent(percent, progress_callback, label=None, part_n=1, part_i=0, count=''):
    process = label.upper() if label else 'PROCESS'
    print(f'{count} -> {process} IS DONE for {str(percent)}%')
    progress_callback(int(percent)//part_n + 100//part_n * part_i, label, count)
    return percent


def updateProgress(done, total, progress_callback, label=None, part_n=1, part_i=0, count=''):
    calculated_progress = math.floor((done / total)*100)
    process = label.upper() if label else 'PROCESS'
    print(f'{count} -> {process} IS DONE for {str(calculated_progress)}%: {str(done)} of {str(total)}')
    progress_callback(calculated_progress//part_n + 100//part_n * part_i, label, count)
    return calculated_progress


def prepare_subprocess(youtube_url, audio_only, output_path,
                       max_playlist, abort_on_long_playlist, do_postprocess,
                       progress_path):
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
            '-o', os.path.join(output_path, '%(title)s%(playlist_index&__{}|)s.%(ext)s'),
        ])
    else:
        cmd.extend([
            '-o', '%(playlist_index&_{}|)s'.join(os.path.splitext(output_path))
        ])

    kwargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE
    }
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    return cmd, kwargs



def download(youtube_url, audio_only, output_path,
             max_playlist=-1, abort_on_long_playlist=False, do_postprocess=True,
             progress_callback=default_progress_callback):

    use_ffmpeg = audio_only or do_postprocess

    with get_progress_listener(use_ffmpeg, progress_callback) as listener:
        cmd, kwargs = prepare_subprocess(youtube_url, audio_only, output_path,
                                         max_playlist, abort_on_long_playlist, do_postprocess,
                                         progress_path='http://{}'.format(listener.listen_on))
        process = subprocess.Popen(cmd, **kwargs)
        for line in process.stdout:
            if err := listener.parse_yt_dlp_data(line):
                process.terminate()
                print('VETOCHKA DOWNLOAD ABORT')
                raise ValueError(*err)
    print('VETOCHKA DOWNLOAD DONE')




if __name__ == "__main__":
    youtube_url = 'https://www.youtube.com/watch?v=YG9otasNmxI'
    # youtube_url = 'https://www.youtube.com/watch?v=-4_bi5E6Z1E'
    # youtube_url = 'https://www.youtube.com/watch?v=fSzdAGoU0vI&list=PLCC3A8CC8A65F6F64'       # short list
    # youtube_url = 'https://www.youtube.com/playlist?list=PL8-QChleIXYo1bmmKrbh5H52IsJWnJ_8L'    # long list
    # youtube_url = 'https://www.youtube.com/watch?v=cC1xVOiCAwc'
    output_mp3_path = '/Users/betty/projects/2024-03-20/talelle/song.mp3'
    output_mp4_path = '/Users/betty/projects/2024-03-20/yona'
    download(youtube_url, False, output_mp4_path)
