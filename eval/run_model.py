"""Decode the corpus with a sherpa-onnx offline model.

Modes:
  whole — one decode per file (isolates model quality),
  vad   — prod-like silero-VAD segmentation (min_silence 1.0s), segments
          decoded independently and space-joined (approximation of the
          app pipeline; #14 will reuse this mode for boundary tuning).
"""
import argparse, glob, json, os, wave

import numpy as np

from eval.collect import load_manifest, DEFAULT_CORPUS

RUNS_DIR = os.path.join(os.path.dirname(__file__), 'runs')
VAD_MODEL = os.path.join(os.path.dirname(__file__), 'models', 'silero_vad.onnx')
MIN_SILENCE = 1.0  # mirrors py/backend.py prod segmentation


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
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


def vad_decode_fn(recognizer):
    import sherpa_onnx
    base = whole_decode_fn(recognizer)

    def fn(samples):
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = VAD_MODEL
        cfg.silero_vad.min_silence_duration = MIN_SILENCE
        cfg.sample_rate = 16000
        vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=300)
        window = cfg.silero_vad.window_size
        parts = []
        for off in range(0, len(samples), window):
            vad.accept_waveform(samples[off:off + window])
        vad.flush()
        while not vad.empty():
            parts.append(base(np.asarray(vad.front.samples, dtype=np.float32)))
            vad.pop()
        return ' '.join(p for p in parts if p)
    return fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-dir', required=True)
    ap.add_argument('--name', required=True, help='run name → runs/<name>.jsonl')
    ap.add_argument('--mode', choices=['whole', 'vad'], default='whole')
    ap.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    args = ap.parse_args()
    rec = build_recognizer(args.model_dir)
    fn = whole_decode_fn(rec) if args.mode == 'whole' else vad_decode_fn(rec)
    out = os.path.join(RUNS_DIR, args.name + '.jsonl')
    n = decode_corpus(fn, args.corpus_dir, out, args.mode,
                      os.path.basename(os.path.normpath(args.model_dir)))
    print('wrote %s (%d clips)' % (out, n))


if __name__ == '__main__':
    main()
