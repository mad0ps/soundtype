from eval.normalize import normalize


def test_lowercase_and_punct():
    assert normalize('Привет, мир! Как дела?') == 'привет мир как дела'


def test_yo_folding_default():
    assert normalize('Всё ещё') == 'все еще'


def test_yo_kept_when_disabled():
    assert normalize('Всё ещё', fold_yo=False) == 'всё ещё'


def test_dash_and_ellipsis_and_numbers():
    assert normalize('Так — вот… 25 штук') == 'так вот 25 штук'


def test_collapse_whitespace_and_newlines():
    assert normalize('раз\nдва   три ') == 'раз два три'
