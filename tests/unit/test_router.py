import pytest

from recruiter.pipeline.router import RoutedInput, classify_url


def test_classify_github_url() -> None:
    assert classify_url("https://github.com/alice") == "github"
    assert classify_url("http://github.com/bob/") == "github"


def test_classify_linkedin_url() -> None:
    assert classify_url("https://www.linkedin.com/in/alice/") == "linkedin"
    assert classify_url("https://linkedin.com/in/bob") == "linkedin"


def test_classify_generic_url() -> None:
    assert classify_url("https://alice.dev") == "webpage"
    assert classify_url("https://example.com/about") == "webpage"


def test_classify_invalid_url() -> None:
    with pytest.raises(ValueError, match="invalid URL"):
        classify_url("not a url")


def test_classify_does_not_eat_leading_w_from_non_www_hosts() -> None:
    # Regression: previously lstrip("www.") would strip ALL leading w/. chars,
    # mangling hosts like "wwwapp.com" into "app.com" (an unrelated webpage).
    assert classify_url("https://wwwapp.com/profile") == "webpage"
    assert classify_url("https://wonderful.example") == "webpage"


def test_routed_input_holds_kind_and_payload() -> None:
    r = RoutedInput(kind="paste", text="hello", source_url=None, resume_path=None)
    assert r.kind == "paste"
    assert r.text == "hello"
