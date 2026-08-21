import json, wave
import numpy as np
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

def test_decode_corpus_writes_run_file(tmp_path):
    corpus = _mk_corpus(tmp_path)
    out = tmp_path / 'run.jsonl'
    n = decode_corpus(lambda s: 'решённый текст', corpus, out,
                      mode_label='whole', model_label='fake')
    assert n == 2
    lines = [json.loads(l) for l in open(out, encoding='utf-8')]
    assert lines[0] == {'id': 'clip0', 'hyp': 'решённый текст',
                        'model': 'fake', 'mode': 'whole'}
