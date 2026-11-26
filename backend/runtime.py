"""Local runtime paths and persistent, installation-specific session signing key."""

import os
from pathlib import Path
import secrets
import time

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('HEALTH_AGENT_DATA_DIR', str(BASE_DIR))).expanduser().resolve()


def load_secret_key():
    configured = os.environ.get('SECRET_KEY', '').strip()
    if configured:
        return configured
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / '.secret_key'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # Another local process may still be finishing the first write.
        for _ in range(50):
            key = path.read_text(encoding='utf-8').strip()
            if len(key) >= 32:
                return key
            time.sleep(0.02)
        raise RuntimeError('本地 .secret_key 文件为空或损坏，请恢复该文件或设置 SECRET_KEY。')
    else:
        key = secrets.token_hex(32)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(key)
        return key
