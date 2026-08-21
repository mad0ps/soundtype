from eval.metrics import score_pair, term_recall, load_terms


def test_score_pair_perfect_after_normalization():
    s = score_pair('Привет, мир!', 'привет мир')
    assert s['wer'] == 0.0 and s['cer'] == 0.0 and s['ref_words'] == 2


def test_score_pair_one_sub():
    s = score_pair('привет большой мир', 'привет странный мир')
    assert abs(s['wer'] - 1/3) < 1e-9


def test_term_recall_counts_hits_per_pair():
    refs = ['запусти демон и демон второй', 'без терминов']
    hyps = ['запусти демон и деман второй', 'без терминов']
    r = term_recall(refs, hyps, ['демон'])
    assert r['демон'] == {'ref': 2, 'hit': 1}


def test_load_terms_skips_comments(tmp_path):
    p = tmp_path / 'terms.txt'
    p.write_text('# comment\n\nклод\nдемон\n', encoding='utf-8')
    assert load_terms(p) == ['клод', 'демон']
