from apokalypse.blocklist import parse_blocklist


def test_parses_common_blocklist_formats() -> None:
    rules = parse_blocklist(
        """
        # ignored comment
        Example network:1.2.3.0-1.2.3.255
        10.0.0.0/24
        192.0.2.7
        invalid entry
        """
    )

    assert [(rule.first, rule.last) for rule in rules] == [
        ("1.2.3.0", "1.2.3.255"),
        ("10.0.0.0", "10.0.0.255"),
        ("192.0.2.7", "192.0.2.7"),
    ]


def test_deduplicates_and_normalizes_reversed_ranges() -> None:
    rules = parse_blocklist("1.1.1.9-1.1.1.1\n1.1.1.1-1.1.1.9")
    assert len(rules) == 1
    assert rules[0].first == "1.1.1.1"
    assert rules[0].last == "1.1.1.9"

