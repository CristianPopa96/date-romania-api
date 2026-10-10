from datetime import date

from typer.testing import CliRunner

from date_romania import cli

runner = CliRunner()


def test_collect_carries_on_after_a_day_that_fails(monkeypatch):
    seen = []

    def collect_day(session, client, day):
        seen.append(day)
        if day == date(2026, 10, 2):
            raise RuntimeError("SEAP answered nonsense")
        return 5

    monkeypatch.setattr(cli, "yesterday", lambda: date(2026, 10, 3))
    monkeypatch.setattr(cli.seap_direct, "collect_day", collect_day)

    result = runner.invoke(cli.app, ["collect", "seap-direct", "--since", "2026-10-01"])

    assert seen == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]
    assert result.exit_code == 1
    assert "2026-10-01: 5 direct purchases" in result.output
    assert "2026-10-03: 5 direct purchases" in result.output
    assert "failed: 2026-10-02" in result.output


def test_collect_exits_cleanly_when_every_day_works(monkeypatch):
    monkeypatch.setattr(cli.seap_direct, "collect_day", lambda session, client, day: 7)
    result = runner.invoke(cli.app, ["collect", "seap-direct", "--date", "2026-10-06"])
    assert result.exit_code == 0
    assert "2026-10-06: 7 direct purchases" in result.output
