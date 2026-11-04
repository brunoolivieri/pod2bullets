from pod2bullets.naming import slugify


def test_slugify_basic():
    assert slugify("Meu Podcast Incrível!") == "meu-podcast-incrivel"


def test_slugify_special_chars():
    assert slugify("Episode #42: O que é AI & ML?") == "episode-42-o-que-e-ai-ml"


def test_slugify_length():
    long_text = "a" * 150
    assert len(slugify(long_text, max_length=50)) == 50
