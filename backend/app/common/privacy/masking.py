"""Mask PII and confidential names with Microsoft Presidio before text reaches a model, and restore them after.

Use one Masker per model call. Within it the same value always gets the same placeholder, so the model can
still tell people apart, and unmask() puts the real values back into the model's answer.
"""

import re
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache
from typing import NamedTuple

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider

from app.common.config import config_version
from app.common.registry import load_registry, register_document

PLACEHOLDER = re.compile(r"<[A-Z]+(?:_[A-Z]+)*_\d+>")
NER = "SpacyRecognizer"


class MaskedText(str):
    """Text returned by Masker.mask(); the only kind a model client should accept."""


class PiiLeakError(RuntimeError):
    """A known private value is still present after masking. The value itself is never included."""


class UnknownPlaceholderError(ValueError):
    """The model returned a placeholder that was never issued."""


class _Engine(NamedTuple):
    analyzer: AnalyzerEngine
    labels: dict[str, str]  # Presidio entity -> placeholder label
    app_terms: dict[str, str]  # how an app is written (casefolded) -> app name
    keep: frozenset[str]  # ordinary words NER must not mask


def _engine() -> _Engine:
    return _build_engine(config_version())


@lru_cache(maxsize=1)
def _build_engine(version: int) -> _Engine:
    """Presidio analyzer with our recognisers, rebuilt after an admin change (the config version moves)."""
    config = load_registry("common/pii.yaml")
    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": config["spacy_model"]}],
    }).create_engine()
    engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])

    for label, regexes in config["patterns"].items():
        patterns = [Pattern(label, rx, 0.9) for rx in regexes]
        engine.registry.add_recognizer(PatternRecognizer(supported_entity=label, patterns=patterns, global_regex_flags=re.M))

    apps = load_registry("common/apps.yaml")
    app_terms = {name.casefold(): app for app, entry in apps.items() for name in [app, *entry["names"]]}
    keep = frozenset(w.casefold() for w in [*config["keep"], *(k for entry in apps.values() for k in entry["keywords"])])
    terms = {label: list(values) for label, values in config["terms"].items()}
    terms["APP"] = [*terms.get("APP", []), *app_terms]
    for label, values in terms.items():
        engine.registry.add_recognizer(PatternRecognizer(supported_entity=label, deny_list=values, name=f"{label}_terms"))

    labels = {**config["entities"], **{label: label for label in [*config["patterns"], *terms]}}
    return _Engine(engine, labels, app_terms, keep)


def _trim_ner(results: list[RecognizerResult], text: str, keep: frozenset[str]) -> list[RecognizerResult]:
    """spaCy findings: cut at a line break (a name never spans lines) and drop ordinary support words."""
    trimmed = []
    for r in results:
        if r.recognition_metadata.get(RecognizerResult.RECOGNIZER_NAME_KEY) == NER:
            if (newline := text.find("\n", r.start, r.end)) != -1:
                r.end = newline
            word = text[r.start:r.end].strip().casefold()
            if not word or word in keep or word.removesuffix("s") in keep:
                continue
        trimmed.append(r)
    return trimmed


def _without_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Keep the strongest, then longest, finding wherever findings overlap."""
    kept: list[RecognizerResult] = []
    for r in sorted(results, key=lambda r: (-r.score, r.start - r.end)):
        if all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: r.start)


class Masker:
    def __init__(self, known_names: Iterable[str | None] = (), known_emails: Iterable[str | None] = ()):
        """known_names / known_emails come from the ticket's own fields and are always masked, even where NER misses them."""
        self._names = [n.strip() for n in known_names if n and n.strip()]
        self._name_parts = {p.casefold(): n.casefold() for n in self._names for p in n.split() if len(p) >= 3}
        self._emails = [e.strip() for e in known_emails if e and e.strip()]
        self._issued: dict[tuple[str, str], str] = {}  # (label, normalised value) -> placeholder
        self._values: dict[str, str] = {}  # placeholder -> original value
        self.counts: Counter = Counter()  # findings per label; safe to log

    def _key(self, label: str, value: str, app_terms: dict[str, str]) -> str:
        v = " ".join(value.casefold().split())
        if label == "PERSON":
            return self._name_parts.get(v, v)  # "Priya" and "Priya Raman" are the same reporter
        if label == "APP":
            return app_terms.get(v, v).casefold()  # "Payroll Pro" and "PayrollPro" are the same app
        return v

    def _placeholder(self, label: str, value: str, app_terms: dict[str, str]) -> str:
        key = (label, self._key(label, value, app_terms))
        if key not in self._issued:
            self._issued[key] = f"<{label}_{sum(k[0] == label for k in self._issued) + 1}>"
            self._values[self._issued[key]] = value
        self.counts[label] += 1
        return self._issued[key]

    def mask(self, text: str | None) -> MaskedText:
        if not text:
            return MaskedText("")
        engine = _engine()
        # Presidio refuses an empty deny list, so a ticket with no reporter name gets no ad-hoc recognizer.
        known = (
            [PatternRecognizer(supported_entity="PERSON", deny_list=[*self._names, *self._name_parts], name="known_people")]
            if self._names
            else None
        )
        results = engine.analyzer.analyze(
            text,
            language="en",
            entities=list(engine.labels),
            score_threshold=load_registry("common/pii.yaml")["score_threshold"],
            ad_hoc_recognizers=known,
        )

        parts, cursor = [], 0
        for r in _without_overlaps(_trim_ner(results, text, engine.keep)):
            parts += [text[cursor:r.start], self._placeholder(engine.labels[r.entity_type], text[r.start:r.end], engine.app_terms)]
            cursor = r.end
        masked = "".join([*parts, text[cursor:]])
        self._check_leaks(masked, engine.app_terms)
        return MaskedText(masked)

    def _check_leaks(self, masked: str, app_terms: dict[str, str]) -> None:
        for kind, values in [("name", [*self._names, *self._name_parts]), ("email", self._emails), ("application", app_terms)]:
            if any(re.search(rf"(?<!\w){re.escape(v)}(?!\w)", masked, re.I) for v in values):
                raise PiiLeakError(f"A known {kind} is still present after masking")

    def unmask(self, text: str) -> str:
        unknown = sorted({p for p in PLACEHOLDER.findall(text) if p not in self._values})
        if unknown:
            raise UnknownPlaceholderError(f"Placeholders never issued: {', '.join(unknown)}")
        return PLACEHOLDER.sub(lambda m: self._values[m.group(0)], text)


def _check_engine() -> None:
    Masker().mask("check")  # builds the Presidio engine from the current documents


register_document("pii", "common/pii.yaml", _check_engine)
register_document("apps", "common/apps.yaml", _check_engine)
