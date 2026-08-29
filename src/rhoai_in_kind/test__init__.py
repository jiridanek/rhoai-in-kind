from __future__ import annotations

from . import format_t_string

def test_t_string():
    name = "n"
    assert format_t_string(t"Hello, {name}!") == ("Hello, {name}!", {"name": "n"})
    assert format_t_string(t"Hello, {name=}!") == ("Hello, name={name}!", {"name": "n"})
