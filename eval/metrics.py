"""WER/CER (jiwer) and domain-term recall, all on normalized text."""
import jiwer

from eval.normalize import normalize


def score_pair(ref, hyp, fold_yo=True):
    nref, nhyp = normalize(ref, fold_yo), normalize(hyp, fold_yo)
    if not nref:
        return {'wer': 0.0 if not nhyp else 1.0, 'cer': 0.0 if not nhyp else 1.0,
                'ref_words': 0}
    return {'wer': jiwer.wer(nref, nhyp),
            'cer': jiwer.cer(nref, nhyp),
            'ref_words': len(nref.split())}


def term_recall(refs, hyps, terms):
    out = {}
    for term in terms:
        nterm = normalize(term)
        ref_n = hit_n = 0
        for ref, hyp in zip(refs, hyps):
            in_ref = normalize(ref).split().count(nterm)
            in_hyp = normalize(hyp).split().count(nterm)
            ref_n += in_ref
            hit_n += min(in_ref, in_hyp)
        out[term] = {'ref': ref_n, 'hit': hit_n}
    return out


def load_terms(path):
    terms = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                terms.append(line)
    return terms
