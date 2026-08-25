"""Decode the corpus with a sherpa-onnx offline model.

Modes:
  whole — one decode per file (isolates model quality),
  vad   — runs the real prod pipeline (py/streaming.py: Segmenter with
          pre/post pads, overlap+LCS dedup at junctions, max_speech forced
          cuts, join_chunk stitching) so the eval harness measures what the
          app actually produces (#14). Old raw-VAD runs from 2026-08-22
          (plain VAD + space-join, no pads/overlap) are NOT comparable to
          runs made after this change.
"""
import argparse, glob, json, os, sys, wave

import numpy as np

from eval.collect import load_manifest, DEFAULT_CORPUS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py'))
import streaming  # noqa: E402  (канон параметров пайплайна — py/streaming.py)

RUNS_DIR = os.path.join(os.path.dirname(__file__), 'runs')
VAD_MODEL = os.path.join(os.path.dirname(__file__), 'models', 'silero_vad.onnx')


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError('expected 16kHz mono s16 WAV: %s' % path)
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def decode_corpus(decode_fn, corpus_dir, out_path, mode_label, model_label):
    entries = load_manifest(str(corpus_dir))
    os.makedirs(os.path.dirname(str(out_path)) or '.', exist_ok=True)
    n = 0
    with open(out_path, 'w', encoding='utf-8') as f:
        for e in entries:
            samples = read_wav(os.path.join(str(corpus_dir), e['wav']))
            hyp = decode_fn(samples)
            f.write(json.dumps({'id': e['id'], 'hyp': hyp, 'model': model_label,
                                'mode': mode_label}, ensure_ascii=False) + '\n')
            n += 1
            print('[%d/%d] %s' % (n, len(entries), e['id']), flush=True)
    return n


def _find_one(model_dir, pattern):
    hits = sorted(glob.glob(os.path.join(model_dir, pattern)))
    if not hits:
        raise SystemExit('no %s in %s' % (pattern, model_dir))
    return hits[0]


def build_recognizer(model_dir):
    import sherpa_onnx
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=_find_one(model_dir, 'encoder*.onnx'),
        decoder=_find_one(model_dir, 'decoder*.onnx'),
        joiner=_find_one(model_dir, 'joiner*.onnx'),
        tokens=_find_one(model_dir, 'tokens.txt'),
        num_threads=4, model_type='nemo_transducer')


def whole_decode_fn(recognizer):
    def fn(samples):
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
    return fn


def build_vad(max_speech=streaming.MAX_SPEECH):
    """VAD с ПРОДОВЫМ конфигом (backend.load), включая max_speech форс-нарезку."""
    import sherpa_onnx
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = VAD_MODEL
    cfg.silero_vad.threshold = 0.5
    cfg.silero_vad.min_silence_duration = streaming.MIN_SILENCE
    cfg.silero_vad.min_speech_duration = streaming.MIN_SPEECH
    cfg.silero_vad.max_speech_duration = max_speech
    cfg.sample_rate = 16000
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=300)


def vad_pipeline(samples, vad, decode_fn, np_mod, overlap):
    """Прод-цепочка: Segmenter (pad+overlap) → decode → join_chunk."""
    seg = streaming.Segmenter(vad, np_mod, streaming.VAD_WINDOW, rate=16000,
                              pad_pre=streaming.PAD_PRE,
                              pad_post=streaming.PAD_POST, overlap=overlap)
    phrases = seg.feed(samples) + seg.flush()
    texts, metas = [], []
    for ph in phrases:
        if ph.speech_len < 16000 * 0.2:
            continue
        text = decode_fn(np_mod.asarray(ph.samples, dtype=np_mod.float32))
        metas.append({'text': text, 'gap': ph.gap, 'overlap': ph.overlap,
                      'dur': len(ph.samples) / 16000.0})
        chunk = streaming.join_chunk(texts[-1] if texts else None, text,
                                     ph.gap, ph.overlap, streaming.CAP_PAUSE)
        if chunk:
            texts.append(chunk)
    return ''.join(texts).strip(), metas


def decode_corpus_vad(decode_fn, corpus_dir, out_path, model_label,
                      overlap, max_speech):
    """Как decode_corpus, но через прод-цепочку + пишет <name>-segments.jsonl."""
    entries = load_manifest(str(corpus_dir))
    seg_path = str(out_path)[:-len('.jsonl')] + '-segments.jsonl'
    os.makedirs(os.path.dirname(str(out_path)) or '.', exist_ok=True)
    n = 0
    with open(out_path, 'w', encoding='utf-8') as f, \
         open(seg_path, 'w', encoding='utf-8') as fs:
        for e in entries:
            samples = read_wav(os.path.join(str(corpus_dir), e['wav']))
            text, metas = vad_pipeline(samples, build_vad(max_speech),
                                       decode_fn, np, overlap)
            f.write(json.dumps({'id': e['id'], 'hyp': text,
                                'model': model_label, 'mode': 'vad'},
                               ensure_ascii=False) + '\n')
            fs.write(json.dumps({'id': e['id'], 'segments': metas},
                                ensure_ascii=False) + '\n')
            n += 1
            print('[%d/%d] %s' % (n, len(entries), e['id']), flush=True)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-dir', required=True)
    ap.add_argument('--name', required=True, help='run name → runs/<name>.jsonl')
    ap.add_argument('--mode', choices=['whole', 'vad'], default='whole')
    ap.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    ap.add_argument('--overlap', type=float, default=streaming.OVERLAP,
                    help='сек контекста с прошлого сегмента, 0 = выкл (default: streaming.OVERLAP)')
    ap.add_argument('--max-speech', type=float, default=streaming.MAX_SPEECH,
                    help='форс-нарезка длинной речи, сек (default: streaming.MAX_SPEECH)')
    args = ap.parse_args()
    rec = build_recognizer(args.model_dir)
    out = os.path.join(RUNS_DIR, args.name + '.jsonl')
    model_label = os.path.basename(os.path.normpath(args.model_dir))
    if args.mode == 'whole':
        n = decode_corpus(whole_decode_fn(rec), args.corpus_dir, out, args.mode,
                          model_label)
    else:
        n = decode_corpus_vad(whole_decode_fn(rec), args.corpus_dir, out,
                              model_label, args.overlap, args.max_speech)
    print('wrote %s (%d clips)' % (out, n))


if __name__ == '__main__':
    main()
