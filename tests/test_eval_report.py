import json
import pytest
from eval.report import build_report

def _corpus(tmp_path):
    corpus = tmp_path / 'corpus'; corpus.mkdir()
    clips = {'a': 'привет мир', 'b': 'запусти демон'}
    with open(corpus / 'manifest.jsonl', 'w', encoding='utf-8') as f:
        for cid, text in clips.items():
            (corpus / (cid + '.ref.txt')).write_text(text, encoding='utf-8')
            (corpus / (cid + '.wav')).write_bytes(b'')
            f.write(json.dumps({'id': cid, 'wav': cid + '.wav',
                                'ref': cid + '.ref.txt', 'source': 'phone',
                                'verified': False}) + '\n')
    return corpus

def _run(tmp_path, name, hyps):
    p = tmp_path / (name + '.jsonl')
    with open(p, 'w', encoding='utf-8') as f:
        for cid, hyp in hyps.items():
            f.write(json.dumps({'id': cid, 'hyp': hyp, 'model': name,
                                'mode': 'whole'}, ensure_ascii=False) + '\n')
    return p

def test_single_run_report_has_aggregate(tmp_path):
    corpus = _corpus(tmp_path)
    terms = tmp_path / 'terms.txt'; terms.write_text('демон\n', encoding='utf-8')
    run = _run(tmp_path, 'm1', {'a': 'привет мир', 'b': 'запусти демона'})
    md = build_report(corpus, [run], terms)
    assert 'WER' in md and 'm1' in md and 'демон' in md

def test_two_run_report_has_delta_table(tmp_path):
    corpus = _corpus(tmp_path)
    terms = tmp_path / 'terms.txt'; terms.write_text('', encoding='utf-8')
    r1 = _run(tmp_path, 'm1', {'a': 'привет мир', 'b': 'пусти демон'})
    r2 = _run(tmp_path, 'm2', {'a': 'привет мир', 'b': 'запусти демон'})
    md = build_report(corpus, [r1, r2], terms)
    assert 'Δ' in md and 'm2' in md

def test_partial_run_reports_excluded_count(tmp_path):
    corpus = _corpus(tmp_path)  # two clips: a, b
    terms = tmp_path / 'terms.txt'; terms.write_text('', encoding='utf-8')
    run = _run(tmp_path, 'm1', {'a': 'привет мир'})  # covers only clip a
    md = build_report(corpus, [run], terms)
    assert 'excluded from scoring: 1 clips (ids not present in m1/whole)' in md

def test_empty_run_raises_system_exit(tmp_path):
    corpus = _corpus(tmp_path)
    terms = tmp_path / 'terms.txt'; terms.write_text('', encoding='utf-8')
    run = _run(tmp_path, 'm1', {})  # covers no clips
    with pytest.raises(SystemExit):
        build_report(corpus, [run], terms)

def test_aggregate_wer_is_word_weighted(tmp_path):
    corpus = tmp_path / 'corpus'; corpus.mkdir()
    clips = {'a': 'привет мир', 'b': 'один два три'}
    with open(corpus / 'manifest.jsonl', 'w', encoding='utf-8') as f:
        for cid, text in clips.items():
            (corpus / (cid + '.ref.txt')).write_text(text, encoding='utf-8')
            (corpus / (cid + '.wav')).write_bytes(b'')
            f.write(json.dumps({'id': cid, 'wav': cid + '.wav',
                                'ref': cid + '.ref.txt', 'source': 'phone',
                                'verified': False}) + '\n')
    terms = tmp_path / 'terms.txt'; terms.write_text('', encoding='utf-8')
    # clip a: exact match (wer=0, 2 words). clip b: 1 substitution (wer=1/3, 3 words).
    # weighted = (0*2 + (1/3)*3) / 5 = 0.2 -> 20.00%, not the unweighted mean 16.67%.
    run = _run(tmp_path, 'm1', {'a': 'привет мир', 'b': 'один два четыре'})
    md = build_report(corpus, [run], terms)
    row = next(l for l in md.splitlines() if l.startswith('| m1/whole |'))
    assert row.startswith('| m1/whole | 20.00% |')  # not the unweighted mean, 16.67%
