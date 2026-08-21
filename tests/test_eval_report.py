import json
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
