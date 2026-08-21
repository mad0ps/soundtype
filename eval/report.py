"""Markdown report: one run vs refs, or two runs side by side."""
import argparse, datetime, json, os

from eval.collect import load_manifest, DEFAULT_CORPUS
from eval.metrics import score_pair, term_recall, load_terms

REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')
TERMS = os.path.join(os.path.dirname(__file__), 'terms.txt')


def _load_run(path):
    with open(path, encoding='utf-8') as f:
        rows = [json.loads(line) for line in f if line.strip()]
    label = '%s/%s' % (rows[0]['model'], rows[0]['mode']) if rows else str(path)
    return label, {r['id']: r['hyp'] for r in rows}


def _aggregate(refs, hyps):
    tot_err_w = tot_w = 0.0
    tot_cer = 0.0
    for ref, hyp in zip(refs, hyps):
        s = score_pair(ref, hyp)
        tot_err_w += s['wer'] * s['ref_words']
        tot_w += s['ref_words']
        tot_cer += s['cer']
    n = max(len(refs), 1)
    return (tot_err_w / tot_w if tot_w else 0.0), tot_cer / n


def build_report(corpus_dir, run_paths, terms_path):
    entries = load_manifest(str(corpus_dir))
    refs = {}
    for e in entries:
        with open(os.path.join(str(corpus_dir), e['ref']), encoding='utf-8') as f:
            refs[e['id']] = f.read().strip()
    runs = [_load_run(p) for p in run_paths]
    ids = [e['id'] for e in entries if all(e['id'] in h for _, h in runs)]
    if not ids:
        raise SystemExit('no clips covered by all runs — refusing to render an empty report')
    terms = load_terms(terms_path)

    lines = ['# Eval report — %s' % datetime.date.today().isoformat(),
             '', 'Corpus: %d clips scored (%d in manifest), verified refs: %d' % (
                 len(ids), len(entries),
                 sum(1 for e in entries if e.get('verified')))]
    if len(ids) < len(entries):
        for label, hyps in runs:
            missing = sum(1 for e in entries if e['id'] not in hyps)
            lines.append('excluded from scoring: %d clips (ids not present in %s)' % (
                missing, label))
    lines.append('')
    lines.append('| run | WER | mean CER |')
    lines.append('|---|---|---|')
    for label, hyps in runs:
        wer, cer = _aggregate([refs[i] for i in ids], [hyps[i] for i in ids])
        lines.append('| %s | %.2f%% | %.2f%% |' % (label, wer * 100, cer * 100))
    lines.append('')

    for label, hyps in runs:
        tr = term_recall([refs[i] for i in ids], [hyps[i] for i in ids], terms)
        hits = {t: v for t, v in tr.items() if v['ref']}
        if hits:
            lines.append('## Terms — %s' % label)
            for t, v in sorted(hits.items()):
                lines.append('- %s: %d/%d' % (t, v['hit'], v['ref']))
            lines.append('')

    if len(runs) == 2:
        (la, ha), (lb, hb) = runs
        rows = []
        for i in ids:
            wa = score_pair(refs[i], ha[i])['wer']
            wb = score_pair(refs[i], hb[i])['wer']
            rows.append((wb - wa, i, wa, wb))
        rows.sort(reverse=True)
        lines.append('## Per-clip Δ WER (%s → %s, worst regressions first)' % (la, lb))
        lines.append('| clip | %s | %s | Δ |' % (la, lb))
        lines.append('|---|---|---|---|')
        for d, i, wa, wb in rows:
            lines.append('| %s | %.1f%% | %.1f%% | %+.1f%% |' % (i, wa * 100, wb * 100, d * 100))
        lines.append('')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    md = build_report(args.corpus_dir, args.runs, TERMS)
    out = args.out or os.path.join(
        REPORTS_DIR, datetime.datetime.now().strftime('%Y%m%d-%H%M') + '.md')
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(md)
    print(md)
    print('\nsaved: %s' % out)


if __name__ == '__main__':
    main()
