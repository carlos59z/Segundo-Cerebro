import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))


def pytest_configure(config):
    config.addinivalue_line("markers", "network: tests que descargan datos reales")
