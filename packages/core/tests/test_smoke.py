import larder_core


def test_version_is_exposed() -> None:
    assert larder_core.__version__ == "0.0.0"
