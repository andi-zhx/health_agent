"""Create a private Python environment for the Windows double-click entry points."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def prepare_environment():
    if not (3, 10) <= sys.version_info[:2] <= (3, 14):
        raise RuntimeError('Please install 64-bit Python 3.10 to 3.14 (3.12 recommended).')
    env_dir = ROOT / '.venv'
    python = env_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Creating local Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(env_dir)
    requirements = ROOT / 'requirements.txt'
    stamp = env_dir / '.requirements.sha256'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    current = stamp.read_text().strip() if stamp.exists() else ''
    if current != digest:
        print('Installing dependencies. The first launch needs internet access...', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '--only-binary=:all:',
                        '-r', str(requirements)], cwd=ROOT, check=True)
        subprocess.run([str(python), '-m', 'pip', 'check'], cwd=ROOT, check=True)
        stamp.write_text(digest, encoding='ascii')
    return python


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install-only', action='store_true')
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    try:
        python = prepare_environment()
        if args.install_only:
            print('Ready. Run the startup .bat file to open the app.')
            return 0
        env = os.environ.copy()
        if args.demo:
            data_dir = ROOT / 'demo_v2_data'
            subprocess.run([str(python), str(ROOT / 'seed_demo_v2.py'), '--data-dir', str(data_dir)], cwd=ROOT, check=True)
            env['HEALTH_AGENT_DATA_DIR'] = str(data_dir)
            env['APP_PORT'] = '5050'
        return subprocess.call([str(python), str(ROOT / 'launch.py')], cwd=ROOT, env=env)
    except Exception as error:
        print('Setup failed: %s' % error, file=sys.stderr)
        print('Check your Python version, network, and folder write permissions.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
