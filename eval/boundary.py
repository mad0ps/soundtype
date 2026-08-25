"""Junction-attribution metric for #14: which vad-vs-whole diffs sit at
VAD segment junctions. whole-decode of the SAME model is the reference —
the diff isolates segmentation damage from model quality."""
import argparse, json

import jiwer

from eval.normalize import normalize


def collapse_ratio(whole_text, seg_texts):
    """len(whole)/len(vad) по нормализованным словам; < 0.7 = whole-decode
    рухнул (длинное/тихое аудио), эталоном служить не может."""
    ww = normalize(whole_text).split()
    vw = normalize(' '.join(seg_texts)).split()
    if not vw:
        return 1.0
    return float(len(ww)) / len(vw)


def attribute(whole_text, seg_texts, win=2):
    seg_words = [normalize(t).split() for t in seg_texts]
    vad_words = [w for sw in seg_words for w in sw]
    whole_words = normalize(whole_text).split()
    juncts, pos = [], 0
    for sw in seg_words[:-1]:
        pos += len(sw)
        juncts.append(pos)
    res = {'junctions': len(juncts), 'damaged': 0, 'ops': 0,
           'ops_junction': 0, 'details': []}
    if not whole_words or not vad_words:
        return res
    out = jiwer.process_words(' '.join(whole_words), ' '.join(vad_words))
    bad = set()
    for c in out.alignments[0]:
        if c.type == 'equal':
            continue
        near = [jp for jp in juncts
                if c.hyp_start_idx - win <= jp <= c.hyp_end_idx + win]
        res['ops'] += 1
        if near:
            res['ops_junction'] += 1
            bad.update(near)
        res['details'].append(
            (bool(near), c.type,
             ' '.join(whole_words[c.ref_start_idx:c.ref_end_idx]),
             ' '.join(vad_words[c.hyp_start_idx:c.hyp_end_idx])))
    res['damaged'] = len(bad)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--segments', required=True,
                    help='runs/<name>-segments.jsonl (Task-4 format)')
    ap.add_argument('--whole', required=True, help='runs/<whole>.jsonl')
    ap.add_argument('--win', type=int, default=2)
    args = ap.parse_args()
    whole = {r['id']: r['hyp'] for r in
             map(json.loads, open(args.whole, encoding='utf-8'))}
    tot = {'junctions': 0, 'damaged': 0, 'ops': 0, 'ops_junction': 0}
    excluded = []
    for row in map(json.loads, open(args.segments, encoding='utf-8')):
        cid, texts = row['id'], [s['text'] for s in row['segments']]
        if cid not in whole or len(texts) < 2:
            continue
        if collapse_ratio(whole[cid], texts) < 0.7:
            excluded.append(cid)
            continue
        r = attribute(whole[cid], texts, args.win)
        for k in tot:
            tot[k] += r[k]
        if r['damaged']:
            print('== %s: %d/%d junctions damaged' %
                  (cid, r['damaged'], r['junctions']))
            for near, typ, ref, hyp in r['details']:
                print('   [%s] %-10s whole=%r vad=%r' %
                      ('JUNCT' if near else 'mid  ', typ, ref, hyp))
    print()
    print('junctions: %d damaged: %d (%.0f%%)  ops: %d junction-ops: %d (%.0f%%)'
          % (tot['junctions'], tot['damaged'],
             100.0 * tot['damaged'] / max(tot['junctions'], 1),
             tot['ops'], tot['ops_junction'],
             100.0 * tot['ops_junction'] / max(tot['ops'], 1)))
    if excluded:
        print('excluded (whole collapsed, ratio<0.7): %s' % ', '.join(excluded))


if __name__ == '__main__':
    main()
