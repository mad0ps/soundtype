import json, wave
import numpy as np
import pytest
from eval.run_model import decode_corpus, read_wav

def _mk_corpus(tmp_path, n=2):
    corpus = tmp_path / 'corpus'; corpus.mkdir()
    entries = []
    for i in range(n):
        cid = 'clip%d' % i
        with wave.open(str(corpus / (cid + '.wav')), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(np.full(1600, 1000, dtype=np.int16).tobytes())
        (corpus / (cid + '.ref.txt')).write_text('текст %d' % i, encoding='utf-8')
        entries.append({'id': cid, 'wav': cid + '.wav', 'ref': cid + '.ref.txt',
                        'source': 'phone', 'verified': False})
    with open(corpus / 'manifest.jsonl', 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e) + '\n')
    return corpus

def test_read_wav_scales_to_unit_float(tmp_path):
    corpus = _mk_corpus(tmp_path, n=1)
    samples = read_wav(corpus / 'clip0.wav')
    assert samples.dtype == np.float32
    assert abs(float(samples[0]) - 1000 / 32768.0) < 1e-6

def test_read_wav_rejects_wrong_sample_width(tmp_path):
    path = tmp_path / 'bad.wav'
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(1); w.setframerate(16000)  # 8-bit, not s16
        w.writeframes(np.full(1600, 200, dtype=np.uint8).tobytes())
    with pytest.raises(ValueError):
        read_wav(path)

def test_decode_corpus_writes_run_file(tmp_path):
    corpus = _mk_corpus(tmp_path)
    out = tmp_path / 'run.jsonl'
    n = decode_corpus(lambda s: 'решённый текст', corpus, out,
                      mode_label='whole', model_label='fake')
    assert n == 2
    lines = [json.loads(l) for l in open(out, encoding='utf-8')]
    assert lines[0] == {'id': 'clip0', 'hyp': 'решённый текст',
                        'model': 'fake', 'mode': 'whole'}

def test_vad_pipeline_joins_via_prod_chain():
    import types
    from eval.run_model import vad_pipeline
    from fakes import FakeVad

    vad = FakeVad()
    # speech_len должен пройти прод-порог 0.2с (3200 отсчётков при 16кГц)
    seg = types.SimpleNamespace(samples=[0.5] * 4000, start=100)
    vad.pending.append(seg)
    texts = iter(['привет мир'])
    text, metas = vad_pipeline(np.arange(1600, dtype=np.float32), vad,
                               lambda s: next(texts), np, overlap=1.0)
    assert text == 'Привет мир'          # прод-склейка: капитализация первой
    assert len(metas) == 1
    assert set(metas[0]) == {'text', 'gap', 'overlap', 'dur'}

def test_vad_mode_writes_segments_file(tmp_path, monkeypatch):
    import eval.run_model as rm
    corpus = _mk_corpus(tmp_path, n=1)
    out = tmp_path / 'run.jsonl'
    monkeypatch.setattr(rm, 'build_vad', lambda max_speech: __import__('fakes').FakeVad())
    n = rm.decode_corpus_vad(lambda s: 'текст', corpus, out,
                             model_label='fake', overlap=1.0, max_speech=30.0)
    assert n == 1
    segs = [json.loads(l) for l in open(tmp_path / 'run-segments.jsonl',
                                        encoding='utf-8')]
    assert segs[0]['id'] == 'clip0' and 'segments' in segs[0]
