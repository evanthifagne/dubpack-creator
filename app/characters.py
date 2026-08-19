"""Suggestion de noms de personnages à partir du texte transcrit."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable, Sequence

from .asr import Line

# Mots capitalisés qui ne sont jamais des noms de personnages.
_STOP = {
    # anglais
    "i", "the", "a", "an", "and", "but", "so", "no", "yes", "ok", "okay", "oh", "hey",
    "hi", "hello", "what", "who", "why", "how", "when", "where", "well", "you", "we",
    "he", "she", "it", "they", "this", "that", "there", "here", "my", "your", "his",
    "her", "our", "their", "not", "now", "just", "come", "go", "let", "look", "listen",
    "wait", "stop", "please", "thanks", "thank", "sorry", "god", "yeah", "nah", "sir",
    "maam", "mister", "mr", "mrs", "ms", "dr", "captain", "doctor", "if", "all", "one",
    "do", "did", "does", "is", "are", "was", "were", "be", "been", "have", "has", "had",
    "can", "could", "will", "would", "should", "get", "got", "know", "think", "want",
    # français
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "le", "la", "les",
    "un", "une", "des", "et", "mais", "ou", "donc", "car", "ne", "pas", "plus", "moi",
    "toi", "lui", "eux", "ce", "cet", "cette", "ces", "mon", "ma", "mes", "ton", "ta",
    "tes", "son", "sa", "ses", "notre", "votre", "leur", "quoi", "qui", "quand", "où",
    "comment", "pourquoi", "oui", "non", "bon", "bien", "alors", "voilà", "merci",
    "bonjour", "salut", "attends", "écoute", "regarde", "allez", "viens", "monsieur",
    "madame", "mademoiselle", "putain", "hein", "ben", "eh", "ah", "oh",
}

_WORD = re.compile(r"\b([A-ZÀ-Ý][a-zà-ÿ'’\-]{2,})\b")
# « Hé Marco », « Marco, écoute », « ... , Marco. »
# La casse compte: les flags insensibles sont limités à la liste d'interjections,
# sinon n'importe quel mot devant une virgule passerait pour un prénom.
_GREET = r"(?i:hey|h[éeè]|hi|salut|bonjour|yo|ok|okay|listen|[ée]coute|regarde|look|attends)"
_NAME = r"[A-ZÀ-Ý][a-zà-ÿ'’\-]{2,}"
_VOCATIVE = re.compile(
    rf"(?:^|[,.!?]\s*){_GREET}[\s,]+({_NAME})"
    rf"|({_NAME})\s*[,!?]"
    rf"|,\s*({_NAME})\s*[.!?]",
    re.U,
)
# Impératifs pronominaux (« Calme-toi ») : jamais des prénoms.
_PRONOMINAL = re.compile(r"-(?:toi|moi|lui|nous|vous|les?|la|en|y)$", re.I)
# Élisions du français (« C'était », « J'ai », « L'homme ») : artefacts de capitalisation.
_ELISION = re.compile(r"^(?:c|j|l|d|n|m|t|s|qu)['’]", re.I)


def _candidates(text: str) -> list[tuple[str, bool]]:
    """Noms propres plausibles, avec un drapeau « pas en tête de phrase ».

    Un mot capitalisé au milieu d'une phrase est un excellent indice de nom
    propre. En tête de phrase l'indice ne vaut rien: seule une apostrophe
    (« Marco, viens ») permet alors de trancher, ce que gère `_VOCATIVE`.
    """
    out: list[tuple[str, bool]] = []
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for match in _WORD.finditer(sentence):
            word = match.group(1)
            if word.lower() in _STOP or _PRONOMINAL.search(word) or _ELISION.match(word):
                continue
            out.append((word, match.start() > 0))
    return out


def suggest_names(lines: Sequence[Line], limit: int = 8) -> list[dict]:
    """Noms candidats, avec qui les prononce (pour deviner à qui ils s'adressent)."""
    counts: Counter[str] = Counter()
    mid_sentence: Counter[str] = Counter()
    said_by: dict[str, Counter] = defaultdict(Counter)
    vocatives: Counter[str] = Counter()

    for line in lines:
        text = line.text or ""
        for name, is_mid in _candidates(text):
            counts[name] += 1
            if is_mid:
                mid_sentence[name] += 1
            if line.speaker:
                said_by[name][line.speaker] += 1
        for match in _VOCATIVE.finditer(text):
            name = next((g for g in match.groups() if g), None)
            if not name or name.lower() in _STOP:
                continue
            if _PRONOMINAL.search(name) or _ELISION.match(name):
                continue
            pretty = name[:1].upper() + name[1:]
            vocatives[pretty] += 1
            counts[pretty] += 1
            if line.speaker:
                said_by[pretty][line.speaker] += 1

    ranked = []
    for name, count in counts.most_common(limit * 4):
        if len(name) < 3:
            continue
        vocative = vocatives.get(name, 0)
        # Sans apostrophe ni occurrence en milieu de phrase, c'est probablement
        # juste un mot en début de phrase.
        if vocative == 0 and mid_sentence.get(name, 0) == 0:
            continue
        ranked.append({
            "name": name,
            "count": count,
            "vocative": vocative,
            "said_by": dict(said_by.get(name, {})),
        })
    # Un nom employé en apostrophe est un bien meilleur candidat.
    ranked.sort(key=lambda item: (item["vocative"] * 3 + item["count"]), reverse=True)
    return ranked[:limit]


def auto_assign(lines: Sequence[Line], speakers: Sequence[str],
                suggestions: Sequence[dict] | None = None) -> dict[str, str]:
    """Propose un nom par voix détectée, uniquement quand l'indice est net.

    Règle: un nom prononcé en apostrophe par une voix désigne presque toujours
    *l'autre* voix. On ne renomme donc que les dialogues à deux personnages où
    un nom ressort clairement, pour éviter les faux positifs.
    """
    suggestions = list(suggestions or suggest_names(lines))
    mapping: dict[str, str] = {}
    if len(speakers) != 2 or not suggestions:
        return mapping

    strong = [s for s in suggestions if s["vocative"] >= 1 and s["count"] >= 1]
    for item in strong:
        said_by = item["said_by"]
        if not said_by:
            continue
        speaker = max(said_by, key=said_by.get)
        other = next((s for s in speakers if s != speaker), None)
        if other and other not in mapping and item["name"] not in mapping.values():
            mapping[other] = item["name"]
    return mapping
