"""Mask personal information with Microsoft Presidio, and restore it afterwards.

Only personal data is masked (names, contacts, personal IDs). Application names, error codes and record IDs stay
readable. Within one Masker the same value always gets the same placeholder, and unmask() puts the real values back.
"""

import re
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache
from typing import NamedTuple

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider

from app.core.config import config_version
from app.core.registry import load_registry, register_document

PLACEHOLDER = re.compile(r"<[A-Z]+(?:_[A-Z]+)*_\d+>")
NER = "SpacyRecognizer"
KNOWN_PEOPLE = "known_people"


class MaskedText(str):
    """Text returned by Masker.mask(); the only kind a model client should accept."""


class PiiLeakError(RuntimeError):
    """A known name or email is still present after masking. The value itself is never included."""


class UnknownPlaceholderError(ValueError):
    """The model returned a placeholder that was never issued."""


class _Engine(NamedTuple):
    analyzer: AnalyzerEngine
    labels: dict[str, str]  # Presidio entity -> placeholder label
    protect: tuple[re.Pattern, ...]  # spans that are never masked
    keep: frozenset[str]  # ordinary words NER must not mask


def _engine() -> _Engine:
    return _build_engine(config_version())


@lru_cache(maxsize=1)
def _build_engine(version: int) -> _Engine:
    """Presidio analyzer with our recognisers, rebuilt after an admin change (the config version moves)."""
    config = load_registry("pii.yaml")
    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": config["spacy_model"]}],
    }).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    for label, regexes in config["patterns"].items():
        patterns = [Pattern(label, rx, 0.9) for rx in regexes]
        analyzer.registry.add_recognizer(PatternRecognizer(supported_entity=label, patterns=patterns, global_regex_flags=re.M))

    apps = load_registry("apps.yaml")
    app_names = sorted({n for app, entry in apps.items() for n in [app, *entry["names"]]}, key=len, reverse=True)
    protect = (*(re.compile(p) for p in config["protect"]), re.compile(rf"\b(?:{'|'.join(map(re.escape, app_names))})\b", re.I))
    keep = frozenset(w.casefold() for w in [*config["keep"], *(k for entry in apps.values() for k in entry["keywords"])])
    labels = {**config["entities"], **{label: label for label in config["patterns"]}}
    return _Engine(analyzer, labels, protect, keep)


def _filter(results: list[RecognizerResult], text: str, engine: _Engine) -> list[RecognizerResult]:
    """Drop findings on protected spans; cut NER names at a line break and drop ordinary words NER mistook for names."""
    protected = [m.span() for p in engine.protect for m in p.finditer(text)]
    kept = []
    for r in results:
        source = r.recognition_metadata.get(RecognizerResult.RECOGNIZER_NAME_KEY)
        if source != KNOWN_PEOPLE and any(r.start < end and start < r.end for start, end in protected):
            continue
        if source == NER:
            if (newline := text.find("\n", r.start, r.end)) != -1:
                r.end = newline
            word = text[r.start:r.end].strip().casefold()
            if not word or word in engine.keep or word.removesuffix("s") in engine.keep:
                continue
        kept.append(r)
    return kept


def _without_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Keep the strongest, then longest, finding wherever findings overlap."""
    kept: list[RecognizerResult] = []
    for r in sorted(results, key=lambda r: (-r.score, r.start - r.end)):
        if all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: r.start)


class Masker:
    def __init__(
        self, known_names: Iterable[str | None] = (), known_emails: Iterable[str | None] = (), beside: Iterable[str | None] = ()
    ):
        """known_names / known_emails come from the ticket's own fields and are always masked, even where NER misses them.
        beside are texts already masked that the result is read next to; numbering starts after their placeholders."""
        system = {a.casefold() for a in load_registry("pii.yaml")["system_accounts"]}
        self._names = sorted({
            n.strip() for n in known_names
            if n and n.strip() and n.strip().casefold() not in system and not PLACEHOLDER.fullmatch(n.strip())
        })
        parts = Counter(p.casefold() for n in self._names for p in set(n.split()) if len(p) >= 3)
        self._parts = sorted(parts)  # every first and last name is masked on its own too
        # ...and linked to the full name when no other known person shares it
        self._name_parts = {p.casefold(): n.casefold() for n in self._names for p in n.split() if parts.get(p.casefold()) == 1}
        self._emails = [
            e.strip() for e in known_emails
            if e and e.strip() and not PLACEHOLDER.fullmatch(e.strip())
        ]
        self._issued: dict[tuple[str, str], str] = {}  # (label, normalised value) -> placeholder
        self._taken: Counter = Counter()  # label -> highest number in the texts beside
        for placeholder in PLACEHOLDER.findall(" ".join(t for t in beside if t)):
            label, _, number = placeholder[1:-1].rpartition("_")
            self._taken[label] = max(self._taken[label], int(number))
        self._values: dict[str, str] = {}  # placeholder -> original value
        self.counts: Counter = Counter()  # findings per label; safe to log

    def _placeholder(self, label: str, value: str) -> str:
        v = " ".join(value.casefold().split())
        key = (label, self._name_parts.get(v, v) if label == "PERSON" else v)  # "Priya" and "Priya Raman" are one person
        if key not in self._issued:
            self._issued[key] = f"<{label}_{self._taken[label] + sum(k[0] == label for k in self._issued) + 1}>"
            self._values[self._issued[key]] = value
        self.counts[label] += 1
        return self._issued[key]

    def mask(self, text: str | None) -> MaskedText:
        if not text or not text.strip():
            return MaskedText(text or "")
        engine = _engine()
        known = [  # a lone first or last name scores below NER, so "Ravi Kumar" is not split into two known people
            PatternRecognizer(supported_entity="PERSON", deny_list=self._names, name=KNOWN_PEOPLE),
            PatternRecognizer(supported_entity="PERSON", deny_list=self._parts, deny_list_score=0.8, name=KNOWN_PEOPLE),
        ] if self._names else None
        results = engine.analyzer.analyze(
            text,
            language="en",
            entities=list(engine.labels),
            score_threshold=load_registry("pii.yaml")["score_threshold"],
            ad_hoc_recognizers=known,
        )

        parts, cursor = [], 0
        for r in _without_overlaps(_filter(results, text, engine)):
            parts += [text[cursor:r.start], self._placeholder(engine.labels[r.entity_type], text[r.start:r.end])]
            cursor = r.end
        masked = "".join([*parts, text[cursor:]])
        self._check_leaks(masked)
        return MaskedText(masked)

    def _check_leaks(self, masked: str) -> None:
        for kind, values in [("name", [*self._names, *self._parts]), ("email", self._emails)]:
            if any(re.search(rf"(?<!\w){re.escape(v)}(?!\w)", masked, re.I) for v in values):
                raise PiiLeakError(f"A known {kind} is still present after masking")

    def unmask(self, text: str) -> str:
        unknown = sorted({p for p in PLACEHOLDER.findall(text) if p not in self._values})
        if unknown:
            raise UnknownPlaceholderError(f"Placeholders never issued: {', '.join(unknown)}")
        return PLACEHOLDER.sub(lambda m: self._values[m.group(0)], text)


def _check_engine() -> None:
    Masker().mask("check")  # builds the Presidio engine from the current documents


register_document("pii", "pii.yaml", _check_engine)
register_document("apps", "apps.yaml", _check_engine)
