"""The working corpus of Yaounde urban statements.

PROVENANCE -- READ THIS BEFORE SUBMITTING
=========================================
The brief requires 10-15 statements that your group **heard and manually
transcribed** in Yaounde.  The statements below were *authored* to exercise the
analyzer during development.  They are written in the registers the brief names
(taxi, network, electricity, market, rain, fuel, roadside, bendskin, security,
ICTU) but they are **not field data**, and every one of them is flagged
``provenance="CONSTRUCTED"``.

Replace them with your real transcriptions and set ``provenance="FIELD"``,
filling in ``where``, ``when`` and ``speaker``.  Every tool in this project --
the token tables, the frequency counts, the grammar tests and the generated
report -- reads from this list, so swapping the data is the only change needed.
While any CONSTRUCTED statement remains, the report prints a provenance
warning on its first page.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    """One member of the submitting group."""

    name: str
    matricule: str


#: The group, as printed on the title page of the generated report.
GROUP: list[Member] = [
    Member("Fru Chi Ehud Neba", "ICTU20241812"),
    Member("Daniel Victor", "ICTU20241332"),
    Member("Tchelibo Ayolo Sherrylle Claire", "ICTU20241316"),
]

#: Course and institution, also printed on the title page.
COURSE = "CS4110 --- Compiler Construction"
INSTITUTION = "Faculty of Information and Communication Technologies"


def duplicate_matricules() -> list[str]:
    """Matricules shared by more than one member.

    Two members currently carry the same number, which is almost certainly a
    transcription slip.  Reporting it is cheap; a wrong matricule on a
    submitted cover page is not.
    """
    seen: dict[str, int] = {}
    for member in GROUP:
        seen[member.matricule] = seen.get(member.matricule, 0) + 1
    return sorted(m for m, count in seen.items() if count > 1)


@dataclass(frozen=True)
class Statement:
    """One transcribed utterance plus its field metadata."""

    sid: str
    text: str
    topic: str
    where: str
    when: str
    speaker: str
    gloss: str
    provenance: str = "CONSTRUCTED"

    @property
    def is_field_data(self) -> bool:
        return self.provenance.upper() == "FIELD"


CORPUS: list[Statement] = [
    Statement(
        sid="S01",
        topic="Taxi and commuting",
        text="Chef, drop me for Carrefour Obili.",
        where="Melen, taxi rank",
        when="—",
        speaker="passenger to driver",
        gloss="Boss, drop me at Obili junction.",
    ),
    Statement(
        sid="S02",
        topic="Taxi and commuting",
        text="Patron, deux cents na for Mvan?",
        where="Nsimeyong, roadside",
        when="—",
        speaker="passenger",
        gloss="Boss, is it two hundred francs to Mvan?",
    ),
    Statement(
        sid="S03",
        topic="Taxi bargaining",
        text="Hmmm, chef, this road don cut, pay cinq cents.",
        where="Mvog-Ada",
        when="—",
        speaker="taxi driver",
        gloss="The road is bad, pay five hundred.",
    ),
    Statement(
        sid="S04",
        topic="Poor internet connectivity",
        text="Ekiee, this MTN reseau dey small small today.",
        where="Ngoa-Ekelle, student hostel",
        when="—",
        speaker="student",
        gloss="This MTN network keeps cutting in and out today.",
    ),
    Statement(
        sid="S05",
        topic="Poor internet connectivity",
        text="Je wanda, my forfait don finish!",
        where="Obili",
        when="—",
        speaker="student",
        gloss="Unbelievable, my data bundle is finished.",
    ),
    Statement(
        sid="S06",
        topic="Limited electricity supply",
        text="Garrr, ENEO don cut courant since ce matin.",
        where="Biyem-Assi",
        when="—",
        speaker="shop owner",
        gloss="ENEO has cut the power since this morning.",
    ),
    Statement(
        sid="S07",
        topic="Limited electricity supply",
        text="Courant no dey, we dey wait la nuit.",
        where="Essos",
        when="—",
        speaker="neighbour",
        gloss="There is no power, we are waiting for the night.",
    ),
    Statement(
        sid="S08",
        topic="Market bargaining",
        text="Mami, reduce this tomate small, na trop cher.",
        where="Mokolo market",
        when="—",
        speaker="buyer",
        gloss="Madam, reduce the tomatoes a little, it is too expensive.",
    ),
    Statement(
        sid="S09",
        topic="Market bargaining",
        text="Mbom, deux mille na last price o.",
        where="Mokolo market",
        when="—",
        speaker="seller",
        gloss="My friend, two thousand is the last price.",
    ),
    Statement(
        sid="S10",
        topic="Rainy season struggles",
        text="Weh, rain don beat we for Damas.",
        where="Damas",
        when="—",
        speaker="pedestrian",
        gloss="We got soaked by the rain at Damas.",
    ),
    Statement(
        sid="S11",
        topic="Rainy season struggles",
        text="This boue dey full the chemin, taxi no dey come.",
        where="Nsimeyong",
        when="—",
        speaker="resident",
        gloss="Mud fills the path, no taxi comes.",
    ),
    Statement(
        sid="S12",
        topic="Fuel scarcity",
        text="Hmmm, queue for station dey long trop.",
        where="Etoudi, filling station",
        when="—",
        speaker="motorist",
        gloss="The queue at the station is far too long.",
    ),
    Statement(
        sid="S13",
        topic="Bendskin communication",
        text="Bendskin man, carry me go Mokolo sharp sharp.",
        where="Mvog-Ada junction",
        when="—",
        speaker="passenger to rider",
        gloss="Rider, take me to Mokolo immediately.",
    ),
    Statement(
        sid="S14",
        topic="Security checkpoint",
        text="Chef, bring your carte nationale!",
        where="Bastos checkpoint",
        when="—",
        speaker="police officer",
        gloss="Sir, produce your national identity card.",
    ),
    Statement(
        sid="S15",
        topic="Life at the ICT University",
        text="Mola, the prof don drop resultats for lundi.",
        where="ICT University, Messassi",
        when="—",
        speaker="student",
        gloss="Friend, the lecturer has released the results for Monday.",
    ),
]


#: Deliberately ill-formed inputs used as negative tests.  These are *not*
#: field data and are never counted in the corpus statistics; they exist to
#: prove the parser rejects for a stated reason.
NEGATIVE_TESTS: list[tuple[str, str, str]] = [
    ("N01", "drop", "verb with no object and no terminator"),
    ("N02", "Chef chef chef.", "three vocatives, no clause"),
    ("N03", "for Mokolo drop me.", "prepositional phrase before the verb"),
    ("N04", "Mami reduce tomate", "missing sentence terminator"),
    ("N05", "xyzzy plonk.", "words outside the lexical specification"),
    ("N06", ".", "terminator with no clause"),
]


def field_data_ratio() -> tuple[int, int]:
    """Return ``(field statements, total statements)``."""
    field = sum(1 for s in CORPUS if s.is_field_data)
    return field, len(CORPUS)


def provenance_warning() -> str | None:
    """Return a warning if the corpus is not yet real field data."""
    field, total = field_data_ratio()
    if field == total:
        return None
    return (
        f"PROVENANCE WARNING: {total - field} of {total} statements are marked "
        f"CONSTRUCTED, not FIELD. The assignment requires statements your group "
        f"recorded and transcribed in Yaounde. Replace them in "
        f"src/yca/corpus.py and set provenance='FIELD' before submitting."
    )


def topics() -> list[str]:
    seen: list[str] = []
    for s in CORPUS:
        if s.topic not in seen:
            seen.append(s.topic)
    return seen
