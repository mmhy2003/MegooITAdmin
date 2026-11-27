import pytest

from app.logs.allowlist import STARTER_PATTERNS, check_pattern, matches


def test_a_wildcard_never_crosses_a_slash():
    assert not matches("/var/log/nginx/access.log", ["/var/log/*.log"])
    assert matches("/var/log/nginx/access.log", ["/var/log/nginx/*.log"])


def test_a_question_mark_matches_one_character():
    assert matches("/var/log/app1.log", ["/var/log/app?.log"])
    assert not matches("/var/log/app12.log", ["/var/log/app?.log"])
    assert not matches("/var/log/app/.log", ["/var/log/app?.log"])


def test_other_characters_match_only_themselves():
    assert not matches("/var/log/aXlog", ["/var/log/a.log"])
    assert matches("/var/log/+x", ["/var/log/+x"])
    assert not matches("/var/log/x", ["/var/log/+x"])
    assert not matches("/var/log/++x", ["/var/log/+x"])


def test_the_whole_path_must_match():
    assert not matches("/var/log/syslog.1", ["/var/log/syslog"])
    assert not matches("/old/var/log/syslog", ["/var/log/syslog"])
    assert matches("/var/log/syslog", ["/var/log/messages", "/var/log/syslog"])


def test_no_pattern_matches_nothing():
    assert not matches("/var/log/syslog", [])


@pytest.mark.parametrize(
    "pattern", ["/*", "/v*r/log", "var/log", "/var/../etc", "/var//x", "/var/log/", "/var/log/[ab]", "/" + "a" * 255],
)
def test_refused_patterns(pattern):
    with pytest.raises(ValueError):
        check_pattern(pattern)


def test_the_starter_patterns_are_valid():
    assert STARTER_PATTERNS == ("/var/log/syslog", "/var/log/messages", "/var/log/nginx/*.log", "/var/log/apache2/*.log")
    for pattern in STARTER_PATTERNS:
        assert check_pattern(pattern) == pattern
