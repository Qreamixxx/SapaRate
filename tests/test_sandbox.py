import pytest

from backend import sandbox


def test_parse_lines_and_timestamps():
    m = sandbox.parse("К: Привет\nО: Здравствуйте\nпродолжение\nклиент: Спасибо")
    assert [x["speaker"] for x in m] == ["client", "operator", "client"]
    assert m[1]["text"] == "Здравствуйте продолжение" and [x["timestamp"] for x in m] == ["00:00", "00:05", "00:10"]


@pytest.mark.parametrize("bad", ["", "просто текст", "К: только клиент", "О: только оператор"])
def test_parse_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        sandbox.parse(bad)


def test_language():
    assert sandbox.language("Сәлеметсіз бе") == "KZ" and sandbox.language("Привет") == "RU" and sandbox.language("Hello") == "EN"
