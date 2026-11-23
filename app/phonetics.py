"""Moteur d'interprétation des notations Clun'ss et de comparaison orthographique / phonétique française."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import re
import unicodedata


@dataclass(frozen=True)
class PhoneticProfile:
    raw: str
    visual_clean: str
    expanded_readings: tuple[str, ...]
    visual_readings: tuple[str, ...]
    phonetic_readings: tuple[str, ...]
    primary_phonetic: str
    explanation: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "visual_clean": self.visual_clean,
            "expanded_readings": list(self.expanded_readings),
            "phonetic_readings": list(self.phonetic_readings),
            "primary_phonetic": self.primary_phonetic,
            "explanation": list(self.explanation),
        }


_SYMBOL_MAP = {
    "∞": "oo",
    "π": "pi",
    "Π": "pi",
    "φ": "fi",
    "Φ": "fi",
    "Ω": "o",
    "ω": "o",
    "α": "alfa",
    "Α": "alfa",
    "τ": "to",
    "Τ": "to",
    "µ": "mu",
    "μ": "mu",
    "&": "et",
    "$": "s",
    "€": "e",
    "!": "i",
    "@": "a",
    "æ": "e",
    "Æ": "e",
    "œ": "eu",
    "Œ": "eu",
    "ø": "eu",
    "Ø": "eu",
}

_PRONONCE_RE = re.compile(r"\(\s*prononc[eé]\s+([^)]+)\)", re.IGNORECASE)
_H2O_RE = re.compile(r"\(\s*h2[o0]\s*\)|\[\s*h2[o0]\s*\]|\bh2[o0]\b", re.IGNORECASE)

# Puissance 0 : (mot)^0, [mot]^0, (mot)⁰, (mot)°, (mot)**0
_POW0_GROUP_RE = re.compile(
    r"(?:\(((?:[^()]|\([^()]*\))+)\)|\[([^\[\]]+)\])\s*(?:\^\s*0|\*\*\s*0|[⁰°])"
)
# Lettre isolée puissance 0 : x^0, x⁰
_POW0_CHAR_RE = re.compile(r"[A-Za-zÀ-ÿ]\s*(?:\^\s*0|\*\*\s*0|⁰)")

# Transposée : (mot)^T, (mot)^t, [mot]^T, (mot)^(T), (mot)**T, (mot)ᵗ, (mot)ᵀ, (mot)⊤
# Supporte un niveau d'accolades/parenthèses imbriquées comme (Art[s])^T
_TRANSPOSE_GROUP_RE = re.compile(
    r"(?:\(((?:[^()]|\([^()]*\))+)\)|\[([^\[\]]+)\])\s*(?:\^\s*\(?[tT]\)?|\*\*\s*[tT]|[ᵗᵀ⊤])"
)
# Mot collé avant ^T / ^t / ᵗ / ᵀ / ⊤ sans parenthèses : ex GO^t(ARTS)
_TRANSPOSE_WORD_RE = re.compile(
    r"([A-Za-zÀ-ÿ]+)\s*(?:\^\s*[tT]|\*\*\s*[tT]|[ᵗᵀ⊤])"
)
# Transposée préfixée à la française : ᵀ(mot), ᵗ(mot), ⊤(mot), ^T(mot), ^t(mot)
_TRANSPOSE_PREFIX_GROUP_RE = re.compile(
    r"(?:\^\s*\(?[tT]\)?|[ᵗᵀ⊤])\s*(?:\(((?:[^()]|\([^()]*\))+)\)|\[([^\[\]]+)\])"
)

# Puissances 2 (carré : répétition ×2 ou lecture « karse »)
_POW2_GROUP_RE = re.compile(
    r"(?:\(((?:[^()]|\([^()]*\))+)\)|\[([^\[\]]+)\])\s*(?:\^\s*2|²|(?<![A-Za-zÀ-ÿ])2(?![0-9]))"
)
_POW2_WORD_RE = re.compile(r"([A-Za-zÀ-ÿ]+)\s*(?:\^\s*2|²)")
_POW2_STANDALONE_RE = re.compile(r"\^\s*2|²")
_HAS_POW2_RE = re.compile(r"²|\^\s*2")

# Puissances 3 sur groupe ou mot : [mot]^3, mot³, P^3
_POW3_GROUP_RE = re.compile(
    r"(?:\(((?:[^()]|\([^()]*\))+)\)|\[([^\[\]]+)\])\s*(?:\^\s*3|³|(?<![A-Za-zÀ-ÿ])3(?![0-9]))"
)
_POW3_WORD_RE = re.compile(r"([A-Za-zÀ-ÿ]+)\s*(?:\^\s*3|³)")

# Détection des parenthèses visuelles (arts) / [arts] / (art) / [art]
_ARTS_PAREN_RE = re.compile(
    r"[\(\[]\s*[aàâäā]rts?\s*[\)\]]", re.IGNORECASE
)


def _strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def normalize_visual(text: str) -> str:
    """Normalise une chaîne pour la comparaison orthographique (sans accents, casse ni ponctuation)."""
    if not text:
        return ""
    s = text.replace("æ", "ae").replace("Æ", "ae").replace("œ", "oe").replace("Œ", "oe")
    s = s.replace("ø", "o").replace("Ø", "o")
    s = _strip_accents(s).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _reverse_preserving_inner_brackets(group: str) -> str:
    cleaned = group.replace("[", "").replace("]", "").replace("(", "").replace(")", "")
    return cleaned[::-1]


def _resolve_non_pow2(text: str, steps: list[str] | None = None) -> str:
    """Résout ^0, les transposées (ᵀ/ᵗ/⊤/^T) et les cubes (³/^3) sans toucher aux carrés ²."""
    for _ in range(8):
        prev = text

        def _repl_pow0_group(m: re.Match) -> str:
            grp = m.group(1) if m.group(1) is not None else m.group(2)
            if steps is not None:
                steps.append(f"Puissance 0 supprimée : « ({grp})⁰ »")
            return ""

        text = _POW0_GROUP_RE.sub(_repl_pow0_group, text)

        def _repl_pow0_char(m: re.Match) -> str:
            if steps is not None:
                steps.append(f"Puissance 0 supprimée : « {m.group(0)} »")
            return ""

        text = _POW0_CHAR_RE.sub(_repl_pow0_char, text)

        def _repl_transpose_group(m: re.Match) -> str:
            grp = m.group(1) if m.group(1) is not None else m.group(2)
            if _HAS_POW2_RE.search(grp):
                return m.group(0)
            rev = _reverse_preserving_inner_brackets(grp)
            if steps is not None:
                steps.append(f"Transposée ({grp})ᵀ → « {rev} »")
            return rev

        text = _TRANSPOSE_GROUP_RE.sub(_repl_transpose_group, text)

        def _repl_transpose_word(m: re.Match) -> str:
            tok = m.group(1)
            rev = tok[::-1]
            if steps is not None:
                steps.append(f"Transposée {tok}ᵀ → « {rev} »")
            return rev

        text = _TRANSPOSE_WORD_RE.sub(_repl_transpose_word, text)

        def _repl_transpose_prefix_group(m: re.Match) -> str:
            grp = m.group(1) if m.group(1) is not None else m.group(2)
            if _HAS_POW2_RE.search(grp):
                return m.group(0)
            rev = _reverse_preserving_inner_brackets(grp)
            if steps is not None:
                steps.append(f"Transposée ᵀ({grp}) → « {rev} »")
            return rev

        text = _TRANSPOSE_PREFIX_GROUP_RE.sub(_repl_transpose_prefix_group, text)

        def _repl_pow3_group(m: re.Match) -> str:
            grp = m.group(1) if m.group(1) is not None else m.group(2)
            rep = grp * 3
            if steps is not None:
                steps.append(f"Puissance 3 : ({grp})³ → « {rep} »")
            return rep

        text = _POW3_GROUP_RE.sub(_repl_pow3_group, text)

        def _repl_pow3_word(m: re.Match) -> str:
            tok = m.group(1)
            rep = tok * 3
            if steps is not None:
                steps.append(f"Puissance 3 : {tok}³ → « {rep} »")
            return rep

        text = _POW3_WORD_RE.sub(_repl_pow3_word, text)

        if text == prev:
            break
    return text


def expand_buque_notations(raw: str) -> tuple[list[str], list[str]]:
    """
    Développe les notations spéciales Arts & Métiers / Clun'ss :
    - H2O -> o
    - Symboles grecs & mathématiques (π->pi, φ->fi, Ω->o, ∞->oo, ...)
    - (mot)^0 / ^0 / ⁰ -> supprimé (ne se lit pas)
    - (mot)^T / ᵗ / ᵀ / ⊤ / **T -> inversé (se lit à l'envers)
    - mot² / (mot)² -> double lecture : répétition ×2 du mot/groupe ET lecture « karse »
    - Parenthèses visuelles (ex: pompl(arts) -> pomplarts / pomplar / pomplart)
    """
    text = (raw or "").strip()
    if not text:
        return [""], []

    steps: list[str] = []
    extra_hints: list[str] = []

    # Indices explicites de prononciation, ex: "Traxex (prononcé Trazex)"
    def _extract_hint(m: re.Match) -> str:
        hint = m.group(1).strip()
        if hint:
            extra_hints.append(hint)
            steps.append(f"Indication explicite : « {hint} »")
        return ""

    text = _PRONONCE_RE.sub(_extract_hint, text).strip()

    # (H2O) / H2O -> o avant de traiter les chiffres/exposants et symboles
    new_text = _H2O_RE.sub("o", text)
    if new_text != text:
        steps.append(f"H2O → « o » : {new_text}")
        text = new_text

    # Substitutions de symboles grecs / mathématiques avant ² (ex: π² -> pi²)
    sym_replaced = []
    changed_sym = False
    for ch in text:
        if ch in _SYMBOL_MAP:
            sym_replaced.append(_SYMBOL_MAP[ch])
            changed_sym = True
        else:
            sym_replaced.append(ch)
    if changed_sym:
        text = "".join(sym_replaced)
        steps.append(f"Symboles → « {text} »")

    # Résolution des notations hors ²
    text = _resolve_non_pow2(text, steps)

    # Gestion du carré ² / ^2 : génère répétition ×2 ET lecture « karse »
    has_pow2 = bool(
        _POW2_GROUP_RE.search(text)
        or _POW2_WORD_RE.search(text)
        or _POW2_STANDALONE_RE.search(text)
    )
    if has_pow2:
        branch_repeat = text
        for _ in range(8):
            prev = branch_repeat
            branch_repeat = _POW2_GROUP_RE.sub(lambda m: (m.group(1) if m.group(1) is not None else m.group(2)) * 2, branch_repeat)
            branch_repeat = _POW2_WORD_RE.sub(lambda m: m.group(1) * 2, branch_repeat)
            if branch_repeat == prev:
                break
        branch_repeat = _resolve_non_pow2(branch_repeat)

        branch_karse = text
        for _ in range(8):
            prev = branch_karse
            branch_karse = _POW2_GROUP_RE.sub(
                lambda m: f"{m.group(1) if m.group(1) is not None else m.group(2)}karse",
                branch_karse,
            )
            branch_karse = _POW2_WORD_RE.sub(lambda m: f"{m.group(1)}karse", branch_karse)
            if branch_karse == prev:
                break
        branch_karse = _POW2_STANDALONE_RE.sub("karse", branch_karse)
        branch_karse = _resolve_non_pow2(branch_karse)

        clean_rep = re.sub(r"[()\[\]]", "", branch_repeat)
        clean_karse = re.sub(r"[()\[\]]", "", branch_karse)
        steps.append(
            f"Carré ² : répétition ×2 → « {clean_rep} » / lecture « karse » → « {clean_karse} »"
        )
        branches = [branch_repeat, branch_karse]
    else:
        branches = [text]

    # Génération des lectures avec parenthèses visuelles (notamment (arts) / (art))
    readings: list[str] = []

    def _add_reading(candidate: str) -> None:
        cleaned = re.sub(r"[()\[\]]", "", candidate).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned and cleaned not in readings:
            readings.append(cleaned)

    logged_paren_step = False
    for branch in branches:
        has_arts_paren = bool(_ARTS_PAREN_RE.search(branch))
        if has_arts_paren:
            spoken_ar = _ARTS_PAREN_RE.sub("ar", branch)
            spoken_art = _ARTS_PAREN_RE.sub("art", branch)
            literal_arts = _ARTS_PAREN_RE.sub(
                lambda m: re.sub(r"[\(\)\[\]\s]", "", m.group(0)), branch
            )
            _add_reading(spoken_ar)
            _add_reading(spoken_art)
            _add_reading(literal_arts)
            if not logged_paren_step:
                clean_spoken = re.sub(r"[()\[\]]", "", spoken_ar)
                clean_literal = re.sub(r"[()\[\]]", "", literal_arts)
                steps.append(
                    f"Parenthèses visuelles (arts) → « {clean_spoken} » / « {clean_literal} »"
                )
                logged_paren_step = True
        else:
            if not logged_paren_step and ("(" in branch or ")" in branch or "[" in branch or "]" in branch):
                clean_text = re.sub(r"[()\[\]]", "", branch)
                steps.append(
                    f"Parenthèses visuelles supprimées → « {clean_text} »"
                )
                logged_paren_step = True
            _add_reading(branch)

    for hint in extra_hints:
        _add_reading(hint)

    if not readings:
        readings = [re.sub(r"[()\[\]]", "", raw).strip() or raw.strip()]

    return readings, steps


def phonetize_fr(text: str) -> list[str]:
    """
    Encode une chaîne française en représentations phonétiques normalisées.
    Retourne une liste ordonnée de variantes (principale en premier, puis variante sans 's' final).
    """
    if not text:
        return [""]

    s = text.lower()
    # Ligatures avant suppression des accents
    s = s.replace("æ", "e").replace("œ", "eu").replace("ø", "eu").replace("ç", "s")
    # Préserver les 'e' accentués prononcés (é, è, ê, ë) avec la sentinelle 'E'
    s = re.sub(r"[éèêë]", "E", s)
    # Normaliser les accents restants sans toucher à 'E'
    out_chars = []
    for ch in s:
        if ch == "E":
            out_chars.append("E")
        else:
            out_chars.append(_strip_accents(ch))
    s = "".join(out_chars)

    # Apostrophes collées (Cairn's -> cairns, K'nass -> knass), tirets et symboles en espaces
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"[^a-zE0-9]+", " ", s).strip()
    if not s:
        return [""]

    # Règles de transformation phonétique française (sensibles à la sentinelle 'E')
    s = s.replace("ph", "f")
    s = re.sub(r"ch(?=[rl])", "k", s)
    s = re.sub(r"sch|sh|ch", "X", s)
    s = s.replace("th", "t")
    s = s.replace("h", "")

    # Voyelles composées et semi-voyelles
    s = re.sub(r"eau|au", "o", s)
    s = re.sub(r"ou|oo", "U", s)
    s = re.sub(r"oi(?=n(?![aeiouyEUO]))", "w1", s)  # oin -> w1 (avant oi -> wa)
    s = re.sub(r"oi|oy", "wa", s)
    s = re.sub(r"ai|ei|ay|ey", "E", s)
    s = re.sub(r"eu|oeu", "O", s)

    # Consonnes contextuelles avant remplacement des nasales
    s = s.replace("gn", "ni")
    s = s.replace("qu", "k")
    s = re.sub(r"gu(?=[eiyE])", "g", s)
    s = re.sub(r"ge(?=[aouU])", "J", s)
    s = re.sub(r"g(?=[eiyE])", "J", s)
    s = s.replace("j", "J")
    s = re.sub(r"c(?=[eiyE])", "s", s)
    s = s.replace("ck", "k").replace("q", "k").replace("c", "k")
    s = s.replace("x", "ks")
    s = re.sub(r"(?<=[aeiouyEUO])s(?=[aeiouyEUO])", "z", s)
    s = s.replace("y", "i")

    # Voyelles nasales (uniquement si suivies ni d'une voyelle, ni d'une autre nasale)
    s = re.sub(r"(?:ain|ein|aim|in|im|un|um)(?![aeiouyEUO123mn])", "1", s)
    s = re.sub(r"(?:an|am|en|em)(?![aeiouyEUO123mn])", "2", s)
    s = re.sub(r"(?:on|om)(?![aeiouyEUO123mn])", "3", s)

    # Finales muettes par mot (avant réduction des doubles lettres)
    words = s.split()
    primary_words: list[str] = []
    alt_words: list[str] = []
    has_alt = False

    for w in words:
        pw = w
        if len(pw) >= 4:
            # pomplart / pomplard / pomplarts / pomplar -> même terminaison 'r'
            pw = re.sub(r"r(?:ts|ds|t|d)$", "r", pw)
            # 'e' muet final (mais pas 'E' accentué)
            if pw.endswith("e") and len(pw) >= 4:
                pw = pw[:-1]
                pw = re.sub(r"r(?:ts|ds|t|d)$", "r", pw)

        # Variante sans 's' final isolé (ex: Cairn's vs Cairn, Arts vs Art)
        aw = pw
        if len(pw) >= 4 and pw.endswith("s") and not pw.endswith("ss"):
            aw = pw[:-1]
            if len(aw) >= 4:
                aw = re.sub(r"r(?:ts|ds|t|d)$", "r", aw)
            has_alt = True

        # Réduire les consonnes/voyelles doublées consécutives (ll->l, ss->s, pp->p...)
        pw = re.sub(r"(.)\1+", r"\1", pw)
        aw = re.sub(r"(.)\1+", r"\1", aw)
        primary_words.append(pw)
        alt_words.append(aw)

    variants: list[str] = []
    p_joined = "".join(primary_words)
    if p_joined:
        variants.append(p_joined)
    if has_alt:
        a_joined = "".join(alt_words)
        if a_joined and a_joined not in variants:
            variants.append(a_joined)

    return variants or [""]


@lru_cache(maxsize=8192)
def build_profile(raw: str) -> PhoneticProfile:
    """Construit et met en cache le profil complet (visuel + lectures + phonétique) d'une buque."""
    raw_str = (raw or "").strip()
    if not raw_str:
        return PhoneticProfile(
            raw="",
            visual_clean="",
            expanded_readings=("",),
            visual_readings=("",),
            phonetic_readings=("",),
            primary_phonetic="",
            explanation=(),
        )

    readings, steps = expand_buque_notations(raw_str)
    visual_clean = normalize_visual(readings[0]) or normalize_visual(raw_str)

    visual_readings: list[str] = []
    for r in readings:
        vr = normalize_visual(r)
        if vr and vr not in visual_readings:
            visual_readings.append(vr)
    if visual_clean and visual_clean not in visual_readings:
        visual_readings.append(visual_clean)

    phonetics: list[str] = []
    for r in readings:
        for ph in phonetize_fr(r):
            if ph and ph not in phonetics:
                phonetics.append(ph)

    if not phonetics:
        phonetics = [visual_clean] if visual_clean else [""]

    return PhoneticProfile(
        raw=raw_str,
        visual_clean=visual_clean,
        expanded_readings=tuple(readings),
        visual_readings=tuple(visual_readings or [""]),
        phonetic_readings=tuple(phonetics),
        primary_phonetic=phonetics[0],
        explanation=tuple(steps),
    )


@lru_cache(maxsize=65536)
def _levenshtein_bounded_cached(a: str, b: str, max_dist: int) -> int:
    la, lb = len(a), len(b)
    prev = list(range(la + 1))
    for j in range(1, lb + 1):
        bj = b[j - 1]
        curr = [j] + [0] * la
        row_min = j
        for i in range(1, la + 1):
            cost = 0 if a[i - 1] == bj else 1
            val = min(
                prev[i] + 1,      # suppression
                curr[i - 1] + 1,  # insertion
                prev[i - 1] + cost,  # substitution
            )
            curr[i] = val
            if val < row_min:
                row_min = val
        if row_min > max_dist:
            return max_dist + 1
        prev = curr
    return prev[la]


def _levenshtein_bounded(a: str, b: str, max_dist: int) -> int:
    """Distance de Levenshtein optimisée avec borne supérieure et cache LRU."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    if la > lb or (la == lb and a > b):
        a, b = b, a
        la, lb = lb, la
    if la == 0:
        return lb
    return _levenshtein_bounded_cached(a, b, max_dist)


def string_similarity(a: str, b: str, min_threshold: float = 0.0) -> float:
    """Calcule la similarité normalisée [0.0, 1.0] avec élagage par ratio de longueur."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    max_len = max(la, lb)
    min_len = min(la, lb)

    # Garde anti faux-positifs sur les chaînes très courtes (<= 3 caractères, ex: Bob vs Rob)
    if min_len <= 3:
        return 0.0

    # Élagage immédiat par différence de longueur
    if min_threshold > 0.0:
        upper_bound = 1.0 - (la - lb if la > lb else lb - la) / max_len
        if upper_bound < min_threshold:
            return 0.0
        max_dist = int(max_len * (1.0 - min_threshold) + 1e-9)
    else:
        max_dist = max_len

    dist = _levenshtein_bounded(a, b, max_dist)
    if dist > max_dist:
        return 0.0
    return max(0.0, 1.0 - dist / max_len)


def compare_profiles(
    p1: PhoneticProfile,
    p2: PhoneticProfile,
    min_threshold: float = 0.5,
    include_prefix: bool = False,
) -> tuple[float, float, float]:
    """
    Compare deux PhoneticProfile.
    Retourne (best_score, ortho_score, phon_score) dans [0.0, 1.0].
    """
    if not p1.raw or not p2.raw:
        return 0.0, 0.0, 0.0

    # Comparaison orthographique sur toutes les lectures développées normalisées
    ortho_best = 0.0
    for v1 in p1.visual_readings:
        if not v1:
            continue
        for v2 in p2.visual_readings:
            if not v2:
                continue
            if v1 == v2:
                ortho_best = 1.0
                break
            sim = string_similarity(v1, v2, min_threshold=min_threshold)
            if sim > ortho_best:
                ortho_best = sim
            if include_prefix:
                mn = min(len(v1), len(v2))
                mx = max(len(v1), len(v2))
                if mn >= 5 and mn / mx >= 0.70 and (v1.startswith(v2) or v2.startswith(v1)):
                    ortho_best = max(ortho_best, mn / mx + 0.08)
        if ortho_best == 1.0:
            break

    # Comparaison phonétique sur toutes les variantes
    phon_best = 0.0
    for ph1 in p1.phonetic_readings:
        if not ph1:
            continue
        for ph2 in p2.phonetic_readings:
            if not ph2:
                continue
            if ph1 == ph2:
                phon_best = 1.0
                break
            sim = string_similarity(ph1, ph2, min_threshold=min_threshold)
            if sim > phon_best:
                phon_best = sim
            if include_prefix:
                mn = min(len(ph1), len(ph2))
                mx = max(len(ph1), len(ph2))
                if mn >= 5 and mn / mx >= 0.70 and (ph1.startswith(ph2) or ph2.startswith(ph1)):
                    phon_best = max(phon_best, mn / mx + 0.08)
        if phon_best == 1.0:
            break

    ortho_best = min(1.0, round(ortho_best, 4))
    phon_best = min(1.0, round(phon_best, 4))
    best = max(ortho_best, phon_best)
    return best, ortho_best, phon_best


def is_match(
    p1: PhoneticProfile,
    p2: PhoneticProfile,
    threshold: float,
    mode: str = "r12",
) -> tuple[bool, float, float, float]:
    """
    Évalue si deux profils correspondent selon le seuil et les gardes anti-bruit.
    mode="r12" (Règles 1 & 2) ou mode="r3" (Règle 3 ressemblance).
    """
    include_prefix = mode == "r3"
    best, ortho, phon = compare_profiles(
        p1, p2, min_threshold=min(threshold, 0.70), include_prefix=include_prefix
    )
    if best == 0.0:
        return False, 0.0, ortho, phon

    if best >= 0.999:
        return True, 1.0, ortho, phon

    min_len = min(
        len(p1.visual_clean or p1.primary_phonetic),
        len(p2.visual_clean or p2.primary_phonetic),
        len(p1.primary_phonetic) or 99,
        len(p2.primary_phonetic) or 99,
    )
    if min_len <= 3:
        return False, best, ortho, phon
    if min_len == 4:
        eff_thresh = max(threshold, 0.88 if mode == "r12" else 0.78)
    else:
        eff_thresh = threshold

    return best >= eff_thresh, best, ortho, phon
