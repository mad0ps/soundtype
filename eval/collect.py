"""Corpus collection: history+audio from the phone and the Aug-21 backup.

Idempotent and additive: existing clips (and hand-corrected .ref.txt files)
are never overwritten. Phone keeps only the last 20 recordings, so run this
often — the corpus only grows.
"""
import argparse, json, os, shutil, subprocess, tempfile

ADB = '/Users/n0mads/Downloads/platform-tools/adb'
PHONE_DATA = '/home/phablet/.local/share/soundtype.n0madd3v0ps'
BACKUP_DIR = '/Users/n0mads/Downloads/platform-tools/ut-build/phone-backup-2026-08-21'
DEFAULT_CORPUS = os.path.join(os.path.dirname(__file__), 'corpus')


def load_manifest(corpus_dir):
    path = os.path.join(corpus_dir, 'manifest.jsonl')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def _append_manifest(corpus_dir, entry):
    with open(os.path.join(corpus_dir, 'manifest.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def merge_source(history_path, audio_dir, corpus_dir, source):
    os.makedirs(corpus_dir, exist_ok=True)
    known = {e['id'] for e in load_manifest(corpus_dir)}
    added = 0
    with open(history_path, encoding='utf-8') as f:
        records = [json.loads(line) for line in f if line.strip()]
    for rec in records:
        clip_id = '%d' % int(rec['ts'] * 1000)
        wav_src = os.path.join(str(audio_dir), clip_id + '.wav')
        if clip_id in known or not os.path.exists(wav_src):
            continue
        text = (rec.get('text') or '').strip()
        if not text:
            continue
        shutil.copy2(wav_src, os.path.join(str(corpus_dir), clip_id + '.wav'))
        with open(os.path.join(str(corpus_dir), clip_id + '.ref.txt'), 'w',
                  encoding='utf-8') as rf:
            rf.write(text)
        _append_manifest(str(corpus_dir), {
            'id': clip_id, 'wav': clip_id + '.wav', 'ref': clip_id + '.ref.txt',
            'source': source, 'verified': False})
        known.add(clip_id)
        added += 1
    return added


def collect_phone(corpus_dir):
    """adb pull history+audio into a temp dir, then merge."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ADB, 'pull', PHONE_DATA + '/history.jsonl', tmp], check=True)
        subprocess.run([ADB, 'pull', PHONE_DATA + '/audio', tmp], check=True)
        return merge_source(os.path.join(tmp, 'history.jsonl'),
                            os.path.join(tmp, 'audio'), corpus_dir, source='phone')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    ap.add_argument('--no-phone', action='store_true', help='backup only')
    args = ap.parse_args()
    total = 0
    if os.path.isdir(BACKUP_DIR):
        n = merge_source(os.path.join(BACKUP_DIR, 'history.jsonl'),
                         os.path.join(BACKUP_DIR, 'audio'),
                         args.corpus_dir, source='backup')
        print('backup: +%d clips' % n); total += n
    if not args.no_phone:
        n = collect_phone(args.corpus_dir)
        print('phone: +%d clips' % n); total += n
    print('added this run: %d' % total)
    print('corpus now: %d clips' % len(load_manifest(args.corpus_dir)))


if __name__ == '__main__':
    main()
