import httpx
import pytest

from date_romania.collectors.http import PoliteClient
from date_romania.config import get_settings


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def client(handler, fake: FakeTime, **kwargs) -> PoliteClient:
    return PoliteClient(
        transport=httpx.MockTransport(handler), sleep=fake.sleep, clock=fake.clock, **kwargs
    )


def test_sends_our_user_agent():
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200)

    client(handler, FakeTime()).request("GET", "https://example.test/a")
    assert seen == [get_settings().http_user_agent]


def test_waits_between_calls_to_the_same_host_only():
    fake = FakeTime()
    polite = client(lambda request: httpx.Response(200), fake, min_interval=1.0)
    polite.request("GET", "https://one.test/a")
    polite.request("GET", "https://two.test/a")
    assert fake.sleeps == []
    polite.request("GET", "https://one.test/b")
    assert fake.sleeps == [1.0]


def test_retries_transient_failures_with_growing_delays():
    answers = [httpx.Response(503), httpx.ConnectError("down"), httpx.Response(200, text="ok")]

    def handler(request):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    fake = FakeTime()
    response = client(handler, fake, min_interval=0).request("GET", "https://example.test/a")
    assert response.text == "ok"
    assert fake.sleeps == [2.0, 4.0]


def test_gives_up_after_the_last_retry():
    fake = FakeTime()
    polite = client(lambda request: httpx.Response(500), fake, min_interval=0, retries=2)
    with pytest.raises(httpx.HTTPError, match="after 3 tries"):
        polite.request("GET", "https://example.test/a")


def test_does_not_retry_a_client_error():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(httpx.HTTPStatusError):
        client(handler, FakeTime()).request("GET", "https://example.test/a")
    assert len(calls) == 1


def test_downloads_a_file_to_disk_retrying_from_the_start(tmp_path):
    answers = [httpx.Response(503), httpx.Response(200, content=b"a^b\r\n" * 3)]

    def handler(request):
        return answers.pop(0)

    fake = FakeTime()
    path = tmp_path / "file.csv"
    client(handler, fake).download("https://example.test/file.csv", path)
    assert path.read_bytes() == b"a^b\r\n" * 3
    assert fake.sleeps == [2.0]
