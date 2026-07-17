from bookverse.models import Book
from bookverse.recommender import rank_similar, similarity_score


def make_book(source_id: str, title: str, categories: tuple[str, ...], description: str, rating: float = 4.0) -> Book:
    return Book(
        source="test",
        source_id=source_id,
        title=title,
        authors=("Writer",),
        categories=categories,
        description=description,
        language="en",
        average_rating=rating,
        ratings_count=1000,
    )


def test_recommender_prefers_shared_categories_and_content() -> None:
    seed = make_book("1", "Dragon Academy", ("Fantasy", "Dragons"), "A magical academy with dragons")
    close = make_book("2", "Dragon School", ("Fantasy", "Dragons"), "Students train magical dragons")
    far = make_book("3", "Tax Accounting", ("Business",), "A practical guide to tax")
    assert similarity_score(seed, close) > similarity_score(seed, far)
    assert rank_similar(seed, [far, close], limit=2)[0] == close


def test_extreme_horror_rejects_childrens_picture_book() -> None:
    seed = Book(
        source="test", source_id="seed", title="Playground: Child of Divorce",
        authors=("Aron Beauregard",), categories=("Fiction", "Horror", "Thrillers / Suspense"),
        description="A graphic extreme horror splatterpunk story involving sadistic carnage and a murderous captor.",
        language="en",
    )
    bad = Book(
        source="test", source_id="bad", title="Little Black Sambo",
        authors=("Helen Bannerman",), categories=("Fiction", "Children's book", "Picture book"),
        description="A children's picture book and nursery story.", language="en",
    )
    good = Book(
        source="test", source_id="good", title="The Slob",
        authors=("Aron Beauregard",), categories=("Horror", "Splatterpunk"),
        description="An extreme horror novel with graphic violence and gore.", language="en",
    )
    assert similarity_score(seed, bad) < 0
    assert rank_similar(seed, [bad, good], limit=5) == [good]


def test_sparse_unknown_author_is_rejected():
    seed = Book(source="test", source_id="seed", title="Playground", authors=("Aron Beauregard",), description="An extreme horror splatterpunk novel with sadistic games and graphic violence.", categories=("Extreme horror", "Splatterpunk"))
    noise = Book(source="test", source_id="noise", title="The Seaborne", authors=(), description="", categories=("Fiction",))
    assert similarity_score(seed, noise) == -1.0
    assert rank_similar(seed, [noise], limit=5) == []


def test_extreme_horror_rejects_young_adult_franchise_horror() -> None:
    seed = Book(
        source="test", source_id="seed2", title="Playground",
        authors=("Aron Beauregard",),
        categories=("Extreme horror", "Splatterpunk", "Horror"),
        description="An adult splatterpunk nightmare with graphic violence, captivity and a deadly game.",
        language="en",
    )
    ya_horror = Book(
        source="test", source_id="ya", title="The Silver Eyes",
        authors=("Scott Cawthon", "Kira Breed-Wrisley"),
        categories=("Horror", "Young adult fiction", "Juvenile fiction"),
        description="Teen friends return to a haunted family restaurant and face murderous animatronics.",
        language="en",
    )
    adult_match = Book(
        source="test", source_id="adult", title="The Black Farm",
        authors=("Elias Witherow",),
        categories=("Extreme horror", "Splatterpunk"),
        description="A brutal adult extreme-horror survival story filled with graphic violence and captivity.",
        language="en",
    )
    assert similarity_score(seed, ya_horror) < 0
    assert rank_similar(seed, [ya_horror, adult_match], limit=5) == [adult_match]


def test_nonfiction_does_not_recommend_fiction() -> None:
    seed = Book(
        source="test", source_id="nf", title="A Brief History of Humankind",
        authors=("Historian",), categories=("History", "Popular science", "Anthropology"),
        description="A nonfiction history of human societies, evolution and civilisation.", language="en",
    )
    good = Book(
        source="test", source_id="nf2", title="The Human Story",
        authors=("Scholar",), categories=("History", "Popular science"),
        description="A nonfiction account of human evolution, culture and civilisation.", language="en",
    )
    bad = Book(
        source="test", source_id="f", title="The Time Machine",
        authors=("Novelist",), categories=("Science fiction", "Fiction"),
        description="A fictional time traveller journeys into a distant future.", language="en",
    )
    assert similarity_score(seed, bad) < 0
    assert rank_similar(seed, [bad, good], limit=5) == [good]


def test_middle_grade_fantasy_prefers_same_audience_and_theme() -> None:
    seed = Book(
        source="test", source_id="mg", title="Wizard School",
        authors=("A",), categories=("Fantasy", "Middle grade", "Magic school"),
        description="A middle-grade coming-of-age fantasy about friends learning magic at a wizard school.", language="en",
    )
    good = Book(
        source="test", source_id="mg2", title="The Academy of Spells",
        authors=("B",), categories=("Fantasy", "Middle grade"),
        description="Young friends attend a magical academy and learn dangerous spells.", language="en",
    )
    far = Book(
        source="test", source_id="dark", title="Blood Contract",
        authors=("C",), categories=("Dark romance", "Adult fiction"),
        description="An explicit adult dark romance involving a criminal contract.", language="en",
    )
    assert similarity_score(seed, good) > 0
    assert similarity_score(seed, far) < 0


def test_horror_novel_rejects_academic_horror_criticism() -> None:
    seed = Book(
        source="test", source_id="seed-academic", title="Playground",
        authors=("Aron Beauregard",), categories=("Horror", "Fiction", "Extreme horror"),
        description="An adult extreme-horror novel involving captivity, graphic violence and a deadly game.",
        language="en",
    )
    criticism = Book(
        source="test", source_id="criticism", title="Horror Literature and Dark Fantasy: Challenging Genres",
        authors=("Mark A. Fabrizi",), categories=("Education",),
        description=(
            "A collection of scholarly essays for teachers, school administrators and students "
            "using horror literature to teach critical literacy in secondary schools and higher education."
        ),
        language="en",
    )
    assert similarity_score(seed, criticism) < 0
    assert rank_similar(seed, [criticism], limit=5) == []


def test_same_book_type_outranks_related_anthology() -> None:
    seed = Book(
        source="test", source_id="seed-format", title="The Haunted House",
        authors=("A",), categories=("Horror", "Fiction"),
        description="A dark atmospheric horror novel about a family trapped in a haunted house.",
        language="en",
    )
    novel = Book(
        source="test", source_id="novel-format", title="House of Shadows",
        authors=("B",), categories=("Horror", "Fiction"),
        description="An atmospheric horror novel about a family surviving a haunted house.",
        language="en",
    )
    anthology = Book(
        source="test", source_id="anthology-format", title="Dread",
        authors=("C",), categories=("Horror", "Fiction"),
        description="An anthology of short horror stories and dark nightmares.",
        language="en",
    )
    ranked = rank_similar(seed, [anthology, novel], limit=5)
    assert ranked[0] == novel


def test_match_percent_is_absolute_not_top_result_normalisation() -> None:
    from bookverse.recommender import rank_similar_detailed

    seed = Book(
        source="test", source_id="seed-percent", title="The Haunted House",
        authors=("A",), categories=("Horror", "Fiction"),
        description="A dark atmospheric horror novel about a haunted family home.", language="en",
    )
    broad = Book(
        source="test", source_id="broad-percent", title="Dread",
        authors=("B",), categories=("Horror", "Fiction"),
        description="An anthology of short horror stories and dark nightmares.", language="en",
    )
    result = rank_similar_detailed(seed, [broad], limit=1)[0]
    assert result.match_percent <= 68
    assert result.match_label in {"Possible match", "Loose match"}


def test_character_age_is_not_target_audience() -> None:
    from bookverse.recommender import profile_book

    adult_horror = Book(
        source="test",
        source_id="adult-children-characters",
        title="Playground",
        authors=("Aron Beauregard",),
        categories=("Fiction", "Horror", "Extreme horror", "Splatterpunk"),
        description=(
            "Children are forced into a sadistic survival game in an adult splatterpunk novel "
            "with graphic violence, torture and gore."
        ),
        language="en",
    )
    profile = profile_book(adult_horror)
    assert "children" in profile.character_ages
    assert "children" not in profile.target_audiences
    assert "adult" in profile.target_audiences
    assert profile.content_level == "extreme"


def test_playground_rejects_ya_survival_despite_child_characters() -> None:
    seed = Book(
        source="test",
        source_id="playground-dna",
        title="Playground",
        authors=("Aron Beauregard",),
        categories=("Fiction", "Horror", "Extreme horror", "Splatterpunk"),
        description=(
            "An adult extreme-horror novel where children are kidnapped and forced through "
            "a sadistic deadly game involving graphic gore and torture."
        ),
        language="en",
    )
    hunger = Book(
        source="test",
        source_id="hunger-ya",
        title="Hunger: A Gone Novel",
        authors=("Michael Grant",),
        categories=("Fiction", "Survival", "Horror stories", "Juvenile Fiction"),
        description=(
            "Teen survivors under the age of fifteen face hunger, supernatural powers and danger "
            "in a young adult dystopian adventure."
        ),
        language="en",
    )
    adult_match = Book(
        source="test",
        source_id="adult-extreme",
        title="The Summer I Died",
        authors=("Ryan C. Thomas",),
        categories=("Horror", "Extreme horror", "Adult fiction"),
        description=(
            "Two friends are held captive by a sadistic killer in a brutal adult horror novel "
            "with graphic violence, torture and a desperate fight for survival."
        ),
        language="en",
    )
    assert similarity_score(seed, hunger) < 0
    assert rank_similar(seed, [hunger, adult_match], limit=5) == [adult_match]


def test_adult_novel_about_children_is_not_labelled_childrens() -> None:
    from bookverse.recommender import profile_book

    book = Book(
        source="test",
        source_id="the-three",
        title="The Three",
        authors=("Sarah Lotz",),
        categories=("Fiction", "Horror", "Thriller"),
        description=(
            "Three child survivors of separate plane crashes become the focus of an apocalyptic "
            "adult horror thriller involving cults and disturbing behaviour."
        ),
        language="en",
    )
    profile = profile_book(book)
    assert "children" in profile.character_ages
    assert "children" not in profile.target_audiences
    assert "adult" in profile.target_audiences


def test_turtles_all_the_way_down_is_classified_as_ya_mental_health_fiction() -> None:
    from bookverse.recommender import profile_book

    book = Book(
        source="test",
        source_id="turtles",
        title="Turtles All the Way Down",
        authors=("John Green",),
        categories=("Fiction", "Coming of age", "Friendship"),
        description=(
            "Sixteen-year-old high school student Aza Holmes tries to solve the disappearance "
            "of a fugitive billionaire while living with severe anxiety, obsessive-compulsive "
            "disorder, intrusive thoughts, friendship and first love."
        ),
        language="en",
    )
    profile = profile_book(book)
    assert "young_adult" in profile.target_audiences
    assert "adult" not in profile.target_audiences
    assert "mental_health_fiction" in profile.subgenres
    assert "young_adult_contemporary" in profile.subgenres
    assert "mental_health" in profile.themes
    assert "obsessive_compulsive_disorder" in profile.themes


def test_turtles_prefers_ya_mental_health_over_generic_child_mystery() -> None:
    seed = Book(
        source="test",
        source_id="turtles-seed",
        title="Turtles All the Way Down",
        authors=("John Green",),
        categories=("Fiction", "Coming of age", "Friendship"),
        description=(
            "Sixteen-year-old Aza is a high school student living with severe anxiety and "
            "obsessive-compulsive disorder while navigating friendship, first love and a mystery."
        ),
        language="en",
    )
    generic_mystery = Book(
        source="test",
        source_id="djinn",
        title="Djinn Patrol on the Purple Line",
        authors=("Deepa Anappara",),
        categories=("Literary fiction", "Mystery", "Coming of age"),
        description=(
            "Nine-year-old Jai and his friends investigate missing children in an impoverished "
            "neighbourhood while confronting poverty and social injustice."
        ),
        language="en",
    )
    close = Book(
        source="test",
        source_id="close-ya",
        title="Every Last Word",
        authors=("Tamara Ireland Stone",),
        categories=("Young adult fiction", "Contemporary fiction", "Coming of age"),
        description=(
            "A high school girl hides obsessive-compulsive disorder and anxiety while finding "
            "friendship, first love and a place where she can be herself."
        ),
        language="en",
    )
    assert similarity_score(seed, close) > 0
    assert similarity_score(seed, generic_mystery) < 0
    assert rank_similar(seed, [generic_mystery, close], limit=5) == [close]


def test_adult_literary_novel_with_child_narrator_stays_adult() -> None:
    from bookverse.recommender import profile_book

    book = Book(
        source="test",
        source_id="djinn-adult",
        title="Djinn Patrol on the Purple Line",
        authors=("Deepa Anappara",),
        categories=("Literary fiction", "Mystery", "Adult fiction"),
        description=(
            "Nine-year-old Jai investigates missing children in a literary novel about poverty, "
            "inequality and social injustice in an Indian neighbourhood."
        ),
        language="en",
    )
    profile = profile_book(book)
    assert "children" in profile.character_ages
    assert "adult" in profile.target_audiences
    assert "children" not in profile.target_audiences


def test_non_english_recommendations_are_rejected_even_when_mislabeled_english() -> None:
    seed = Book(
        source="test",
        source_id="adult-horror-language",
        title="The Locked Room",
        authors=("Writer A",),
        categories=("Adult fiction", "Horror", "Psychological horror"),
        description=(
            "An adult psychological-horror novel about captivity, trauma and a desperate escape "
            "from a violent locked room."
        ),
        language="en",
    )
    indonesian = Book(
        source="test",
        source_id="indonesian",
        title="Ruang Terkunci",
        authors=("Writer B",),
        categories=("Adult fiction", "Horror", "Psychological horror"),
        description=(
            "Seorang pria terjebak di dalam ruangan terkunci dan berusaha melarikan diri dari "
            "penculik yang kejam. Ia mengalami trauma, ketakutan, dan kekerasan sepanjang malam."
        ),
        # Deliberately wrong provider label: the text itself must still win.
        language="en",
    )
    english = Book(
        source="test",
        source_id="english-horror",
        title="The Captive",
        authors=("Writer C",),
        categories=("Adult fiction", "Horror", "Psychological horror"),
        description=(
            "An adult psychological-horror novel about captivity, trauma and a desperate escape "
            "from a violent kidnapper in a locked room."
        ),
        language="en",
    )
    assert similarity_score(seed, indonesian) < 0
    assert similarity_score(seed, english) > 0
    assert rank_similar(seed, [indonesian, english], limit=5) == [english]


def test_language_detector_accepts_english_and_rejects_indonesian() -> None:
    from bookverse.language_utils import book_language_status

    english = Book(
        source="test", source_id="lang-en", title="A Quiet Story", authors=("A",),
        description="A young woman learns to live with anxiety while rebuilding her friendships and family life.",
        language="",
    )
    indonesian = Book(
        source="test", source_id="lang-id", title="Sebuah Cerita", authors=("B",),
        description="Seorang perempuan muda belajar menjalani hidup dengan kecemasan dan dukungan keluarganya.",
        language="",
    )
    assert book_language_status(english) == "english"
    assert book_language_status(indonesian) == "non_english"
