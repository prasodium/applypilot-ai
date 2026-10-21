"""Question classification. Sensitive and legal categories are checked FIRST so they can never be mistaken for ordinary fields."""
from __future__ import annotations

import re

from app.core.enums import LEGAL_TYPES, SENSITIVE_TYPES
from app.core.enums import QuestionType as Q
from app.core.skills import find_skills

_R = re.compile
_RULES: list[tuple[Q, re.Pattern[str]]] = [
    # --- legal (checked first): certifications, consents, agreements
    (Q.LEGAL_CERTIFICATION, _R(r"\b(i|we)\s+(hereby\s+)?(certify|agree|acknowledge|declare|consent|confirm|authori[sz]e|understand|attest|accept)\b|"
                               r"terms\s*(and|&)\s*conditions|privacy\s+(policy|notice|statement)|(information|answers?|statements?).{0,30}(true|accurate|correct|complete)|"
                               r"electronic\s+signature|e-?sign|data\s+processing\s+consent|at-?will|background\s+(check|screening)\s+consent", re.I)),
    # --- sensitive: never answered without explicit user-approved information
    (Q.CRIMINAL_HISTORY, _R(r"convict|criminal|felon|misdemeanou?r|arrest|offen[sc]e", re.I)),
    (Q.DISABILITY, _R(r"disabilit|handicap|accommodation|medical\s+condition|chronic|health\s+condition", re.I)),
    (Q.SPONSORSHIP, _R(r"sponsor|require\s+(a\s+)?(work\s+)?visa|(need|require).{0,30}(work\s+)?(permit|visa)", re.I)),
    (Q.WORK_AUTHORIZATION, _R(r"authori[sz]ed\s+to\s+work|work\s+authori[sz]ation|legally\s+(authori[sz]ed|eligible|permitted|allowed)|eligib\w+\s+to\s+work|"
                              r"right\s+to\s+work|work\s+permit|work\s+visa|citizen|immigration|residen(t|cy)\s+status|permanent\s+resident", re.I)),
    (Q.DEMOGRAPHIC, _R(r"\bgender\b|\bsex\b|\brace\b|racial|ethnic|hispanic|latino|veteran|military|sexual\s+orientation|pronoun|marital|religio|"
                       r"\bage\b|date\s+of\s+birth|\bdob\b|birth\s*date|nationality|national\s+origin|caste|transgender", re.I)),
    # --- ordinary profile fields
    (Q.COVER_LETTER, _R(r"cover\s+letter", re.I)),
    (Q.RESUME_UPLOAD, _R(r"\b(resume|résumé|cv|curriculum\s+vitae)\b", re.I)),
    (Q.FIRST_NAME, _R(r"first\s+name|given\s+name|forename", re.I)),
    (Q.LAST_NAME, _R(r"last\s+name|surname|family\s+name", re.I)),
    (Q.FULL_NAME, _R(r"^\s*(your\s+)?(full\s+|legal\s+)?name\s*[*:]?\s*$|full\s+name|legal\s+name", re.I)),
    (Q.EMAIL, _R(r"e-?mail", re.I)),
    (Q.PHONE, _R(r"phone|mobile|telephone|contact\s+number|cell", re.I)),
    (Q.LINKEDIN, _R(r"linkedin", re.I)),
    (Q.GITHUB, _R(r"github|gitlab", re.I)),
    (Q.PORTFOLIO, _R(r"portfolio|personal\s+(web)?site|website|your\s+url", re.I)),
    (Q.RELOCATION, _R(r"relocat", re.I)),
    (Q.SALARY, _R(r"salary|compensation|pay\s+expectation|expected\s+(ctc|pay)|desired\s+pay|rate\s+expectation", re.I)),
    (Q.START_DATE, _R(r"start\s+date|available\s+to\s+start|notice\s+period|when\s+can\s+you\s+(start|join)|earliest\s+(start|availability)|availability", re.I)),
    (Q.EXPERIENCE_YEARS, _R(r"years?\s+of\s+(relevant\s+|work\s+|professional\s+)?experience|how\s+many\s+years|total\s+experience", re.I)),
    (Q.EDUCATION, _R(r"degree|university|college|school|education|gpa|cgpa|graduat|major|field\s+of\s+study", re.I)),
    (Q.LOCATION, _R(r"\bcity\b|current\s+location|where\s+(do\s+you\s+)?(live|are\s+you\s+based)|\bcountry\b|\blocation\b|home\s+address|\baddress\b", re.I)),
    (Q.REFERRAL, _R(r"how\s+did\s+you\s+(hear|find)|referr|source\s+of\s+application", re.I)),
    # --- free text
    (Q.MOTIVATION, _R(r"why\s+(do\s+you\s+want|are\s+you\s+interested|would\s+you\s+like|us\b|this\s+(role|company|position)|should\s+we)|what\s+(excites|interests|motivates|attracts)|"
                      r"interest\s+in\s+(this|our|the)|why\s+.{0,25}(join|work\s+(for|at|with))", re.I)),
    (Q.BEHAVIORAL, _R(r"tell\s+us\s+about\s+a\s+time|describe\s+a\s+(time|situation|challenge)|give\s+(us\s+)?an?\s+example|conflict|leadership|"
                      r"your\s+(greatest\s+)?(strength|weakness)|proud\s+of|biggest\s+(challenge|achievement)|teamwork", re.I)),
    (Q.SKILLS, _R(r"\bskills?\b|technolog|tech\s+stack|proficien|tools", re.I)),
    (Q.TECHNICAL, _R(r"experience\s+(with|in|using)|how\s+would\s+you|explain|describe\s+your\s+(approach|experience)|project|build|design|implement|"
                     r"\bapi\b|database|architecture", re.I)),
]
_CHECKBOXISH = {"checkbox", "radio"}
LIMIT_WORDS = _R(r"(?:max(?:imum)?|up\s+to|limit(?:ed)?(?:\s+to)?|under|within|no\s+more\s+than)?\s*(\d{1,5})\s*[- ]?words?", re.I)
LIMIT_CHARS = _R(r"(?:max(?:imum)?|up\s+to|limit(?:ed)?(?:\s+to)?|under|within|no\s+more\s+than)?\s*(\d{1,6})\s*[- ]?(?:characters?|chars)\b", re.I)


def classify(label: str, field_type: str = "text") -> Q:
    text = re.sub(r"\s+", " ", label or "").strip()
    if field_type == "file":
        return Q.COVER_LETTER if re.search(r"cover", text, re.I) else Q.RESUME_UPLOAD
    for qtype, rx in _RULES:
        if qtype in {Q.RESUME_UPLOAD}:
            continue  # only meaningful for file inputs
        if rx.search(text):
            if qtype in LEGAL_TYPES and field_type not in _CHECKBOXISH and not re.search(r"certify|consent|agree|acknowledge|declare|attest", text, re.I):
                continue  # a plain text box that merely mentions "accurate" is not a legal attestation
            if qtype == Q.TECHNICAL and re.match(r"^\s*(do|does|have|has|are|can)\b", text, re.I) and find_skills(text):
                return Q.SKILLS  # a yes/no question about one named technology is a skills question, not an essay
            return qtype
    return Q.OTHER


def is_sensitive(q: Q) -> bool:
    return q in SENSITIVE_TYPES


def is_legal(q: Q) -> bool:
    return q in LEGAL_TYPES


def extract_limits(label: str, max_length: int | None) -> tuple[int | None, int | None]:
    """(word_limit, character_limit) from the form's own text and its maxlength attribute."""
    words = LIMIT_WORDS.search(label or "")
    chars = LIMIT_CHARS.search(label or "")
    char_limit = min([x for x in (int(chars.group(1)) if chars else None, max_length) if x] or [0]) or None
    return (int(words.group(1)) if words else None), char_limit
