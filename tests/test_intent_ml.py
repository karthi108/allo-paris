"""ML intent classifier: features, training, save/load, committed model sanity (no network)."""

from __future__ import annotations

from pathlib import Path

from app.agent.intent_ml import LABELS, IntentModel, features

ROWS = [
    ("prochain métro à Nation", "departures"),
    ("next train at Bastille", "departures"),
    ("trafic ligne 4", "status"),
    ("any delays on line 9", "status"),
    ("borne de recharge près de Bercy", "ev"),
    ("EV charger near Opéra", "ev"),
    ("combien coûte un ticket", "out_of_scope"),
    ("how much is the pass", "out_of_scope"),
]


def test_features_include_words_bigrams_and_char_ngrams() -> None:
    f = features("Vélib Bastille")
    assert "w:velib" in f and "b:velib_bastille" in f and "c:<ve" in f


def test_trained_model_separates_simple_labels() -> None:
    model = IntentModel.train(ROWS, epochs=30)
    assert model.predict("prochain métro à Bercy")[0] == "departures"
    assert model.predict("recharge voiture Nation")[0] == "ev"
    label, p = model.predict("combien coûte le pass")
    assert label == "out_of_scope" and 0 < p <= 1
    assert abs(sum(model.proba("anything")) - 1.0) < 1e-9


def test_save_and_load_roundtrip() -> None:
    model = IntentModel.train(ROWS, epochs=10)
    path = Path("data") / "_test_intent_model.json"
    try:
        model.save(path, {"rows": len(ROWS)})
        back = IntentModel.load(path)
        assert back is not None
        assert back.predict("trafic ligne 4")[0] == model.predict("trafic ligne 4")[0]
    finally:
        path.unlink()


def test_committed_model_loads_with_the_eight_labels() -> None:
    model = IntentModel.load(Path("data") / "intent_model.json")
    assert model is not None
    assert len(model.bias) == len(LABELS) == 8


def test_ml_gate_answers_out_of_scope_without_the_llm() -> None:
    from app.agent.dialog import CallState, Dialog
    from tests.conftest import FakeSource
    from tests.test_agent import ScriptedLLM

    class Never(ScriptedLLM):
        def chat(self, *a: object, **k: object) -> object:  # type: ignore[override]
            raise AssertionError("the LLM must not be called")

    from app.agent.agent import Agent
    from app.data.stops import StopIndex

    index = StopIndex.load(Path("data") / "stops.json")
    jokes = [("tell me a joke", "out_of_scope"), ("raconte une blague", "out_of_scope")]
    model = IntentModel.train((ROWS + jokes) * 3, epochs=30)
    agent = Agent(Never([]), lambda: None)
    dialog = Dialog(index, FakeSource(), agent=agent, intent_model=model)
    reply = dialog.handle("raconte-moi une blague drôle", CallState())  # rules: unknown
    assert reply.path == "ml" and reply.intent == "out_of_scope"
    assert "prix" in reply.text
