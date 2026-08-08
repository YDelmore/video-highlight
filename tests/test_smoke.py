"""Smoke test verifying test infrastructure and package imports."""


def test_package_imports():
    from video_highlight import main

    assert callable(main)


def test_fixtures_dir_exists(fixtures_dir):
    assert fixtures_dir.is_dir()
    assert (fixtures_dir / "sample.xml").is_file()


def test_synthetic_density_module_loads():
    from tests.fixtures.synthetic_density import SAMPLE_DF

    assert len(SAMPLE_DF) == 5
    assert set(SAMPLE_DF.columns) >= {"t", "uid", "text", "length"}
