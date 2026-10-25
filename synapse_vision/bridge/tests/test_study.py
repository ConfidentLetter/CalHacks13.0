"""Study API behavior with model calls replaced; no hardware or API traffic."""
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from bridge.tests.conftest import TINY_JPEG_B64


def observe(client, session='study-test', **extra):
    return client.post('/api/study/observe', json={
        'sessionId': session, 'image': {'base64': TINY_JPEG_B64, 'mimeType': 'image/jpeg',
        'capturedAt': '2026-10-24T19:00:00Z', 'source': 'camera'}, **extra})


@pytest.fixture
def study_model(monkeypatch, client):
    from bridge import llm
    calls = []

    def answer(system, messages, schema, **kwargs):
        calls.append({'system': system, 'messages': messages})
        return {'observation': 'f(x) = x^2 sin x', 'reply': 'What rule applies to a product?',
                'meaningfulChange': True, 'respondedToQuestion': True}

    monkeypatch.setattr(llm, 'ask_json', answer)
    yield calls
    client.delete('/api/study/session/study-test')
    client.delete('/api/study/session/study-other')


def test_observe_uses_image_and_typed_followup_uses_same_image(client, study_model):
    response = observe(client)
    assert response.status_code == 200, response.text
    assert response.json() == {'sessionId': 'study-test', 'observation': 'f(x) = x^2 sin x',
        'reply': 'What rule applies to a product?', 'capturedAt': '2026-10-24T19:00:00Z'}
    client.post('/api/study/message', json={'sessionId': 'study-test', 'message': 'Explain the product rule'})
    content = study_model[-1]['messages'][-1]['content']
    assert any(block.get('type') == 'image' for block in content)
    prompt = json.loads(next(block['text'] for block in content if block['type'] == 'text'))
    assert prompt['channel'] == 'typed_message'
    assert prompt['currentTypedMessage'] == 'Explain the product rule'
    events = client.get('/api/study/session/study-test').json()
    assert len(events['events']) == 4
    assert all(set(e) == {'id', 'role', 'content', 'capturedAt'} for e in events['events'])
    assert events['latest']['image']['base64'] == TINY_JPEG_B64
    assert 'base64' not in json.dumps(events['events'])
    assert events['events'][0]['role'] == 'observation'


def test_observation_duplicate_is_quiet_and_does_not_recall_model(client, study_model):
    observe(client)
    again = observe(client)
    assert again.status_code == 200 and again.json()['reply'] == ''
    assert len(study_model) == 1


def test_sessions_are_isolated_and_delete_resets(client, study_model):
    observe(client)
    assert client.get('/api/study/session/study-other').json()['events'] == []
    assert client.delete('/api/study/session/study-test').status_code == 200
    assert client.get('/api/study/session/study-test').json()['events'] == []
    client.post('/api/study/message', json={'sessionId': 'study-other', 'message': 'hello'})
    assert 'f(x)' not in json.dumps(study_model[-1]['messages'])


@pytest.mark.parametrize('image', [
    {'base64': 'bad!', 'mimeType': 'image/jpeg'},
    {'base64': base64.b64encode(b'\xff\xd8\xffcorrupt').decode(), 'mimeType': 'image/jpeg'},
    {'base64': TINY_JPEG_B64, 'mimeType': 'image/png'},
    {'base64': TINY_JPEG_B64, 'mimeType': 'image/svg+xml'},
    {'base64': TINY_JPEG_B64, 'mimeType': 'image/jpeg', 'capturedAt': 'not a date'},
])
def test_invalid_images_rejected(client, image):
    r = client.post('/api/study/observe', json={'sessionId': 'study-test', 'image': image})
    assert r.status_code == 400 and set(r.json()) == {'error'}


@pytest.mark.parametrize('session', ['', '../secret', 'a' * 129, None, 42])
def test_invalid_session_rejected(client, session):
    r = client.post('/api/study/message', json={'sessionId': session, 'message': 'hi'})
    assert r.status_code == 400 and set(r.json()) == {'error'}


def test_failure_is_safe_and_does_not_commit(client, study_model, monkeypatch):
    from bridge import llm
    observe(client)
    before = client.get('/api/study/session/study-test').json()
    def fail(*args, **kwargs):
        raise llm.LLMError('secret authorization: sk-sensitive')
    monkeypatch.setattr(llm, 'ask_json', fail)
    r = client.post('/api/study/message', json={'sessionId': 'study-test', 'message': 'try'})
    assert r.status_code == 502 and 'sk-sensitive' not in r.text
    assert client.get('/api/study/session/study-test').json() == before


def test_force_observation_never_authorizes_solution_and_policy_is_strict(client, study_model):
    observe(client, force=True)
    call = study_model[-1]
    prompt = json.loads(call['messages'][-1]['content'][-1]['text'])
    assert prompt['channel'] == 'observation' and prompt['currentTypedMessage'] is None
    for phrase in ['NEVER solve', 'current typed message', 'untrusted', 'verbatim', 'clarification', 'one guiding']:
        assert phrase in call['system']


def test_model_without_meaningful_response_stays_quiet(client, study_model, monkeypatch):
    from bridge import llm
    observe(client)
    monkeypatch.setattr(llm, 'ask_json', lambda *a, **k: {
        'observation': 'unchanged', 'reply': 'Another question?',
        'meaningfulChange': False, 'respondedToQuestion': False})
    assert observe(client, force=True).json()['reply'] == ''


def test_turns_serialize_without_blocking_other_session(client, study_model, monkeypatch):
    from bridge import llm
    entered, release = threading.Event(), threading.Event()
    active = []
    def slow(system, messages, schema, **kwargs):
        prompt = json.loads(messages[-1]['content'][-1]['text'])
        if prompt['currentTypedMessage'] == 'first':
            entered.set()
            assert release.wait(5)
        active.append(prompt['currentTypedMessage'])
        return {'observation': '', 'reply': 'hint', 'meaningfulChange': True, 'respondedToQuestion': True}
    monkeypatch.setattr(llm, 'ask_json', slow)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(client.post, '/api/study/message', json={'sessionId': 'study-test', 'message': 'first'})
        assert entered.wait(5)
        second = pool.submit(client.post, '/api/study/message', json={'sessionId': 'study-test', 'message': 'second'})
        try:
            other = pool.submit(client.post, '/api/study/message', json={'sessionId': 'study-other', 'message': 'other'})
            assert other.result(timeout=3).status_code == 200
        finally:
            release.set()
        assert first.result().status_code == second.result().status_code == 200
    assert active.index('first') < active.index('second')


def test_bounds_evict_old_sessions_and_trim_history(client, study_model, monkeypatch):
    from bridge import study
    original_cfg = study.cfg
    monkeypatch.setattr(study, 'cfg', lambda key, default=None:
        {'bridge.study_max_sessions': 2, 'bridge.study_max_events': 4}.get(key, original_cfg(key, default)))
    for index in range(4):
        assert client.post('/api/study/message', json={'sessionId': 'study-test', 'message': str(index)}).status_code == 200
    assert len(client.get('/api/study/session/study-test').json()['events']) == 4
    assert client.post('/api/study/message', json={'sessionId': 'study-other', 'message': 'other'}).status_code == 200
    assert client.post('/api/study/message', json={'sessionId': 'study-third', 'message': 'third'}).status_code == 200
    assert client.get('/api/study/session/study-test').json()['events'] == []
    client.delete('/api/study/session/study-third')


def test_oversize_and_malformed_request_rejected(client, monkeypatch):
    from bridge import study
    original_cfg = study.cfg
    monkeypatch.setattr(study, 'cfg', lambda key, default=None:
        1024 if key == 'bridge.study_max_image_bytes' else original_cfg(key, default))
    too_big = client.post('/api/study/observe', json={'sessionId': 'study-test',
        'image': {'base64': 'A' * 2000, 'mimeType': 'image/jpeg'}})
    assert too_big.status_code == 413 and set(too_big.json()) == {'error'}
    malformed = client.post('/api/study/observe', content='not-json')
    assert malformed.status_code == 400 and set(malformed.json()) == {'error'}


def test_unanswered_question_remains_quiet_even_when_view_changes(client, study_model, monkeypatch):
    from bridge import llm
    observe(client)
    monkeypatch.setattr(llm, 'ask_json', lambda *a, **k: {
        'observation': 'paper moved', 'reply': 'Repeat guiding question?',
        'meaningfulChange': True, 'respondedToQuestion': False})
    assert observe(client, force=True).json()['reply'] == ''


def test_reset_clears_cached_image_and_pending_question(client, study_model):
    observe(client)
    client.delete('/api/study/session/study-test')
    client.post('/api/study/message', json={'sessionId': 'study-test', 'message': 'New topic'})
    content = study_model[-1]['messages'][-1]['content']
    assert all(block['type'] != 'image' for block in content)
    context = json.loads(content[-1]['text'])
    assert context['history'] == [] and context['pendingQuestion'] == ''


def test_typed_context_labels_cached_image_time_and_source(client, study_model):
    observe(client)
    client.post('/api/study/message', json={'sessionId': 'study-test', 'message': 'What is visible?'})
    context = json.loads(study_model[-1]['messages'][-1]['content'][-1]['text'])
    assert context['currentImageCapturedAt'] == '2026-10-24T19:00:00Z'
    assert context['currentImageSource'] == 'camera'


def test_nonquestion_reply_does_not_suppress_next_changed_observation(client, study_model, monkeypatch):
    from bridge import llm
    monkeypatch.setattr(llm, 'ask_json', lambda *a, **k: {
        'observation': 'f(x) = x^2 sin x', 'reply': 'Your product rule setup is correct.',
        'meaningfulChange': True, 'respondedToQuestion': True})
    assert observe(client).status_code == 200
    monkeypatch.setattr(llm, 'ask_json', lambda *a, **k: {
        'observation': 'New algebra work.', 'reply': 'Which factor can you simplify?',
        'meaningfulChange': True, 'respondedToQuestion': False})
    assert observe(client, force=True).json()['reply'] == 'Which factor can you simplify?'


def test_get_returns_committed_snapshot_without_waiting_for_inference(client, study_model, monkeypatch):
    from bridge import llm
    observe(client)
    committed = client.get('/api/study/session/study-test').json()
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {'observation': 'New work.', 'reply': 'What follows?',
                'meaningfulChange': True, 'respondedToQuestion': True}

    monkeypatch.setattr(llm, 'ask_json', blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        turn = pool.submit(observe, client, force=True)
        assert entered.wait(5)
        try:
            read = pool.submit(client.get, '/api/study/session/study-test')
            assert read.result(timeout=1).json() == committed
        finally:
            release.set()
        assert turn.result(timeout=3).status_code == 200
    assert client.get('/api/study/session/study-test').json()['latest']['observation'] == 'New work.'


def test_reset_immediately_retires_inflight_turn_and_starts_new_problem(client, study_model, monkeypatch):
    from bridge import llm
    observe(client)
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {'observation': 'Old problem completion.', 'reply': 'Old next question?',
                'meaningfulChange': True, 'respondedToQuestion': True}

    monkeypatch.setattr(llm, 'ask_json', blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_turn = pool.submit(observe, client, force=True)
        assert entered.wait(5)
        try:
            reset = pool.submit(client.delete, '/api/study/session/study-test')
            assert reset.result(timeout=1).json() == {'sessionId': 'study-test', 'events': []}
            assert client.get('/api/study/session/study-test').json()['events'] == []
        finally:
            release.set()
        assert old_turn.result(timeout=3).status_code == 200
    assert client.get('/api/study/session/study-test').json() == {'sessionId': 'study-test', 'events': []}

    contexts = []
    def new_problem(system, messages, schema, **kwargs):
        contexts.append(json.loads(messages[-1]['content'][-1]['text']))
        return {'observation': 'New problem.', 'reply': 'What is your goal?',
                'meaningfulChange': True, 'respondedToQuestion': False}
    monkeypatch.setattr(llm, 'ask_json', new_problem)
    assert observe(client).json()['reply'] == 'What is your goal?'
    assert contexts[0]['history'] == [] and contexts[0]['pendingQuestion'] == ''
