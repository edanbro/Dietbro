from larder_core.aliases import load_alias_rows, load_aliases
from larder_core.names import normalise_name


def test_aliases_are_well_formed() -> None:
    rows = load_alias_rows()
    names = [a.name for a in rows]
    assert len(names) == len(set(names))
    assert len(rows) > 500
    assert all(a.fdc_id > 0 and a.description for a in rows)
    assert load_aliases()["onion"] == 170000


def test_alias_names_are_normalised() -> None:
    # A key the normaliser can never produce would be dead weight.
    assert [a.name for a in load_alias_rows() if normalise_name(a.name) != a.name] == []
