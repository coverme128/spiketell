import copy
import json
from pathlib import Path

import pytest

from app.domain.market import timestamp
from app.domain.engine import Engine
from app.repo.store import Store

FIXTURE = json.loads((Path(__file__).parents[1] / "spec/fixtures/rule_scenarios.json").read_text())


@pytest.fixture
def case():
    return copy.deepcopy(FIXTURE["cases"][0])


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "test.sqlite3")
    yield instance
    instance.close()


@pytest.fixture
def engine(store, case):
    b = case["bars"][-1]
    with store.transaction() as db:
        db.execute("INSERT INTO watchlist VALUES (?,1,?,?)", (b["symbol"], case["now"], case["now"]))
    instance = Engine(store)
    for bar in case["bars"][:-1]:
        instance.ingest(bar, timestamp(case["now"]))
    return instance
