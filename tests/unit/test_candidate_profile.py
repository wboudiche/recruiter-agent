"""The profile block handed to the interview-question generator."""
from recruiter.models import Candidate
from recruiter.pipeline.candidate_profile import profile_text, to_extracted


def _candidate() -> Candidate:
    return Candidate(
        source_type="paste",
        full_name="Marie Dupont",
        headline="Staff SRE",
        location="Lyon",
        summary="Runs platform reliability for a payments team.",
        skills=["Kubernetes", "Terraform"],
        experience=[{"title": "Staff SRE", "company": "Acme", "start": "2021", "end": None,
                     "description": "Owned the cluster migration."}],
        education=[{"degree": "MSc CS", "school": "INSA", "year": "2015"}],
        links=[{"label": "github", "url": "https://github.com/marie"}],
    )


def test_to_extracted_carries_the_structured_fields() -> None:
    out = to_extracted(_candidate())
    assert out.full_name == "Marie Dupont"
    assert out.skills == ["Kubernetes", "Terraform"]
    assert out.experience[0].company == "Acme"


def test_profile_text_includes_what_scoring_already_sees() -> None:
    """The scorer gets the whole structured candidate; probes used to get
    `summary` alone, which is why they kept asking what the CV answers."""
    text = profile_text(_candidate(), enrichment=None)

    assert "Staff SRE" in text
    assert "Kubernetes" in text
    assert "Acme" in text
    assert "Runs platform reliability" in text


def test_profile_text_folds_in_enrichment_summaries() -> None:
    """Enrichment is the richest source of 'ask for a concrete story' material
    and was not reaching the generator at all."""
    bundle = {"results": [
        {"source": "github", "profile_url": "https://github.com/marie", "confidence": 0.9,
         "discovered": False, "signals": [],
         "summary": "Maintains a Terraform provider with 400 stars."},
        {"source": "blog", "profile_url": "https://marie.dev", "confidence": 0.4,
         "discovered": True, "signals": [], "summary": "Writes about incident reviews."},
    ]}

    text = profile_text(_candidate(), enrichment=bundle)

    assert "Terraform provider" in text
    assert "incident reviews" in text


def test_profile_text_survives_a_bare_candidate() -> None:
    """Extraction can fail to fill anything but a name."""
    text = profile_text(Candidate(source_type="paste", full_name="Sam"), enrichment=None)
    assert "Sam" in text
