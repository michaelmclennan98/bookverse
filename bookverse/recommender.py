from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .models import Book
from .language_utils import book_language_status, normalise_language_code
from .smart_search import SmartSearchPlan

# Words that add little recommendation value. Catalogue categories are noisy, so
# broad labels such as "Fiction" are deliberately excluded from matching.
STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "their", "they",
    "them", "his", "her", "she", "you", "your", "are", "was", "were", "but", "not",
    "book", "books", "novel", "novels", "story", "stories", "about", "who", "when",
    "what", "where", "which", "has", "have", "had", "its", "our", "out", "all", "one",
    "two", "new", "more", "than", "edition", "volume", "series", "author", "published",
    "read", "reading", "fiction", "general", "literature", "accessible", "work", "works",
}

GENERIC_CATEGORIES = {
    "fiction", "general", "literature", "books", "accessible book", "large type books",
    "protected daisy", "internet archive wishlist", "open library staff picks",
    "reading level", "juvenile literature -- general", "education -- general",
}

# The taxonomy is intentionally broad. It is not a hardcoded recommendation list;
# it converts inconsistent API metadata into comparable signals for any book.
SIGNAL_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "genre": {
        "fantasy": ("fantasy", "magic", "magical", "wizard", "witch", "sorcery", "enchanted"),
        "science_fiction": ("science fiction", "sci-fi", "space opera", "alien", "spaceship", "interstellar"),
        "horror": ("horror", "terror", "macabre", "nightmare", "haunted", "demonic", "occult"),
        "thriller": ("thriller", "suspense", "page-turner", "conspiracy", "cat-and-mouse"),
        "mystery": ("mystery", "detective", "whodunit", "investigation", "sleuth"),
        "crime": ("crime", "criminal", "police", "murder investigation", "gangster", "mafia"),
        "romance": ("romance", "romantic", "love story", "fall in love", "relationship"),
        "historical_fiction": ("historical fiction", "period fiction", "historical novel"),
        "literary_fiction": ("literary fiction", "domestic fiction", "family saga"),
        "contemporary_fiction": ("contemporary fiction", "realistic fiction", "contemporary novel"),
        "adventure": ("adventure", "quest", "expedition", "treasure hunt", "survival adventure"),
        "dystopian": ("dystopian", "dystopia", "post-apocalyptic", "apocalypse", "totalitarian"),
        "western": ("western", "cowboy", "frontier", "wild west"),
        "humour": ("humor", "humour", "comedy", "comic novel", "satire", "funny"),
        "erotica": ("erotica", "erotic fiction", "explicit romance"),
        "graphic_novel": ("graphic novel", "comic book", "manga", "comics"),
        "poetry": ("poetry", "poems", "verse"),
        "biography": ("biography", "biographical", "life of"),
        "memoir": ("memoir", "autobiography", "personal narrative"),
        "history": ("history", "historical account", "world war", "social history"),
        "true_crime": ("true crime", "real-life murder", "criminal case"),
        "self_help": ("self-help", "self help", "personal development", "motivation"),
        "business": ("business", "entrepreneurship", "management", "leadership", "marketing"),
        "science": ("popular science", "scientific", "physics", "biology", "astronomy", "chemistry"),
        "philosophy": ("philosophy", "philosophical", "ethics", "metaphysics"),
        "religion": ("religion", "religious", "theology", "spirituality", "bible"),
        "politics": ("politics", "political science", "government", "geopolitics"),
        "travel": ("travel", "travelogue", "journey through", "guidebook"),
        "cooking": ("cookbook", "recipes", "cooking", "baking", "cuisine"),
        "health": ("health", "medical", "medicine", "wellness", "fitness"),
        "essays": ("essays", "essay collection"),
        "reference": ("reference", "handbook", "manual", "textbook", "encyclopedia"),
    },
    "subgenre": {
        "extreme_horror": ("extreme horror", "splatterpunk", "hardcore horror", "gross-out horror"),
        "psychological_horror": ("psychological horror", "psychological terror"),
        "gothic_horror": ("gothic horror", "gothic fiction", "gothic novel"),
        "supernatural_horror": ("supernatural horror", "ghost story", "haunted house", "possession"),
        "body_horror": ("body horror", "mutation horror"),
        "folk_horror": ("folk horror", "pagan horror", "rural horror"),
        "slasher": ("slasher", "masked killer"),
        "cosmic_horror": ("cosmic horror", "lovecraftian", "eldritch"),
        "psychological_thriller": ("psychological thriller", "domestic thriller"),
        "legal_thriller": ("legal thriller", "courtroom thriller"),
        "spy_thriller": ("spy thriller", "espionage", "secret agent"),
        "techno_thriller": ("techno-thriller", "technothriller", "technology thriller"),
        "cozy_mystery": ("cozy mystery", "cosy mystery"),
        "police_procedural": ("police procedural", "detective procedural"),
        "noir": ("noir", "hard-boiled", "hardboiled"),
        "romantic_suspense": ("romantic suspense", "romance thriller"),
        "dark_romance": ("dark romance", "morally grey romance", "morally gray romance"),
        "romantic_comedy": ("romantic comedy", "rom-com", "romcom"),
        "historical_romance": ("historical romance", "regency romance"),
        "paranormal_romance": ("paranormal romance", "vampire romance", "shifter romance"),
        "epic_fantasy": ("epic fantasy", "high fantasy"),
        "urban_fantasy": ("urban fantasy", "contemporary fantasy"),
        "dark_fantasy": ("dark fantasy", "grimdark"),
        "romantasy": ("romantasy", "fantasy romance", "romantic fantasy"),
        "portal_fantasy": ("portal fantasy", "other world", "another world"),
        "space_opera": ("space opera", "galactic empire"),
        "cyberpunk": ("cyberpunk", "virtual reality", "megacorporation"),
        "hard_science_fiction": ("hard science fiction", "hard sci-fi"),
        "time_travel": ("time travel", "time-travel", "alternate timeline"),
        "military_science_fiction": ("military science fiction", "military sci-fi"),
        "alternate_history": ("alternate history", "alternative history"),
        "narrative_nonfiction": ("narrative nonfiction", "literary nonfiction"),
        "popular_science": ("popular science", "science for general readers"),
        "young_adult_contemporary": (
            "young adult contemporary", "contemporary young adult", "ya contemporary",
            "teen contemporary fiction",
        ),
        "mental_health_fiction": (
            "mental health fiction", "mental illness fiction", "psychological realism",
        ),
        "social_issue_fiction": (
            "social issue fiction", "issue-driven fiction", "social realism",
        ),
    },
    "audience": {
        # Target readership only. Character ages are deliberately handled in a
        # separate group so a novel *about children* is not labelled for children.
        "children": (
            "children's book", "childrens book", "for children", "early reader",
            "beginning reader", "ages 3 to 7", "ages 4 to 8",
        ),
        "middle_grade": (
            "middle grade", "middle-grade", "for middle grade readers",
            "ages 8 to 12", "ages 9 to 12",
        ),
        "young_adult": (
            "young adult fiction", "young adult novel", "young-adult fiction",
            "ya fiction", "teen fiction", "for teen readers", "teen readers",
            "ages 13 to 18", "ages 14 and up", "ages 14-up",
        ),
        "adult": (
            "adult fiction", "adult novel", "for adult readers", "for adults",
            "mature readers", "adults only", "18+ readers", "adult horror",
        ),
    },
    "character_age": {
        "children": (
            "child", "child protagonist", "child protagonists", "children", "young children",
            "schoolchildren", "kids", "boys and girls",
        ),
        "teenagers": (
            "teen protagonist", "teen protagonists", "teenager", "teenagers",
            "teenage", "high school student", "high school students", "adolescents",
        ),
        "adults": (
            "adult protagonist", "adult protagonists", "middle-aged", "retired detective",
        ),
    },
    "content_rating": {
        "family": (
            "family friendly", "family-friendly", "suitable for children", "gentle read",
        ),
        "teen": (
            "teen content", "mild violence", "suitable for teens", "young adult content",
        ),
        "mature": (
            "mature content", "graphic violence", "explicit violence", "sexual content",
            "explicit sex", "torture", "gory", "gore", "brutal violence",
        ),
        "extreme": (
            "extreme horror", "splatterpunk", "hardcore horror", "gross-out horror",
            "graphic gore", "sadistic violence", "depraved violence", "blood-soaked",
        ),
    },
    "format": {
        "picture_book": ("picture book", "illustrated children's", "board book"),
        "graphic_novel": ("graphic novel", "manga", "comic book"),
        "short_stories": ("short stories", "short story collection", "collection of stories"),
        "anthology": ("anthology", "collected stories", "stories by multiple authors"),
        "novella": ("novella", "short novel"),
        "poetry": ("poetry", "poems"),
        "memoir": ("memoir", "autobiography"),
        "reference": ("textbook", "manual", "handbook", "reference work"),
    },
    "work_type": {
        "novel": ("a novel", "novel of", "debut novel", "fiction novel"),
        "novella": ("novella", "short novel"),
        "short_stories": ("short stories", "short story collection", "collection of short fiction"),
        "anthology": ("anthology", "collected stories", "stories by multiple authors"),
        "essay_collection": ("essay collection", "collection of essays", "scholarly essays"),
        "academic_criticism": (
            "literary criticism", "critical study", "scholarly study", "scholarly essays",
            "academic essays", "school curriculum", "classroom", "critical literacy",
            "secondary schools", "higher education", "teachers and students", "university press",
            "study of literature", "companion to the", "literary analysis",
            "criticism and interpretation", "study guide", "teacher guide", "lesson plans",
        ),
        "textbook": ("textbook", "coursebook", "student edition", "teaching resource"),
        "reference": ("reference work", "encyclopedia", "handbook", "dictionary of"),
        "manual": ("manual", "step-by-step guide", "instructional guide"),
        "guidebook": ("guidebook", "travel guide", "field guide"),
        "cookbook": ("cookbook", "recipe book", "recipes for"),
        "memoir": ("memoir", "autobiography", "personal memoir"),
        "biography": ("biography", "biographical account"),
        "self_help": ("self-help", "self help", "personal development guide"),
        "poetry": ("poetry collection", "collection of poems", "poems"),
        "graphic_novel": ("graphic novel", "manga", "comic book"),
        "picture_book": ("picture book", "board book", "illustrated children's book"),
    },
    "tone": {
        "dark": ("dark", "bleak", "grim", "disturbing", "unsettling", "harrowing"),
        "cozy": ("cozy", "cosy", "comforting", "wholesome", "gentle"),
        "humorous": ("funny", "humorous", "witty", "comedic", "satirical"),
        "emotional": ("emotional", "heartbreaking", "moving", "poignant", "tearjerker"),
        "hopeful": ("hopeful", "uplifting", "inspiring", "optimistic"),
        "suspenseful": ("suspenseful", "tense", "page-turning", "edge of your seat"),
        "violent": ("graphic violence", "gory", "gore", "brutal", "torture", "sadistic", "carnage", "blood-soaked"),
        "explicit": ("sexually explicit", "explicit sex", "mature content", "erotic"),
        "fast_paced": ("fast-paced", "fast paced", "action-packed", "action packed"),
        "slow_burn": ("slow burn", "slow-burn", "slowly unfolding"),
        "atmospheric": ("atmospheric", "moody", "immersive atmosphere"),
        "introspective": ("introspective", "interior life", "inner thoughts", "thought spirals"),
        "poignant": ("poignant", "tender", "wrenching", "revelatory"),
    },
    "theme": {
        "captivity": ("captivity", "captive", "kidnapped", "abducted", "held hostage", "imprisoned"),
        "deadly_game": ("deadly game", "sadistic game", "survival game", "death game"),
        "serial_killer": ("serial killer", "murderer", "killer stalking"),
        "survival": ("survival", "fight to survive", "stranded", "against the odds"),
        "revenge": ("revenge", "vengeance", "retribution"),
        "coming_of_age": ("coming of age", "coming-of-age", "growing up"),
        "found_family": ("found family", "chosen family"),
        "family": ("family", "siblings", "mother and daughter", "father and son", "generational"),
        "grief": ("grief", "bereavement", "loss of", "mourning"),
        "friendship": ("friendship", "best friends", "friends"),
        "war": ("war", "battlefield", "soldier", "military conflict"),
        "political_intrigue": ("political intrigue", "court intrigue", "power struggle"),
        "magic_school": ("magic school", "magical academy", "wizard school", "academy of magic"),
        "dragons": ("dragon", "dragons", "dragon rider"),
        "vampires": ("vampire", "vampires"),
        "werewolves": ("werewolf", "werewolves", "shifter"),
        "witches": ("witch", "witches", "witchcraft"),
        "enemies_to_lovers": ("enemies to lovers", "enemies-to-lovers"),
        "friends_to_lovers": ("friends to lovers", "friends-to-lovers"),
        "fake_dating": ("fake dating", "pretend relationship"),
        "second_chance": ("second chance romance", "second-chance romance"),
        "forbidden_love": ("forbidden love", "forbidden romance"),
        "time_travel": ("time travel", "time-travel"),
        "artificial_intelligence": ("artificial intelligence", "sentient ai", "machine intelligence"),
        "space_exploration": ("space exploration", "interstellar mission", "space mission"),
        "heist": ("heist", "robbery", "crew of thieves"),
        "courtroom": ("courtroom", "trial", "lawyer", "legal case"),
        "true_story": ("true story", "based on real events", "real-life"),
        "mental_health": ("mental health", "mental illness", "psychiatric", "psychological condition"),
        "anxiety": ("anxiety", "anxious", "panic attack", "panic attacks"),
        "obsessive_compulsive_disorder": (
            "obsessive compulsive disorder", "obsessive-compulsive disorder", "ocd",
            "intrusive thoughts", "compulsions",
        ),
        "depression": ("depression", "depressive", "suicidal thoughts"),
        "trauma": ("trauma", "traumatic", "post-traumatic", "ptsd"),
        "addiction": ("addiction", "substance abuse", "alcoholism", "drug dependency"),
        "self_discovery": ("self-discovery", "self discovery", "finding herself", "finding himself"),
        "identity": ("identity", "sense of self", "who she is", "who he is"),
        "first_love": ("first love", "first romance", "falling in love for the first time"),
        "school_life": ("high school", "secondary school", "school life", "classmate", "classmates"),
        "missing_person": ("missing person", "missing persons", "disappearance", "disappears", "vanished"),
        "poverty": ("poverty", "impoverished", "slum", "financial hardship"),
        "social_injustice": ("social injustice", "inequality", "discrimination", "marginalised", "marginalized"),
        "chronic_illness": ("chronic illness", "long-term illness", "terminal illness"),
        "disability": ("disability", "disabled", "neurodivergent", "neurodiversity"),
    },
}

FICTION_GENRES = {
    "fantasy", "science_fiction", "horror", "thriller", "mystery", "crime", "romance",
    "historical_fiction", "literary_fiction", "contemporary_fiction", "adventure", "dystopian", "western", "humour",
    "erotica", "graphic_novel",
}
NONFICTION_GENRES = {
    "biography", "memoir", "history", "true_crime", "self_help", "business", "science",
    "philosophy", "religion", "politics", "travel", "cooking", "health", "essays", "reference",
}

FICTION_WORK_TYPES = {
    "novel", "novella", "short_stories", "anthology", "graphic_novel", "picture_book", "poetry",
}
NONFICTION_WORK_TYPES = {
    "essay_collection", "academic_criticism", "textbook", "reference", "manual", "guidebook",
    "cookbook", "memoir", "biography", "self_help",
}
LONGFORM_FICTION_TYPES = {"novel", "novella"}
SHORTFORM_FICTION_TYPES = {"short_stories", "anthology"}
ACADEMIC_TYPES = {"academic_criticism", "textbook", "reference", "manual"}
WORK_TYPE_PRIORITY = (
    "academic_criticism", "textbook", "reference", "cookbook", "guidebook", "manual",
    "memoir", "biography", "essay_collection", "picture_book", "graphic_novel", "poetry",
    "short_stories", "anthology", "novella", "novel", "self_help",
)


CONTENT_LEVEL_ORDER = {
    "family": 0,
    "teen": 1,
    "general": 2,
    "mature": 3,
    "extreme": 4,
}
CONTENT_LEVEL_PRIORITY = ("extreme", "mature", "general", "teen", "family")
TARGET_AUDIENCE_PRIORITY = ("adult", "young_adult", "middle_grade", "children")

HIGH_SPECIFICITY_THEMES = {
    "mental_health", "anxiety", "obsessive_compulsive_disorder", "depression",
    "trauma", "addiction", "chronic_illness", "disability", "captivity",
    "deadly_game", "serial_killer", "grief", "first_love", "missing_person",
    "poverty", "social_injustice", "political_intrigue", "magic_school",
    "dragons", "vampires", "werewolves", "witches", "time_travel",
    "artificial_intelligence", "space_exploration", "courtroom", "heist",
}


@dataclass(slots=True)
class BookProfile:
    genres: set[str] = field(default_factory=set)
    subgenres: set[str] = field(default_factory=set)
    target_audiences: set[str] = field(default_factory=set)
    character_ages: set[str] = field(default_factory=set)
    content_ratings: set[str] = field(default_factory=set)
    formats: set[str] = field(default_factory=set)
    work_types: set[str] = field(default_factory=set)
    tones: set[str] = field(default_factory=set)
    themes: set[str] = field(default_factory=set)
    weighted_terms: dict[str, float] = field(default_factory=dict)
    fiction_status: str = "unknown"  # fiction, nonfiction, mixed, unknown

    @property
    def audiences(self) -> set[str]:
        """Backward-compatible alias for the target readership only."""
        return self.target_audiences

    @property
    def strong_signals(self) -> set[str]:
        return self.subgenres | self.genres | self.themes | self.tones | self.work_types

    @property
    def primary_work_type(self) -> str:
        return next((value for value in WORK_TYPE_PRIORITY if value in self.work_types), "unknown")

    @property
    def primary_audience(self) -> str:
        return next((value for value in TARGET_AUDIENCE_PRIORITY if value in self.target_audiences), "unknown")

    @property
    def content_level(self) -> str:
        return next((value for value in CONTENT_LEVEL_PRIORITY if value in self.content_ratings), "general")

    @property
    def content_level_value(self) -> int:
        return CONTENT_LEVEL_ORDER[self.content_level]

    @property
    def confidence(self) -> float:
        score = (
            len(self.genres) * 0.9
            + len(self.subgenres) * 1.5
            + len(self.themes) * 0.55
            + len(self.tones) * 0.45
            + len(self.target_audiences) * 0.4
            + len(self.content_ratings) * 0.45
            + len(self.work_types) * 0.65
            + min(len(self.weighted_terms), 16) * 0.05
        )
        return min(score / 6.0, 1.0)


@dataclass(slots=True)
class RecommendationResult:
    book: Book
    score: float
    reasons: tuple[str, ...]
    match_percent: int
    match_label: str


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _book_text(book: Book) -> str:
    return " ".join([book.title, book.subtitle, book.description, *book.categories]).casefold()


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = phrase.casefold()
    if " " in phrase or "-" in phrase:
        return phrase in text
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _extract_signals(text: str, group: str) -> set[str]:
    output: set[str] = set()
    ambiguous_genre_labels = {"science", "history", "business", "health", "travel", "religion", "politics", "philosophy"}
    for signal, phrases in SIGNAL_PHRASES[group].items():
        canonical = signal.replace("_", " ")
        canonical_match = (
            group not in {"audience", "character_age", "content_rating"}
            and (group != "genre" or signal not in ambiguous_genre_labels)
        )
        if (canonical_match and _contains_phrase(text, canonical)) or any(_contains_phrase(text, phrase) for phrase in phrases):
            output.add(signal)
    return output


def _infer_character_ages(text: str) -> set[str]:
    ages: set[str] = set()
    for raw in re.findall(r"\b(\d{1,2})[- ]year[- ]old\b", text, flags=re.I):
        age = int(raw)
        if 0 <= age <= 12:
            ages.add("children")
        elif 13 <= age <= 19:
            ages.add("teenagers")
        elif age >= 20:
            ages.add("adults")
    if re.search(r"\b(high school|secondary school|sixth form|teenage|teenager|adolescent)\b", text, flags=re.I):
        ages.add("teenagers")
    if re.search(r"\b(primary school|elementary school|young child|nine-year-old|ten-year-old|eleven-year-old|twelve-year-old)\b", text, flags=re.I):
        ages.add("children")
    return ages


def _weighted_tokens(book: Book) -> dict[str, float]:
    weights: Counter[str] = Counter()

    def add(value: str, weight: float) -> None:
        for token in re.findall(r"[a-z0-9']{3,}", value.casefold()):
            if token not in STOP_WORDS and not token.isdigit():
                weights[token] += weight

    add(book.title, 3.2)
    add(book.subtitle, 2.2)
    for category in book.categories:
        if category.casefold().strip() not in GENERIC_CATEGORIES:
            add(category, 2.5)
    add(book.description, 1.0)
    return dict(weights.most_common(80))


def profile_book(book: Book) -> BookProfile:
    text = _book_text(book)
    genres = _extract_signals(text, "genre")
    subgenres = _extract_signals(text, "subgenre")
    target_audiences = _extract_signals(text, "audience")
    exact_audience_categories = {_normalise(value) for value in book.categories}
    juvenile_label = bool(exact_audience_categories & {"juvenile fiction", "juvenile literature"})
    if exact_audience_categories & {
        "young adult", "young adult fiction", "young adult literature", "ya fiction",
        "teen fiction", "teen literature",
    }:
        target_audiences.add("young_adult")
    if exact_audience_categories & {"middle grade", "middle grade fiction"}:
        target_audiences.add("middle_grade")
    if exact_audience_categories & {
        "childrens fiction", "children s fiction", "picture books", "early readers",
        "beginning readers",
    }:
        target_audiences.add("children")
    if exact_audience_categories & {"adult fiction", "adult literature"}:
        target_audiences.add("adult")
    character_ages = _extract_signals(text, "character_age") | _infer_character_ages(text)
    content_ratings = _extract_signals(text, "content_rating")
    formats = _extract_signals(text, "format")
    work_types = _extract_signals(text, "work_type")
    work_types.update(formats & {"picture_book", "graphic_novel", "short_stories", "anthology", "novella", "poetry", "memoir", "reference"})
    tones = _extract_signals(text, "tone")
    themes = _extract_signals(text, "theme")

    # Closely related mental-health terms reinforce the broader theme.
    if themes & {"anxiety", "obsessive_compulsive_disorder", "depression", "trauma", "addiction"}:
        themes.add("mental_health")
    if "obsessive_compulsive_disorder" in themes:
        themes.add("anxiety")
    if re.search(r"\b(contemporary|modern-day|present-day|realistic fiction)\b", text, flags=re.I):
        genres.add("contemporary_fiction")
    if "mental_health" in themes and ("fiction" in text or book.description):
        subgenres.add("mental_health_fiction")
    if themes & {"poverty", "social_injustice"} and ("literary_fiction" in genres or "contemporary_fiction" in genres):
        subgenres.add("social_issue_fiction")

    # Subgenres imply their parent genre.
    if subgenres & {
        "extreme_horror", "psychological_horror", "gothic_horror", "supernatural_horror",
        "body_horror", "folk_horror", "slasher", "cosmic_horror",
    }:
        genres.add("horror")
    if subgenres & {"psychological_thriller", "legal_thriller", "spy_thriller", "techno_thriller"}:
        genres.add("thriller")
    if subgenres & {"cozy_mystery", "police_procedural", "noir"}:
        genres.add("mystery")
    if subgenres & {"romantic_suspense", "dark_romance", "romantic_comedy", "historical_romance", "paranormal_romance"}:
        genres.add("romance")
    if subgenres & {"epic_fantasy", "urban_fantasy", "dark_fantasy", "romantasy", "portal_fantasy"}:
        genres.add("fantasy")
    if subgenres & {"space_opera", "cyberpunk", "hard_science_fiction", "military_science_fiction"}:
        genres.add("science_fiction")
    if "time_travel" in subgenres:
        genres.add("science_fiction")
    if "alternate_history" in subgenres:
        genres.discard("history")
        genres.add("historical_fiction")
    if subgenres & {"young_adult_contemporary", "mental_health_fiction", "social_issue_fiction"}:
        genres.add("contemporary_fiction")

    # A combination of horror, graphic intensity and survival/captivity signals
    # is a reliable proxy when catalogues omit the niche label "extreme horror".
    if (
        "horror" in genres
        and "violent" in tones
        and bool(themes & {"captivity", "deadly_game", "survival", "serial_killer"})
    ):
        subgenres.add("extreme_horror")

    # "Juvenile fiction" is a broad catalogue label, not a synonym for children's books.
    # Use protagonist age and school markers to distinguish YA from middle grade.
    if juvenile_label and not target_audiences:
        if "teenagers" in character_ages or "school_life" in themes:
            target_audiences.add("young_adult")
        elif "children" in character_ages:
            target_audiences.add("middle_grade")
        else:
            target_audiences.add("middle_grade")

    severe_terms = len(re.findall(
        r"\b(extreme horror|splatterpunk|graphic gore|graphic violence|gory|gore|"
        r"sadistic|torture|carnage|blood-soaked|depraved|mutilat|slaughter)\b",
        text,
        flags=re.I,
    ))
    if "extreme_horror" in subgenres or severe_terms >= 2:
        content_ratings.discard("family")
        content_ratings.discard("teen")
        content_ratings.add("extreme")
    elif "explicit" in tones or "erotica" in genres or "violent" in tones or severe_terms == 1:
        content_ratings.discard("family")
        content_ratings.add("mature")
    elif target_audiences & {"children", "middle_grade"}:
        content_ratings.add("family")
    elif "young_adult" in target_audiences:
        content_ratings.add("teen")
    else:
        content_ratings.add("general")

    # Content and readership are different from the ages of the characters. Graphic,
    # explicit or extreme content overrides noisy juvenile catalogue labels.
    if "extreme" in content_ratings or "explicit" in tones or "erotica" in genres:
        target_audiences.difference_update({"children", "middle_grade", "young_adult"})
        target_audiences.add("adult")
    elif "mature" in content_ratings and not target_audiences:
        target_audiences.add("adult")

    category_text = " ".join(book.categories).casefold()
    educational_labels = (
        "education", "study aids", "teaching methods", "curriculum", "literary criticism",
        "criticism and interpretation", "teacher resource", "classroom resource",
    )
    if (
        any(label in category_text for label in educational_labels)
        and not (work_types & {"picture_book", "graphic_novel"})
        and "fiction" not in category_text
    ):
        work_types.add("textbook")

    fiction_hits = bool(genres & FICTION_GENRES)
    nonfiction_hits = bool(genres & NONFICTION_GENRES)
    fiction_type_hits = bool(work_types & FICTION_WORK_TYPES)
    nonfiction_type_hits = bool(work_types & NONFICTION_WORK_TYPES)

    # Work type is more trustworthy than subject words. A scholarly book about horror
    # mentions "horror" repeatedly but is still nonfiction criticism, not a horror novel.
    if nonfiction_type_hits and not fiction_type_hits:
        fiction_status = "nonfiction"
    elif fiction_type_hits and not nonfiction_type_hits:
        fiction_status = "fiction"
    elif fiction_hits and nonfiction_hits:
        fiction_status = "mixed"
    elif fiction_hits:
        fiction_status = "fiction"
    elif nonfiction_hits:
        fiction_status = "nonfiction"
    else:
        categories_text = " ".join(book.categories).casefold()
        if "nonfiction" in categories_text or "non-fiction" in categories_text:
            fiction_status = "nonfiction"
        elif "fiction" in categories_text:
            fiction_status = "fiction"
        else:
            fiction_status = "unknown"

    # Most catalogue records for ordinary novels omit the word "novel". Infer it only
    # after the record is confidently fiction and no more specific form was detected.
    if fiction_status == "fiction" and not work_types:
        work_types.add("novel")
    if fiction_status == "nonfiction" and not work_types:
        if "memoir" in genres:
            work_types.add("memoir")
        elif "biography" in genres:
            work_types.add("biography")
        elif "essays" in genres:
            work_types.add("essay_collection")

    # Infer YA only from a cluster of readership signals. A teenage character alone is
    # not enough; the book must also look like school-centred, coming-of-age, first-love
    # or mental-health contemporary fiction. This keeps adult novels with young narrators adult.
    if fiction_status == "fiction" and not target_audiences:
        ya_markers = 0
        ya_markers += 1 if "teenagers" in character_ages else 0
        ya_markers += 1 if "school_life" in themes else 0
        ya_markers += 1 if themes & {"coming_of_age", "first_love", "mental_health", "identity", "self_discovery"} else 0
        ya_markers += 1 if genres & {"contemporary_fiction", "romance"} or "mental_health_fiction" in subgenres else 0
        if "picture_book" in work_types:
            target_audiences.add("children")
        elif ya_markers >= 3 and content_ratings.isdisjoint({"mature", "extreme"}):
            target_audiences.add("young_adult")
            content_ratings.discard("general")
            content_ratings.add("teen")
            if "contemporary_fiction" in genres or "mental_health_fiction" in subgenres:
                subgenres.add("young_adult_contemporary")
        else:
            target_audiences.add("adult")

    return BookProfile(
        genres=genres,
        subgenres=subgenres,
        target_audiences=target_audiences,
        character_ages=character_ages,
        content_ratings=content_ratings,
        formats=formats,
        work_types=work_types,
        tones=tones,
        themes=themes,
        weighted_terms=_weighted_tokens(book),
        fiction_status=fiction_status,
    )


def profile_search_terms(book: Book, limit: int = 8) -> list[str]:
    """Return useful catalogue query terms ordered from specific to broad."""
    profile = profile_book(book)
    output: list[str] = []

    def add(value: str) -> None:
        value = value.replace("_", " ").strip()
        if value and value not in output:
            output.append(value)

    for value in sorted(profile.subgenres):
        add(value)
    for value in sorted(profile.themes & HIGH_SPECIFICITY_THEMES):
        add(value)
    for value in sorted(profile.genres):
        add(value)
    for value in sorted(profile.themes - HIGH_SPECIFICITY_THEMES):
        add(value)
    for value in sorted(profile.tones):
        add(value)
    for value in sorted(profile.work_types):
        add(value)

    for category in book.categories:
        cleaned = category.casefold().strip()
        if cleaned not in GENERIC_CATEGORIES and 2 <= len(category.split()) <= 5:
            add(category)
    for token, _weight in sorted(profile.weighted_terms.items(), key=lambda pair: pair[1], reverse=True):
        add(token)
    return output[:limit]


def candidate_has_evidence(candidate: Book) -> bool:
    meaningful_categories = {
        c.casefold().strip() for c in candidate.categories
        if c and c.casefold().strip() not in GENERIC_CATEGORIES
    }
    has_author = bool(candidate.authors and candidate.author_text.casefold() not in {"unknown author", "unknown"})
    description = candidate.description.strip()
    has_content = len(description) >= 45 or len(meaningful_categories) >= 2
    return has_author and has_content


def _audience_mismatch(seed: BookProfile, candidate: BookProfile) -> bool:
    if not seed.target_audiences or not candidate.target_audiences:
        return False
    adult_seed = "adult" in seed.target_audiences
    underage_candidate = bool(candidate.target_audiences & {"children", "middle_grade", "young_adult"})
    if adult_seed and underage_candidate:
        return True
    if "young_adult" in seed.target_audiences:
        if candidate.target_audiences & {"children", "middle_grade"}:
            return True
        if "adult" in candidate.target_audiences and candidate.content_level_value >= CONTENT_LEVEL_ORDER["mature"]:
            return True
    underage_seed = bool(seed.target_audiences & {"children", "middle_grade"})
    adult_candidate = "adult" in candidate.target_audiences
    return underage_seed and adult_candidate and candidate.content_level_value >= CONTENT_LEVEL_ORDER["mature"]


def _audience_similarity(seed: BookProfile, candidate: BookProfile) -> float:
    if not seed.target_audiences or not candidate.target_audiences:
        return 0.35
    if seed.target_audiences & candidate.target_audiences:
        return 1.0
    pair = {seed.primary_audience, candidate.primary_audience}
    if pair == {"young_adult", "adult"}:
        return 0.35
    if pair == {"young_adult", "middle_grade"}:
        return 0.15
    return 0.0


def _content_mismatch(seed: BookProfile, candidate: BookProfile) -> bool:
    seed_level = seed.content_level_value
    candidate_level = candidate.content_level_value
    if seed_level >= CONTENT_LEVEL_ORDER["extreme"] and candidate_level <= CONTENT_LEVEL_ORDER["teen"]:
        return True
    if seed_level <= CONTENT_LEVEL_ORDER["family"] and candidate_level >= CONTENT_LEVEL_ORDER["mature"]:
        return True
    return False


def is_hard_mismatch(seed: Book, candidate: Book) -> bool:
    # Recommendation cards must be readable in the app's English-first interface.
    # Catalogue language labels can be wrong, so the actual synopsis is inspected too.
    if book_language_status(candidate) == "non_english":
        return True

    seed_profile = profile_book(seed)
    candidate_profile = profile_book(candidate)

    if seed_profile.fiction_status in {"fiction", "nonfiction"} and candidate_profile.fiction_status in {"fiction", "nonfiction"}:
        if seed_profile.fiction_status != candidate_profile.fiction_status:
            return True

    seed_type = seed_profile.primary_work_type
    candidate_type = candidate_profile.primary_work_type

    # Academic/reference material about a genre is not a recommendation for a story
    # in that genre. This rule fixes false matches such as literary criticism being
    # returned for a horror novel merely because both contain the word "horror".
    if seed_profile.fiction_status == "fiction" and candidate_type in ACADEMIC_TYPES | {"essay_collection", "cookbook", "guidebook", "manual", "self_help"}:
        return True
    if seed_type in ACADEMIC_TYPES and candidate_profile.fiction_status == "fiction":
        return True

    if _audience_mismatch(seed_profile, candidate_profile) or _content_mismatch(seed_profile, candidate_profile):
        return True

    # Extreme/explicit adult horror must not collapse into generic YA, juvenile or mild franchise horror.
    if "extreme_horror" in seed_profile.subgenres:
        if "extreme_horror" not in candidate_profile.subgenres:
            strong_adjacent = (
                "horror" in candidate_profile.genres
                and "violent" in candidate_profile.tones
                and bool(seed_profile.themes & candidate_profile.themes)
            )
            if not strong_adjacent:
                return True
        if candidate_profile.target_audiences & {"children", "middle_grade", "young_adult"}:
            return True

    if "picture_book" in candidate_profile.work_types and "picture_book" not in seed_profile.work_types:
        return True
    if "picture_book" in seed_profile.work_types and "picture_book" not in candidate_profile.work_types:
        return True
    return False


def _weighted_overlap(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    numerator = sum(min(left[token], right[token]) for token in shared)
    denominator = sum(max(left.get(token, 0.0), right.get(token, 0.0)) for token in set(left) | set(right))
    return numerator / denominator if denominator else 0.0


def _set_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)


def _candidate_quality(book: Book) -> float:
    quality = 0.0
    quality += 0.35 if len(book.description) >= 100 else 0.12 if book.description else 0.0
    quality += 0.20 if len([c for c in book.categories if c.casefold() not in GENERIC_CATEGORIES]) >= 2 else 0.0
    quality += 0.15 if book.best_cover else 0.0
    quality += 0.10 if book.page_count else 0.0
    quality += 0.10 if book.published_year else 0.0
    quality += 0.10 if book.authors else 0.0
    return min(quality, 1.0)


def _duplicate(seed: Book, candidate: Book) -> bool:
    if seed.uid == candidate.uid:
        return True
    if seed.primary_isbn and candidate.primary_isbn and seed.primary_isbn == candidate.primary_isbn:
        return True
    seed_title = _normalise(seed.title)
    candidate_title = _normalise(candidate.title)
    seed_authors = {_normalise(name) for name in seed.authors}
    candidate_authors = {_normalise(name) for name in candidate.authors}
    return seed_title == candidate_title and bool(seed_authors & candidate_authors)



def _work_type_overlap(seed: BookProfile, candidate: BookProfile) -> float:
    left = seed.primary_work_type
    right = candidate.primary_work_type
    if left == "unknown" or right == "unknown":
        return 0.30
    if left == right:
        return 1.0
    if left in LONGFORM_FICTION_TYPES and right in LONGFORM_FICTION_TYPES:
        return 0.78
    if left in SHORTFORM_FICTION_TYPES and right in SHORTFORM_FICTION_TYPES:
        return 0.72
    if {left, right} <= (LONGFORM_FICTION_TYPES | SHORTFORM_FICTION_TYPES):
        return 0.20
    if {left, right} <= {"memoir", "biography"}:
        return 0.55
    return 0.0

def similarity_components(seed: Book, candidate: Book) -> dict[str, float]:
    if _duplicate(seed, candidate) or is_hard_mismatch(seed, candidate) or not candidate_has_evidence(candidate):
        return {"total": -1.0}

    sp = profile_book(seed)
    cp = profile_book(candidate)
    genre = _set_overlap(sp.genres, cp.genres)
    subgenre = _set_overlap(sp.subgenres, cp.subgenres)
    theme = _set_overlap(sp.themes, cp.themes)
    tone = _set_overlap(sp.tones, cp.tones)
    fmt = _set_overlap(sp.formats, cp.formats)
    work_type = _work_type_overlap(sp, cp)
    lexical = _weighted_overlap(sp.weighted_terms, cp.weighted_terms)

    audience = _audience_similarity(sp, cp)
    content = max(0.0, 1.0 - abs(sp.content_level_value - cp.content_level_value) / 4.0)
    character_age = _set_overlap(sp.character_ages, cp.character_ages)
    seed_specific_themes = sp.themes & HIGH_SPECIFICITY_THEMES
    candidate_specific_themes = cp.themes & HIGH_SPECIFICITY_THEMES
    specific_theme = _set_overlap(seed_specific_themes, candidate_specific_themes)

    strong_seed = bool(sp.subgenres) or len(sp.themes) >= 2
    meaningful_overlap = subgenre > 0 or theme >= 0.25 or lexical >= 0.055
    if strong_seed and not meaningful_overlap:
        return {"total": -1.0}
    if sp.genres and cp.genres and genre == 0 and subgenre == 0 and lexical < 0.08:
        return {"total": -1.0}
    if not sp.genres and lexical < 0.045 and theme == 0 and subgenre == 0:
        return {"total": -1.0}

    # When a book has distinctive subject matter—mental illness, grief, captivity,
    # disability, addiction, a specialised setting, etc.—a recommendation must share
    # at least one of those anchors or a closely matching subgenre. This prevents a
    # generic mystery/coming-of-age overlap from outranking the book's actual identity.
    if seed_specific_themes and not (seed_specific_themes & candidate_specific_themes):
        if subgenre == 0 and (lexical < 0.18 or audience < 0.75):
            return {"total": -1.0}

    # A broad subject plus a broad tone is not enough when the actual kind of book
    # differs. This catches "horror criticism" vs "horror novel" and similar cases.
    specific_overlap_count = (
        len(sp.subgenres & cp.subgenres)
        + len(sp.themes & cp.themes)
        + len(sp.tones & cp.tones)
    )
    if work_type == 0.0 and specific_overlap_count < 2 and lexical < 0.10:
        return {"total": -1.0}

    total = (
        0.15 * genre
        + 0.23 * subgenre
        + 0.17 * theme
        + 0.12 * specific_theme
        + 0.06 * tone
        + 0.09 * audience
        + 0.06 * content
        + 0.01 * character_age
        + 0.01 * fmt
        + 0.06 * work_type
        + 0.04 * lexical
    )

    seed_authors = {_normalise(name) for name in seed.authors}
    candidate_authors = {_normalise(name) for name in candidate.authors}
    same_author = bool(seed_authors & candidate_authors)
    if same_author:
        total -= 0.025

    seed_language = normalise_language_code(seed.language)
    candidate_language = normalise_language_code(candidate.language)
    if seed_language and candidate_language and seed_language == candidate_language:
        total += 0.014
    elif book_language_status(candidate) == "english":
        total += 0.008
    if seed.page_count and candidate.page_count:
        distance = abs(seed.page_count - candidate.page_count)
        total += 0.020 * max(0.0, 1.0 - distance / max(seed.page_count, 220))
    if seed.published_year and candidate.published_year:
        distance = abs(seed.published_year - candidate.published_year)
        total += 0.014 * max(0.0, 1.0 - distance / 60)
    if candidate.average_rating is not None:
        total += 0.018 * max(0.0, min(candidate.average_rating / 5.0, 1.0))
    total += 0.008 * min(math.log10(candidate.ratings_count + 1) / 5.0, 1.0)
    total += 0.020 * _candidate_quality(candidate)

    return {
        "total": round(total, 6),
        "genre": genre,
        "subgenre": subgenre,
        "theme": theme,
        "specific_theme": specific_theme,
        "tone": tone,
        "audience": audience,
        "content": content,
        "character_age": character_age,
        "format": fmt,
        "work_type": work_type,
        "lexical": lexical,
        "same_author": 1.0 if same_author else 0.0,
        "specific_overlap_count": float(specific_overlap_count),
    }


def similarity_score(seed: Book, candidate: Book) -> float:
    return similarity_components(seed, candidate)["total"]


def _display_signal(value: str) -> str:
    special = {
        "science_fiction": "science fiction",
        "historical_fiction": "historical fiction",
        "literary_fiction": "literary fiction",
        "young_adult": "young adult",
        "middle_grade": "middle grade",
        "extreme_horror": "extreme horror",
        "psychological_horror": "psychological horror",
        "psychological_thriller": "psychological thriller",
        "dark_romance": "dark romance",
        "epic_fantasy": "epic fantasy",
        "urban_fantasy": "urban fantasy",
        "space_opera": "space opera",
        "time_travel": "time travel",
        "found_family": "found family",
        "coming_of_age": "coming of age",
        "deadly_game": "deadly game",
        "serial_killer": "serial killer",
        "fast_paced": "fast-paced",
        "slow_burn": "slow burn",
        "short_stories": "short-story collection",
        "essay_collection": "essay collection",
        "academic_criticism": "academic criticism",
        "graphic_novel": "graphic novel",
        "picture_book": "picture book",
        "young_adult_contemporary": "YA contemporary",
        "mental_health_fiction": "mental-health fiction",
        "social_issue_fiction": "social-issue fiction",
        "mental_health": "mental health",
        "obsessive_compulsive_disorder": "OCD",
        "self_discovery": "self-discovery",
        "first_love": "first love",
        "school_life": "school life",
        "missing_person": "missing person",
        "social_injustice": "social injustice",
        "chronic_illness": "chronic illness",
        "children": "children",
        "teenagers": "teen characters",
        "adults": "adult characters",
        "family": "family-safe content",
        "teen": "teen-level content",
        "mature": "mature content",
        "extreme": "extreme content",
    }
    return special.get(value, value.replace("_", " "))


def profile_summary(book: Book, limit: int = 8) -> tuple[str, ...]:
    profile = profile_book(book)
    values: list[str] = []

    def add(value: str) -> None:
        label = _display_signal(value)
        if label and label not in values:
            values.append(label)

    if profile.primary_audience != "unknown":
        add(profile.primary_audience)
    if profile.content_level in {"mature", "extreme"}:
        add(profile.content_level)
    for value in sorted(profile.subgenres):
        add(value)
    for value in sorted(profile.themes & HIGH_SPECIFICITY_THEMES):
        add(value)
    for value in sorted(profile.genres):
        add(value)
    for value in sorted(profile.themes - HIGH_SPECIFICITY_THEMES):
        add(value)
    return tuple(values[:limit])


def recommendation_reasons(seed: Book, candidate: Book, components: dict[str, float]) -> tuple[str, ...]:
    sp = profile_book(seed)
    cp = profile_book(candidate)
    reasons: list[str] = []

    def add_shared(values: set[str], prefix: str = "") -> None:
        for value in sorted(values):
            label = _display_signal(value)
            reason = f"{prefix}{label}" if prefix else label
            if reason not in reasons:
                reasons.append(reason)

    add_shared(sp.subgenres & cp.subgenres)
    add_shared((sp.themes & cp.themes) & HIGH_SPECIFICITY_THEMES)
    add_shared(sp.genres & cp.genres)
    add_shared((sp.themes & cp.themes) - HIGH_SPECIFICITY_THEMES)
    add_shared(sp.tones & cp.tones)
    if sp.primary_work_type != "unknown" and sp.primary_work_type == cp.primary_work_type:
        reasons.append("same book type: " + _display_signal(sp.primary_work_type))
    if sp.target_audiences & cp.target_audiences:
        add_shared(sp.target_audiences & cp.target_audiences, "same target audience: ")
    if sp.content_level == cp.content_level and sp.content_level in {"mature", "extreme"}:
        reasons.append("same content intensity: " + _display_signal(sp.content_level))
    if sp.character_ages & cp.character_ages:
        add_shared(sp.character_ages & cp.character_ages, "similar character focus: ")
    if components.get("lexical", 0.0) >= 0.08:
        reasons.append("similar plot and subject language")
    if components.get("same_author"):
        reasons.append("same author")
    return tuple(reasons[:5]) or ("closest available metadata match",)


def _candidate_pair_similarity(left: Book, right: Book) -> float:
    lp = profile_book(left)
    rp = profile_book(right)
    same_author = bool({_normalise(a) for a in left.authors} & {_normalise(a) for a in right.authors})
    return min(
        1.0,
        0.35 * _set_overlap(lp.genres, rp.genres)
        + 0.30 * _set_overlap(lp.subgenres, rp.subgenres)
        + 0.20 * _set_overlap(lp.themes, rp.themes)
        + 0.15 * (1.0 if same_author else 0.0),
    )


def _match_display(score: float, components: dict[str, float]) -> tuple[int, str]:
    """Calibrate an honest display score from absolute evidence, not list position."""
    raw = round(34 + 62 * (1.0 - math.exp(-2.15 * max(score, 0.0))))
    specific = int(components.get("specific_overlap_count", 0.0))
    if components.get("subgenre", 0.0) == 0 and components.get("theme", 0.0) == 0:
        raw = min(raw, 62)
    if components.get("work_type", 0.0) < 0.5:
        raw = min(raw, 70)
    if specific < 2:
        raw = min(raw, 68)
    if score < 0.18:
        raw = min(raw, 54)
    elif score < 0.28:
        raw = min(raw, 64)
    elif score < 0.42:
        raw = min(raw, 76)
    percent = max(45, min(96, raw))
    label = (
        "Strong match" if percent >= 84 else
        "Good match" if percent >= 70 else
        "Possible match" if percent >= 58 else
        "Loose match"
    )
    return percent, label


def rank_similar_detailed(seed: Book, candidates: list[Book], limit: int = 12) -> list[RecommendationResult]:
    scored: list[tuple[float, Book, dict[str, float]]] = []
    for candidate in candidates:
        components = similarity_components(seed, candidate)
        score = components.get("total", -1.0)
        if score >= 0:
            scored.append((score, candidate, components))
    scored.sort(key=lambda row: row[0], reverse=True)
    if not scored:
        return []

    seed_profile = profile_book(seed)
    floor = 0.14 if seed_profile.confidence >= 0.65 else 0.11 if seed_profile.confidence >= 0.35 else 0.085
    best = scored[0][0]
    floor = min(floor, max(0.075, best * 0.42))

    selected: list[tuple[float, Book, dict[str, float]]] = []
    remaining = [row for row in scored if row[0] >= floor]
    same_author_count = 0
    seed_authors = {_normalise(a) for a in seed.authors}
    seen_titles: set[str] = set()

    while remaining and len(selected) < limit:
        best_index = -1
        best_mmr = -999.0
        for index, (score, candidate, components) in enumerate(remaining):
            title_key = _normalise(re.sub(r"\b(a novel|a memoir|stories|the complete edition)\b", "", candidate.title, flags=re.I))
            if not title_key or title_key in seen_titles:
                continue
            candidate_authors = {_normalise(a) for a in candidate.authors}
            same_author = bool(seed_authors & candidate_authors)
            if same_author and same_author_count >= 2:
                continue
            redundancy = max((_candidate_pair_similarity(candidate, chosen[1]) for chosen in selected), default=0.0)
            mmr = score - 0.10 * redundancy
            if mmr > best_mmr:
                best_mmr = mmr
                best_index = index
        if best_index < 0:
            break
        row = remaining.pop(best_index)
        score, candidate, components = row
        same_author = bool(seed_authors & {_normalise(a) for a in candidate.authors})
        if same_author:
            same_author_count += 1
        seen_titles.add(_normalise(re.sub(r"\b(a novel|a memoir|stories|the complete edition)\b", "", candidate.title, flags=re.I)))
        selected.append(row)

    results: list[RecommendationResult] = []
    for score, candidate, components in selected:
        match_percent, match_label = _match_display(score, components)
        results.append(
            RecommendationResult(
                book=candidate,
                score=score,
                reasons=recommendation_reasons(seed, candidate, components),
                match_percent=match_percent,
                match_label=match_label,
            )
        )
    return results


def rank_similar(seed: Book, candidates: list[Book], limit: int = 12) -> list[Book]:
    return [result.book for result in rank_similar_detailed(seed, candidates, limit)]


def smart_match_score(book: Book, plan: SmartSearchPlan) -> float:
    haystack = " ".join(
        [book.title, book.subtitle, book.author_text, book.description, book.category_text]
    ).casefold()
    score = 0.0

    for genre in plan.genres:
        score += 2.0 if genre.casefold() in haystack else 0.0
    for trope in plan.tropes:
        score += 2.2 if trope.casefold() in haystack else 0.0
    if plan.author and plan.author.casefold() in book.author_text.casefold():
        score += 3.0
    if plan.similar_to and plan.similar_to.casefold() in book.title.casefold():
        score += 1.0

    if plan.min_pages is not None:
        score += 0.6 if book.page_count and book.page_count >= plan.min_pages else -1.0
    if plan.max_pages is not None:
        score += 0.6 if book.page_count and book.page_count <= plan.max_pages else -1.0
    if plan.year_from is not None:
        score += 0.5 if book.published_year and book.published_year >= plan.year_from else -0.5
    if plan.year_to is not None:
        score += 0.5 if book.published_year and book.published_year <= plan.year_to else -0.5

    for term in plan.negative_terms:
        if term.casefold() in haystack:
            score -= 3.0

    if book.average_rating is not None:
        score += book.average_rating / 10
    score += min(math.log10(book.ratings_count + 1), 5) / 10
    return score


def rank_smart_results(books: list[Book], plan: SmartSearchPlan) -> list[Book]:
    return sorted(books, key=lambda book: smart_match_score(book, plan), reverse=True)


def favourite_categories(books: list[Book], limit: int = 8) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for book in books:
        counter.update(book.categories)
    return counter.most_common(limit)
