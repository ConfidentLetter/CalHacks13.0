import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_loads_parent_env_alias_and_uses_browser_capture(tmp_path):
    (tmp_path / '.env').write_text('anthropic_key=placeholder-for-test\n')
    repo = tmp_path / 'synapse'
    repo.mkdir()
    spec = importlib.util.spec_from_file_location('launcher', ROOT / 'run_studbud.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.dict(os.environ, {}, clear=True):
        module.configure_environment(repo)
        assert os.environ['ANTHROPIC_API_KEY'] == 'placeholder-for-test'
        assert os.environ['SV_SOURCE'] == 'upload'
        assert os.environ['SV_CAMERA_PROBE'] == '0'
        assert os.environ['SV_STT'] == '1'


def test_launcher_respects_explicit_speech_transcription_disable(tmp_path):
    spec = importlib.util.spec_from_file_location('launcher_stt', ROOT / 'run_studbud.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.dict(os.environ, {'SV_STT': '0'}, clear=True):
        module.configure_environment(tmp_path)
        assert os.environ['SV_STT'] == '0'


def test_frontend_refresh_removes_stale_source_but_preserves_dependencies(tmp_path):
    spec = importlib.util.spec_from_file_location('launcher_sync', ROOT / 'run_studbud.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo = tmp_path / 'repo'
    source = repo / 'frontend'
    (source / 'src').mkdir(parents=True)
    (source / 'src/current.js').write_text('export const current = true')
    (source / 'package-lock.json').write_text('{}')
    (source / '.env').write_text('ANTHROPIC_API_KEY=test-placeholder-only')
    runtime = tmp_path / 'data/web'
    (runtime / 'src').mkdir(parents=True)
    (runtime / 'src/obsolete.js').write_text('obsolete')
    (runtime / 'node_modules').mkdir()
    (runtime / 'node_modules/keep.txt').write_text('dependency')
    with patch.object(module, 'ROOT', repo):
        with patch.dict(os.environ, {'STUDBUD_DATA_DIR': str(tmp_path / 'data')}):
            with patch.object(module.shutil, 'which', return_value='/test/npm'):
                with patch.object(module.subprocess, 'run'):
                    module.frontend(5173)
    assert not (runtime / 'src/obsolete.js').exists()
    assert (runtime / 'src/current.js').read_text() == 'export const current = true'
    assert (runtime / 'node_modules/keep.txt').read_text() == 'dependency'
    assert not (runtime / '.env').exists()
    assert (source / 'src/current.js').exists()
