from bookverse.language_utils import detect_text_language


def test_dependency_free_english_detection():
    text = "A young woman struggles with anxiety while trying to solve a mystery with her best friend."
    assert detect_text_language(text) == "english"


def test_dependency_free_indonesian_detection():
    text = "Seorang pria memiliki masalah dengan keluarganya dan tidak memiliki teman dekat sejak kecil."
    assert detect_text_language(text) == "non_english"
