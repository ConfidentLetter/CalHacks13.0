"""Run the local study API, or --frontend to run the Chrome dashboard.

Credentials stay in the Python process. The frontend is copied to an internal
runtime folder because npm executables need symlinks unavailable on FAT drives.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def configure_environment(root=ROOT):
    from dotenv import load_dotenv

    load_dotenv(root / '.env')
    load_dotenv(root.parent / '.env')
    credential = (os.getenv('ANTHROPIC_API_KEY', '').strip()
                  or os.getenv('anthropic_key', '').strip())
    if credential:
        os.environ['ANTHROPIC_API_KEY'] = credential
    if os.getenv('CLAUDE_MODEL'):
        os.environ.setdefault('SV_MODEL', os.environ['CLAUDE_MODEL'])
    # The browser owns the camera, including the iPhone. Never probe or open a Pi.
    os.environ['SV_SOURCE'] = 'upload'
    os.environ['SV_CAMERA_PROBE'] = '0'
    os.environ['SV_STT'] = '0'


def frontend(port):
    npm = shutil.which('npm')
    if not npm:
        raise SystemExit('Install Node.js with npm, then run this command again.')
    default = (Path.home() / 'Library' / 'Application Support' / 'StudBud'
               if sys.platform == 'darwin' else Path.home() / '.local' / 'share' / 'studbud')
    runtime = Path(os.getenv('STUDBUD_DATA_DIR') or default).expanduser() / 'web'
    source = (ROOT / 'frontend').resolve()
    destination = runtime.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise SystemExit('The frontend runtime directory must be separate from its source tree.')
    runtime.mkdir(parents=True, exist_ok=True)
    # These directories are generated copies, never user source or npm dependencies.
    # Replace them so moved/deleted modules do not accumulate in the runtime tree.
    for name in ('src', 'public'):
        generated = runtime / name
        if generated.is_symlink():
            raise SystemExit(f'Refusing to replace a linked runtime source directory: {generated}')
        if generated.exists():
            shutil.rmtree(generated)
    shutil.copytree(source, runtime, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('node_modules', 'dist', '.git', '.env*', '._*'))
    digest = hashlib.sha256((runtime / 'package-lock.json').read_bytes()).hexdigest()
    marker = runtime / '.studbud-dependencies'
    public_env = {key: value for key, value in os.environ.items()
                  if key not in ('ANTHROPIC_API_KEY', 'anthropic_key', 'ANTHROPIC_AUTH_TOKEN')}
    if not (runtime / 'node_modules').is_dir() or not marker.exists() or marker.read_text() != digest:
        subprocess.run([npm, 'ci', '--ignore-scripts'], cwd=runtime, env=public_env, check=True)
        marker.write_text(digest)
    # Do not pass backend secrets to Vite or its child processes.
    subprocess.run([npm, 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(port), '--strictPort'],
                   cwd=runtime, env=public_env, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='StudBud local API and browser frontend')
    parser.add_argument('--frontend', action='store_true', help='run the dashboard (second terminal)')
    parser.add_argument('--port', type=int)
    args = parser.parse_args(argv)
    if args.frontend:
        frontend(args.port or 5173)
        return
    configure_environment()
    sys.path.insert(0, str(ROOT / 'synapse_vision'))
    import uvicorn

    print(f'StudBud API: http://127.0.0.1:{args.port or 8000} — camera capture happens in Chrome.')
    uvicorn.run('bridge.server:app', host='127.0.0.1', port=args.port or 8000, log_level='warning')


if __name__ == '__main__':
    main()
