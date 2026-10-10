from date_romania.config import Settings


def test_an_empty_variable_falls_back_to_the_default(monkeypatch):
    # Compose passes every setting through; one that is not set arrives empty.
    monkeypatch.setenv("HTTP_USER_AGENT", "")
    monkeypatch.setenv("S3_REGION", "")
    settings = Settings(_env_file=None)
    assert settings.http_user_agent.startswith("date-romania/")
    assert settings.s3_region == "us-east-1"


def test_a_set_variable_wins(monkeypatch):
    monkeypatch.setenv("HTTP_USER_AGENT", "someone-else/1.0")
    assert Settings(_env_file=None).http_user_agent == "someone-else/1.0"
