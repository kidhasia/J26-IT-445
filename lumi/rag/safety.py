"""A conservative guard that refuses questions asking about a person's own health, or asking LUMI to diagnose something.

It runs BEFORE any search, so a retrieved passage can never be shown as if it answered a diagnosis request. It is a small set
of word and phrase rules, not a medical safety classifier: it will miss some phrasings and it will refuse some harmless ones.
When in doubt it refuses. Questions that merely mention a disease while asking about the project or the model ("What was the
melanoma recall?", "Does LUMI diagnose melanoma?") are not blocked, because nothing in them points at a particular case.
"""

import re

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")

# Phrases that mean "about me / my child / my result" or ask for a diagnosis or treatment.
PERSONAL_PHRASES = (
    "do i have", "does my", "is my", "should i", "am i", "can i take", "what should i", "my child", "my son", "my daughter",
    "my baby", "my mole", "my skin", "my lesion", "my rash", "my result", "my results", "my blood", "my test", "my photo",
    "diagnose me", "diagnose him", "diagnose her", "diagnose them", "diagnose it", "diagnose this", "diagnose that", "diagnose my",
    "can you diagnose", "could you diagnose", "will you diagnose", "please diagnose", "help me diagnose",
    "treat me", "is it cancer", "is this cancer", "is it melanoma", "is this melanoma", "is this safe",
    "what treatment", "which treatment", "how to treat", "how do i treat", "what medicine", "what medication", "what dose",
    "need to see a doctor", "see a doctor", "what is wrong with", "what s wrong with",
)
PERSONAL_WORDS = frozenset("prescribe prescription dosage".split())

# "this photo", "my mole", "that rash": a pointer to one particular case.
CASE_POINTERS = frozenset("this that these those my his her their our".split())
CASE_NOUNS = frozenset(
    "photo photos image images picture pictures lesion lesions mole moles spot spots rash scan scans sample patient patients child "
    "person man woman boy girl baby".split()
)
CONDITIONS = frozenset(
    "cancer cancerous melanoma carcinoma malignant benign tumor tumour disease diseases infection infected condition illness disorder "
    "psoriasis eczema acne dermatitis keratosis nevus naevus lupus diabetes anaemia anemia".split()
)
# Words that turn a pointer plus a noun into a request to judge the case.
CUES = frozenset(
    "show shows showing shown indicate indicates suggest suggests identify identifies detect detects diagnose diagnosed diagnosing "
    "diagnosis determine classify classified assess tell check decide look looks sick ill unwell healthy wrong".split()
) | CONDITIONS
PERSONS = frozenset("patient child person man woman boy girl baby kid infant toddler someone somebody he she".split())
HAS_WORDS = frozenset("has have having got suffering suffer suffers".split())
SYMPTOMS = frozenset("itchy itching itch pain painful bleeding bleeds fever rash swelling swollen lump cough headache nausea vomiting dizzy blister blisters".split())
SYMPTOM_CONTEXT = frozenset("have has having with keeps suffering got feel feeling experiencing developed noticed".split())
DIAGNOSIS_WORDS = frozenset("diagnosis diagnose cause causes condition disease illness fits fit".split())


def is_personal_medical_question(question: str) -> bool:
    """True if the question looks like a personal-health question or a request to diagnose, identify a disease, or decide
    whether someone has a condition. See the module note: conservative, and not a complete safety classifier."""
    words = _TOKEN.findall(question.lower())
    text = " " + " ".join(words) + " "
    if any(f" {phrase} " in text for phrase in PERSONAL_PHRASES) or set(words) & PERSONAL_WORDS:
        return True
    for i, word in enumerate(words):
        if word in CASE_POINTERS and CASE_NOUNS & set(words[i + 1 : i + 3]) and CUES & set(words):
            return True  # "Does this picture show ...", "Check if this mole is malignant"
        if word in PERSONS and HAS_WORDS & set(words[i + 1 : i + 3]):
            return True  # "whether the patient has ...", "is he suffering from ..."
    if SYMPTOMS & set(words) and SYMPTOM_CONTEXT & set(words):
        return True  # "I have an itchy patch that keeps bleeding"
    if {"symptom", "symptoms"} & set(words) and DIAGNOSIS_WORDS & set(words):
        return True  # "What diagnosis fits these symptoms"
    return False
