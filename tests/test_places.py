"""Place names must be found even when misspelled, without spaces, abbreviated or in Tamil."""
import pytest

from modules.data_loader import load_all
from modules.parser import parse_disruption
from modules.places import best_road, normalize


@pytest.mark.parametrize("text, road_id", [
    ("accident near avinasi rd", "R1"),          # missing letter + short form
    ("Avinashiroad fully blocked", "R1"),        # no space
    ("AVANASHI ROAD", "R1"),                     # alias + caps
    ("avinaashi road la jam", "R1"),             # extra letter
    ("near KMCH hospital", "R1"),                # landmark -> its road
    ("PSG Tech signal", "R1"),
    ("அவிநாசி சாலையில் விபத்து", "R1"),          # Tamil with suffix
    ("R.S.Puram la traffic", "R6"),              # dotted initials
    ("r s puram", "R6"),                         # spaced initials
    ("100ft road jam", "R7"),                    # digits stuck to unit
    ("gandhi puram bus stand", "R7"),            # extra space
    ("gaandhipuram", "R7"),                      # double letter typo
    ("pelamedu signal", "R9"),
    ("hope collage", "R9"),
    ("townhall", "R10"),
    ("ukadam bus stand", "R10"),
    ("saravanapatti flood", "R4"),
    ("singanalur", "R2"),
    ("trichy rd", "R2"),
    ("Mettupalayam road la mazhai", "R3"),
    ("thudialur", "R3"),
    ("echanari temple", "R5"),
])
def test_place_variants_resolve_to_the_right_road(text, road_id):
    best, _ = best_road(text)
    assert best is not None, text
    assert best["road_id"] == road_id, (text, best)


@pytest.mark.parametrize("text", ["Something happened somewhere", "heavy traffic", "murugan is late",
                                  "road", "vandi puncture"])
def test_no_place_means_no_guess(text):
    best, _ = best_road(text)
    assert best is None, (text, best)


def test_normalize_joins_initials_and_expands_short_forms():
    assert normalize("R.S. Puram rd") == "rs puram road"
    assert normalize("100ft") == "100 feet"


@pytest.fixture(scope="module")
def data():
    return load_all()


@pytest.mark.parametrize("text, dtype, road, minutes", [
    ("avinasi rd la accident, rendu mani neram block", "accident", "R1", 120),
    ("two hours traffic jam at gandhi puram", "traffic", "R7", 120),
    ("trichy road mazhai, muppathu minutes late", "flood", "R2", 30),
    ("அவிநாசி சாலையில் விபத்து 2 மணி நேரம்", "accident", "R1", 120),
    ("customer not available at RS Puram, door locked", "customer_unavailable", "R6", 0),
])
def test_parser_understands_misspellings_spoken_numbers_and_tamil(data, text, dtype, road, minutes):
    p = parse_disruption(text, data, use_llm=False)
    assert (p["type"], p["road_id"], p["duration_min"]) == (dtype, road, minutes), p
