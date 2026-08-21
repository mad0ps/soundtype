import json, wave, os
from eval.collect import merge_source, load_manifest

def _mk_wav(path, seconds=0.1):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b'\x00\x00' * int(16000 * seconds))

def _mk_source(tmp_path, ts, text):
    tmp_path.mkdir(parents=True, exist_ok=True)
    hist = tmp_path / 'history.jsonl'
    with open(hist, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': ts, 'text': text}, ensure_ascii=False) + '\n')
    audio = tmp_path / 'audio'; audio.mkdir(exist_ok=True)
    _mk_wav(audio / ('%d.wav' % int(ts * 1000)))
    return hist, audio

def test_merge_creates_clip_and_manifest(tmp_path):
    hist, audio = _mk_source(tmp_path / 'src', 1000.5, 'привет мир')
    corpus = tmp_path / 'corpus'
    added = merge_source(hist, audio, corpus, source='phone')
    assert added == 1
    assert (corpus / '1000500.wav').exists()
    assert (corpus / '1000500.ref.txt').read_text(encoding='utf-8') == 'привет мир'
    m = load_manifest(corpus)
    assert m == [{'id': '1000500', 'wav': '1000500.wav', 'ref': '1000500.ref.txt',
                  'source': 'phone', 'verified': False}]

def test_merge_is_idempotent_and_keeps_edited_refs(tmp_path):
    hist, audio = _mk_source(tmp_path / 'src', 1000.5, 'привет мир')
    corpus = tmp_path / 'corpus'
    merge_source(hist, audio, corpus, source='phone')
    (corpus / '1000500.ref.txt').write_text('привет, мир!', encoding='utf-8')  # Khan corrected it
    added = merge_source(hist, audio, corpus, source='phone')
    assert added == 0
    assert (corpus / '1000500.ref.txt').read_text(encoding='utf-8') == 'привет, мир!'
    assert len(load_manifest(corpus)) == 1

def test_merge_skips_records_without_audio(tmp_path):
    src = tmp_path / 'src'; src.mkdir()
    hist = src / 'history.jsonl'
    hist.write_text(json.dumps({'ts': 2000.0, 'text': 'без аудио'}) + '\n')
    (src / 'audio').mkdir()
    added = merge_source(hist, src / 'audio', tmp_path / 'corpus', source='backup')
    assert added == 0
