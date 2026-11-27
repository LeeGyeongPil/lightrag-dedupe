"""Rule data for name normalization (kept as plain data so it is easy to review and extend).

Order matters: longer entries come first so that the longest match wins.
"""

from __future__ import annotations

# Corporate suffixes written with Latin letters. Matched as whole trailing words, case-insensitively,
# with an optional trailing dot ("Co.," "Ltd." ...). Compared after NFKC + casefold.
LATIN_SUFFIXES: tuple[str, ...] = (
    "incorporated",
    "corporation",
    "company",
    "limited",
    "corp",
    "inc",
    "ltd",
    "llc",
    "plc",
    "gmbh",
    "co",
)

# Korean corporate markers. NFKC turns the single character "㈜" into "(주)", so only these two appear.
# They may sit in front of the name ("(주)카카오") or behind it ("카카오(주)").
KO_CORPORATE: tuple[str, ...] = ("주식회사", "(주)")

# Korean particles that may trail a noun. Longest first. Removed only when the remaining
# stem is the key of another node (or alias), see normalize.py.
KO_PARTICLES: tuple[str, ...] = (
    "에서는",
    "으로는",
    "에게서",
    "에서",
    "으로",
    "에게",
    "와의",
    "과의",
    "의",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "도",
    "로",
    "에",
)

# A key shorter than this after a suffix is removed means the name was (almost) only a suffix.
MIN_KEY_LENGTH = 2

# Every rule code the tool can emit (the "evidence" vocabulary), for documentation and tests.
RULE_CODES: tuple[str, ...] = (
    "nfkc",
    "casefold",
    "suffix:<x>",
    "ko_particle:<x>",
    "punct_space",
    "alias",
    "guard:too_short",
)

# Rules that change how a name is written on the surface. A name with none of them is
# preferred as the merge target ("casefold" alone does not count).
SURFACE_RULE_PREFIXES: tuple[str, ...] = ("nfkc", "suffix:", "ko_particle:", "punct_space", "alias")
