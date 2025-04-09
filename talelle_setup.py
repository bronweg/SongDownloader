import logging
import logging.config

import os
import shutil
from pathlib import Path

def to_path(path: str) -> Path:
    return Path(path)

TALELLE_DIR = os.path.join(os.path.expanduser('~'), 'TalelleApps')
to_path(TALELLE_DIR).mkdir(parents=True, exist_ok=True)


def config_log(talelle_tool: str):
    log_conf_name = 'logging.conf'
    local_log_conf = f'./{log_conf_name}'

    log_conf = os.path.join(TALELLE_DIR, local_log_conf)
    log_file = os.path.join(TALELLE_DIR, f'{talelle_tool}.log')

    if not os.path.exists(log_conf):
        shutil.copy(local_log_conf, log_conf)

    logging.config.fileConfig(log_conf, defaults={"log_path": log_file})