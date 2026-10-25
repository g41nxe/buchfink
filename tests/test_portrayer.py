"""Der Steckbrief-Ersteller und seine zwei Wege zum Modell (ADR 33, #52).

Kein Test hier ruft ein Modell: die Leitung ist ein Stub, der Unterprozess und
die API sind ersetzt.
"""

from __future__ import annotations

import json

import pytest

from conftest import needs_vocabulary
from ebook_watchlist.models import MatchReason, Observation
from ebook_watchlist.portrait import ANSWER_SCHEMA, Parts, PortrayalUnavailable, load_vocabulary
from ebook_watchlist.portrayer import (
    ApiChannel,
    CliChannel,
    Portrayer,
    _cli_text,
    build_portrayer,
)

ANSWER = '{"bekannt": false}'


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    from subprocess import CompletedProcess

    return CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr)


# --- der Weg ohne Schlüssel: claude -p -------------------------------------------


def test_the_cli_answer_is_read_out_of_its_json_envelope(monkeypatch) -> None:
    """``--output-format json`` verpackt das Ergebnis in ``result``."""
    monkeypatch.setattr(
        "ebook_watchlist.portrayer.subprocess.run",
        lambda *a, **k: _completed(stdout=json.dumps({"result": ANSWER, "is_error": False})),
    )

    assert CliChannel().ask("Frage") == ANSWER


def test_a_bare_answer_is_read_too(monkeypatch) -> None:
    """Auf das Hüllenformat zu bestehen hieße, an einer fremden Version zu
    hängen. Fehlt sie, geht der Text unverändert weiter."""
    monkeypatch.setattr(
        "ebook_watchlist.portrayer.subprocess.run", lambda *a, **k: _completed(stdout=ANSWER)
    )

    assert CliChannel().ask("Frage") == ANSWER


def test_a_missing_executable_is_no_reason_to_fail_a_run(monkeypatch) -> None:
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr("ebook_watchlist.portrayer.subprocess.run", boom)

    with pytest.raises(PortrayalUnavailable, match="nicht gefunden"):
        CliChannel().ask("Frage")


def test_a_timeout_is_reported_as_unavailable(monkeypatch) -> None:
    from subprocess import TimeoutExpired

    def slow(*a, **k):
        raise TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr("ebook_watchlist.portrayer.subprocess.run", slow)

    with pytest.raises(PortrayalUnavailable, match="antwortete nicht"):
        CliChannel(timeout=1).ask("Frage")


def test_a_nonzero_exit_names_what_the_cli_said(monkeypatch) -> None:
    monkeypatch.setattr(
        "ebook_watchlist.portrayer.subprocess.run",
        lambda *a, **k: _completed(returncode=1, stderr="not logged in"),
    )

    with pytest.raises(PortrayalUnavailable, match="not logged in"):
        CliChannel().ask("Frage")


def test_the_prompt_reaches_the_cli_over_stdin(monkeypatch) -> None:
    """Nicht als Argument: Windows begrenzt eine Kommandozeile auf 32767
    Zeichen. Python meldet das als FileNotFoundError, also ununterscheidbar von
    "claude ist nicht installiert"."""
    seen: list[tuple[list[str], str | None]] = []

    def capture(command, **kwargs):
        seen.append((command, kwargs.get("input")))
        return _completed(stdout=ANSWER)

    monkeypatch.setattr("ebook_watchlist.portrayer.subprocess.run", capture)

    CliChannel(executable="claude").ask("Blindflug von Peter Watts")

    command, text = seen[0]
    assert command[:4] == ["claude", "-p", "--output-format", "json"]
    assert text == "Blindflug von Peter Watts"
    assert not any("Blindflug" in part for part in command)


def test_the_cli_runs_lean_with_the_configured_model(monkeypatch) -> None:
    """Gemessen am 24.09.2026 an einem echten Fund: der bloße Aufruf kostete
    rund 61 000 Eingabe-Tokens (Claude Codes eigene Anweisung, Werkzeuge und die
    MCP-Server der Leserin) und 0,33 $; mit eigener kurzer Anweisung, ohne
    Werkzeuge, Einstellungen und MCP und mit Haiku waren es 10 800 Tokens und
    0,03 $ — bei gleich guten Steckbriefen."""
    seen: list[tuple[list[str], dict]] = []

    def capture(command, **kwargs):
        seen.append((command, kwargs))
        return _completed(stdout=ANSWER)

    monkeypatch.setattr("ebook_watchlist.portrayer.subprocess.run", capture)

    CliChannel(executable="claude", model="haiku").ask("Frage")

    command, kwargs = seen[0]
    assert command[command.index("--model") + 1] == "haiku"
    assert command[command.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in command and "--disable-slash-commands" in command
    assert "--no-session-persistence" in command
    assert command[command.index("--setting-sources") + 1] == ""
    assert "--system-prompt" in command
    assert kwargs["env"]["MAX_THINKING_TOKENS"] == "2048"


def test_the_thinking_budget_can_be_turned_off(monkeypatch) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(
        "ebook_watchlist.portrayer.subprocess.run",
        lambda command, **kwargs: seen.append(kwargs) or _completed(stdout=ANSWER),
    )

    CliChannel(thinking_tokens=0).ask("Frage")

    assert seen[0]["env"]["MAX_THINKING_TOKENS"] == "0"


def test_an_error_envelope_is_not_mistaken_for_an_answer() -> None:
    """Gemessen an einer abgelaufenen Anmeldung: die Hülle trug exit 0, aber
    is_error true, und in ``result`` stand "Failed to authenticate: OAuth
    session expired". Ohne diese Prüfung wanderte das als Antwort weiter."""
    envelope = json.dumps({
        "is_error": True,
        "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
        "type": "result",
    })

    with pytest.raises(PortrayalUnavailable, match="OAuth session expired"):
        _cli_text(envelope)


def test_a_failing_call_names_what_the_envelope_says(monkeypatch) -> None:
    """Gemessen an einem Container ohne Anmeldung: Rückgabewert 1, stderr leer,
    und der einzige Hinweis — "Not logged in · Please run /login" — stand in der
    Hülle auf stdout."""
    monkeypatch.setattr(
        "ebook_watchlist.portrayer.subprocess.run",
        lambda *a, **k: _completed(
            stdout=json.dumps({"is_error": True, "result": "Not logged in · Please run /login"}),
            returncode=1,
        ),
    )

    with pytest.raises(PortrayalUnavailable, match="Not logged in"):
        CliChannel().ask("Frage")


def test_a_failure_without_an_envelope_still_names_the_return_code(monkeypatch) -> None:
    monkeypatch.setattr(
        "ebook_watchlist.portrayer.subprocess.run",
        lambda *a, **k: _completed(stdout="", stderr="Killed", returncode=137),
    )

    with pytest.raises(PortrayalUnavailable, match="endete mit 137: Killed"):
        CliChannel().ask("Frage")


def test_a_good_envelope_still_yields_its_result() -> None:
    envelope = json.dumps({"is_error": False, "result": '{"bekannt": true}'})

    assert _cli_text(envelope) == '{"bekannt": true}'


# --- der Weg über die API ------------------------------------------------------------


class _Block:
    def __init__(self, kind: str, text: str = "") -> None:
        self.type, self.text = kind, text


class _Message:
    def __init__(self, blocks, stop_reason: str = "end_turn") -> None:
        self.content, self.stop_reason = blocks, stop_reason


class _Stream:
    def __init__(self, message) -> None:
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def get_final_message(self):
        return self.message


class FakeClient:
    """Steht für `anthropic.Anthropic`: nimmt die Anfragen entgegen, fragt niemanden."""

    def __init__(self, message=None, error: Exception | None = None) -> None:
        self.sent: list[dict] = []
        self.error = error
        self.reply = message or _Message([_Block("text", ANSWER)])
        self.messages = self
        self.batches = FakeBatches(self)

    def stream(self, **params):
        self.sent.append(params)
        if self.error:
            raise self.error
        return _Stream(self.reply)


class FakeBatches:
    def __init__(self, client: FakeClient) -> None:
        self.client, self.created, self.polls = client, [], 0

    def create(self, requests):
        self.created = list(requests)
        return type("Batch", (), {"id": "msgbatch_1", "processing_status": "in_progress"})()

    def retrieve(self, batch_id):
        self.polls += 1
        status = "ended" if self.polls >= 2 else "in_progress"
        return type("Batch", (), {"id": batch_id, "processing_status": status})()

    def results(self, batch_id):
        # Absichtlich verkehrt herum: Ergebnisse kommen in beliebiger Reihenfolge.
        for request in reversed(self.created):
            custom_id = request["custom_id"]
            if custom_id.endswith("2"):
                yield type("R", (), {"custom_id": custom_id, "result": type(
                    "E", (), {"type": "errored"})()})()
                continue
            answer = f'{{"bekannt": false, "n": "{custom_id}"}}'
            message = _Message([_Block("thinking"), _Block("text", answer)])
            yield type("R", (), {"custom_id": custom_id, "result": type(
                "S", (), {"type": "succeeded", "message": message})()})()


PARTS = Parts(stable="Anweisung und Vokabular",
              variable="--- BUCH ---\nTitel: X\n--- ENDE BUCH ---")


def test_the_api_caches_the_vocabulary_and_fixes_the_shape() -> None:
    """Das Vokabular steht vorn und wird gecacht; die Form der Antwort legt ein
    Schema fest, statt dass das Modell sie aus dem Text abliest (#102)."""
    client = FakeClient()

    answer = ApiChannel(api_key="sk-test", client=client).ask_parts(PARTS, ANSWER_SCHEMA)

    assert answer == ANSWER
    params = client.sent[0]
    assert params["model"] == "claude-haiku-5-5"
    assert params["system"] == [{"type": "text", "text": PARTS.stable,
                                 "cache_control": {"type": "ephemeral"}}]
    assert params["messages"] == [{"role": "user", "content": PARTS.variable}]
    assert params["output_config"]["format"] == {"type": "json_schema", "schema": ANSWER_SCHEMA}
    # Haiku 5.5: Sampling-Parameter sind ein Fehler, ein festes Denkbudget auch.
    assert "temperature" not in params and "thinking" not in params


def test_thinking_blocks_are_not_the_answer() -> None:
    client = FakeClient(_Message([_Block("thinking"), _Block("text", ANSWER)]))

    assert ApiChannel(api_key="sk-test", client=client).ask_parts(PARTS, ANSWER_SCHEMA) == ANSWER


@pytest.mark.parametrize(
    ("stop", "word"), [("refusal", "abgelehnt"), ("max_tokens", "abgeschnitten")]
)
def test_a_cut_or_refused_answer_is_unavailable(stop: str, word: str) -> None:
    client = FakeClient(_Message([_Block("text", "{")], stop_reason=stop))

    with pytest.raises(PortrayalUnavailable, match=word):
        ApiChannel(api_key="sk-test", client=client).ask_parts(PARTS, ANSWER_SCHEMA)


def test_an_unreachable_api_is_unavailable_not_a_crash() -> None:
    import anthropic
    import httpx2

    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x.invalid"))

    with pytest.raises(PortrayalUnavailable, match="nicht erreichbar"):
        ApiChannel(api_key="sk-test", client=FakeClient(error=error)).ask_parts(PARTS, None)


def test_an_error_status_is_named() -> None:
    import anthropic
    import httpx2

    response = httpx2.Response(529, request=httpx2.Request("POST", "https://x.invalid"))
    error = anthropic.APIStatusError("überlastet", response=response, body=None)

    with pytest.raises(PortrayalUnavailable, match="529"):
        ApiChannel(api_key="sk-test", client=FakeClient(error=error)).ask_parts(PARTS, None)


def test_a_batch_comes_back_by_its_ids_not_its_order() -> None:
    """Die Batch-API für `ebw rate` (#102): halber Preis, Ergebnisse in
    beliebiger Reihenfolge, ein fehlgeschlagener Eintrag kostet nur sich."""
    client = FakeClient()
    channel = ApiChannel(api_key="sk-test", client=client)

    answers = channel.batch({"b1": (PARTS, ANSWER_SCHEMA), "b2": (PARTS, ANSWER_SCHEMA),
                             "b3": (PARTS, ANSWER_SCHEMA)}, poll_seconds=0)

    assert set(answers) == {"b1", "b3"}
    assert json.loads(answers["b1"])["n"] == "b1"
    request = client.batches.created[0]["params"]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["output_config"]["format"]["schema"] == ANSWER_SCHEMA


@needs_vocabulary
def test_the_api_path_hands_over_parts_and_schema() -> None:
    """Der Weg über die Kommandozeile bekommt weiter genau den alten Text."""
    client = FakeClient()
    portrayer = Portrayer(ApiChannel(api_key="sk-test", client=client), load_vocabulary())

    portrayer.portray("Der Schwarm", "Frank Schätzing", "Ein Meer, das zurückschlägt.")

    params = client.sent[0]
    assert "Der Schwarm" in params["messages"][0]["content"]
    assert "Der Schwarm" not in params["system"][0]["text"]
    assert "VOKABULAR" in params["system"][0]["text"]


@needs_vocabulary
def test_rate_uses_the_batch_when_asked() -> None:
    client = FakeClient()
    portrayer = Portrayer(ApiChannel(api_key="sk-test", client=client), load_vocabulary())
    finds = [Observation(source="beam", source_item_id=str(n), title=f"Titel {n}", author="A",
                         match_reason=MatchReason.GENRE_CATEGORY) for n in (1, 2, 3)]

    described = portrayer.portray_finds(finds, batch=True)

    assert client.sent == []  # kein einzelner Aufruf
    assert len(client.batches.created) == 3
    assert set(described) == {("beam", "1"), ("beam", "3")}


# --- welcher Weg gewählt wird ----------------------------------------------------------


@needs_vocabulary
def test_a_key_in_the_environment_wins(monkeypatch) -> None:
    """Wer ihn setzt, hat sich für ihn entschieden."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("ebook_watchlist.portrayer.shutil.which", lambda name: "/usr/bin/claude")

    portrayer = build_portrayer(None, load_vocabulary())

    assert isinstance(portrayer.channel, ApiChannel)


@needs_vocabulary
def test_without_a_key_the_local_installation_is_used(monkeypatch) -> None:
    """API-Zugang ist in keinem Claude-Abo enthalten; die angemeldete
    Installation ist der Weg ohne zusätzliches Guthaben."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ebook_watchlist.portrayer.shutil.which", lambda name: "/usr/bin/claude")

    portrayer = build_portrayer(None, load_vocabulary())

    assert isinstance(portrayer.channel, CliChannel)
    assert portrayer.channel.executable == "/usr/bin/claude"
    assert portrayer.channel.model == "haiku"


@needs_vocabulary
def test_the_configured_model_reaches_the_cli_too(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ebook_watchlist.portrayer.shutil.which", lambda name: "/usr/bin/claude")

    portrayer = build_portrayer("sonnet", load_vocabulary())

    assert portrayer.channel.model == "sonnet"


@needs_vocabulary
def test_the_configured_model_is_used_on_the_api_path(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    portrayer = build_portrayer("ein-anderes-modell", load_vocabulary())

    assert portrayer.channel.model == "ein-anderes-modell"


@needs_vocabulary
def test_with_neither_there_is_simply_no_portrayer(monkeypatch) -> None:
    """Kein Fehler, sondern der Zustand ohne neue Steckbriefe: alles bleibt
    unbeschrieben und wird gezeigt."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("ebook_watchlist.portrayer.shutil.which", lambda name: None)

    assert build_portrayer(None, load_vocabulary()) is None


# --- das Beschreiben ----------------------------------------------------------------------


class Recorder:
    def __init__(self, answer: str) -> None:
        self.answer, self.asked = answer, []

    def ask(self, text: str, max_tokens: int = 2000) -> str:
        self.asked.append((text, max_tokens))
        return self.answer


@needs_vocabulary
def test_portraying_asks_once_and_reads_the_answer() -> None:
    recorder = Recorder('{"bekannt": false}')

    portrait = Portrayer(recorder, load_vocabulary()).portray("Ein Titel", "Wer", "Klappentext")

    assert not portrait.known
    text, max_tokens = recorder.asked[0]
    assert "Ein Titel" in text and "Klappentext" in text and max_tokens == 2000


@needs_vocabulary
def test_a_find_is_described_with_its_original_title_and_keywords() -> None:
    """Ein Buch, das das Modell nur unter dem englischen Titel kennt, bliebe
    sonst unbekannt (#17)."""
    recorder = Recorder('{"bekannt": false}')
    observation = Observation(
        source="beam", source_item_id="7", title="Der Zeitenläufer", author="Blake Crouch",
        match_reason=MatchReason.GENRE_CATEGORY, blurb="Ein Physiker.",
        original_title="Dark Matter", keywords=("Space Opera", "Dune"),
    )

    Portrayer(recorder, load_vocabulary()).portray_find(observation)

    text = recorder.asked[0][0]
    assert "Der Zeitenläufer (Originaltitel: Dark Matter)" in text
    assert "Blake Crouch" in text and "Ein Physiker." in text
    assert "Schlagwörter: Space Opera, Dune" in text


@needs_vocabulary
def test_an_unreadable_answer_is_unavailable_not_guessed() -> None:
    with pytest.raises(PortrayalUnavailable):
        Portrayer(Recorder("gar kein JSON"), load_vocabulary()).portray("Titel", None, None)


# --- mehrere Funde in einem Aufruf (#66) -----------------------------------------------


def _find(number: int) -> Observation:
    return Observation(
        source="beam", source_item_id=str(number), title=f"Fund {number}", author="Wer",
        match_reason=MatchReason.GENRE_CATEGORY, blurb="Ein Klappentext.",
    )


class BatchChannel:
    """Antwortet auf ein Bündel mit ``{"bekannt": false}`` je Buch — außer dort, wo
    die Antwort etwas anderes vorsieht."""

    def __init__(self, fail_on=(), skip=()) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail_on, self.skip = set(fail_on), set(skip)

    def ask(self, text: str, max_tokens: int = 2000) -> str:
        self.calls.append((text, max_tokens))
        if len(self.calls) in self.fail_on:
            raise PortrayalUnavailable("kein Netz")
        if "--- BUCH 1 ---" not in text:  # ein einzelnes Buch
            return '{"bekannt": false}'
        count = text.count("--- ENDE BUCH ")
        return json.dumps({str(i): {"bekannt": False} for i in range(1, count + 1)
                           if i not in self.skip})


@needs_vocabulary
def test_ten_finds_cost_three_calls_at_a_batch_size_of_four() -> None:
    channel = BatchChannel()
    portrayer = Portrayer(channel, load_vocabulary(), batch_size=4)
    finds = [_find(n) for n in range(10)]

    results = portrayer.portray_finds(finds)

    assert len(channel.calls) == 3 and len(results) == 10
    assert [max_tokens for _, max_tokens in channel.calls] == [8000, 8000, 4000]


@needs_vocabulary
def test_a_single_book_at_the_end_is_asked_the_ordinary_way() -> None:
    channel = BatchChannel()

    Portrayer(channel, load_vocabulary(), batch_size=4).portray_finds(
        [_find(n) for n in range(5)]
    )

    text, max_tokens = channel.calls[-1]
    assert "--- BUCH 1 ---" not in text and max_tokens == 2000


@needs_vocabulary
def test_a_failed_batch_costs_that_batch_and_no_more() -> None:
    channel = BatchChannel(fail_on={2})
    portrayer = Portrayer(channel, load_vocabulary(), batch_size=2)
    finds = [_find(n) for n in range(6)]

    results = portrayer.portray_finds(finds)

    assert len(channel.calls) == 3
    assert sorted(o.key[1] for o in finds if o.key in results) == ["0", "1", "4", "5"]


@needs_vocabulary
def test_a_book_the_batch_answer_skips_is_missing_from_the_result() -> None:
    portrayer = Portrayer(BatchChannel(skip={2}), load_vocabulary(), batch_size=8)
    finds = [_find(n) for n in range(3)]

    results = portrayer.portray_finds(finds)

    assert finds[1].key not in results and finds[0].key in results and finds[2].key in results


@needs_vocabulary
def test_an_empty_list_asks_nobody() -> None:
    channel = BatchChannel()

    assert Portrayer(channel, load_vocabulary()).portray_finds([]) == {}
    assert channel.calls == []


def test_the_thinking_budget_grows_with_the_batch(monkeypatch) -> None:
    """Es gilt je Buch: acht Bücher mit dem Budget für eines würden flüchtig."""
    seen: list[dict] = []
    monkeypatch.setattr(
        "ebook_watchlist.portrayer.subprocess.run",
        lambda command, **kwargs: seen.append(kwargs["env"]) or _completed(stdout=ANSWER),
    )

    CliChannel().ask("Ein Buch", 2000)
    CliChannel().ask("Acht Bücher", 16000)

    assert [e["MAX_THINKING_TOKENS"] for e in seen] == ["2048", "16384"]


# --- die Leseprobe als zweite Stufe (#76) --------------------------------------------------


KNOWN = json.dumps({
    "bekannt": True, "titel": "Maddrax 697", "autor": "Wer", "genre": "Science-Fiction",
    "untergenre": "Endzeit", "pitch": "Ein Pitch.",
    "merkmale": [{"id": "gritty", "satz": "Staub.", "beleg": "leseprobe", "gewicht": "praegend"},
                 {"id": "fast_paced", "satz": "Tempo.", "beleg": "klappentext",
                  "gewicht": "deutlich"},
                 {"id": "brooding", "satz": "Figur.", "beleg": "leseprobe", "gewicht": "rand"}],
    "erzaehlmuster": [],
})


class SecondTry:
    """Erst „unbekannt", mit Leseprobe dann bekannt."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def ask(self, text: str, max_tokens: int = 2000) -> str:
        self.asked.append(text)
        return KNOWN if "Leseprobe" in text else '{"bekannt": false}'


def _with_sample(url: str | None = "https://beam.invalid/probe.epub") -> Observation:
    return Observation(
        source="beam", source_item_id="697", title="Maddrax 697", author="Wer",
        match_reason=MatchReason.GENRE_CATEGORY, blurb="Ein Vorwort der Redaktion.",
        sample_url=url,
    )


@needs_vocabulary
def test_unknown_despite_a_blurb_asks_once_more_with_the_sample() -> None:
    channel = SecondTry()
    portrayer = Portrayer(channel, load_vocabulary(), samples=lambda url: "Es war staubig.")

    portrait = portrayer.portray_finds([_with_sample()])[_with_sample().key]

    assert portrait.known and portrait.with_sample
    assert len(channel.asked) == 2
    assert "Es war staubig." in channel.asked[1]
    # Die Leseprobe gilt als Beleg, weil sie beilag.
    assert not any("Beleg" in v for v in portrait.violations)


@needs_vocabulary
def test_without_a_sample_the_book_stays_unknown_and_is_asked_once() -> None:
    channel = SecondTry()
    portrayer = Portrayer(channel, load_vocabulary(), samples=lambda url: "Es war staubig.")

    portrait = portrayer.portray_finds([_with_sample(url=None)])[_with_sample().key]

    assert not portrait.known and len(channel.asked) == 1


@needs_vocabulary
def test_a_sample_that_cannot_be_read_invents_nothing() -> None:
    channel = SecondTry()
    portrayer = Portrayer(channel, load_vocabulary(), samples=lambda url: None)

    portrait = portrayer.portray_finds([_with_sample()])[_with_sample().key]

    assert not portrait.known and len(channel.asked) == 1


@needs_vocabulary
def test_the_sample_is_evidence_only_when_it_came_along() -> None:
    """Ohne Probe hat sie das Modell erfunden (#69): dann ist sie ein Verstoß."""
    portrait = Portrayer(Recorder(KNOWN), load_vocabulary()).portray("Maddrax 697", "Wer", "Text")

    assert any("ungültiger Beleg" in v for v in portrait.violations)
