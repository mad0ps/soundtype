"""Text normalization for fair WER: strips exactly the formatting layers
that differ between models (case, punctuation, ё) so WER measures words."""
import re

# keep letters/digits (any script), everything else becomes a space
_NON_WORD = re.compile(r'[^\w]+', re.UNICODE)


def normalize(text, fold_yo=True):
    text = text.lower()
    if fold_yo:
        text = text.replace('ё', 'е')
    text = _NON_WORD.sub(' ', text)
    return ' '.join(text.split())
