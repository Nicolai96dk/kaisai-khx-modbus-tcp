"""Tests that exercise config-flow schemas with the real Home Assistant runtime."""

import pytest

pytest.importorskip("homeassistant")

import voluptuous_serialize
from homeassistant.helpers import config_validation as cv

from custom_components.kaisai_khx.config_flow import connection_schema


def test_first_setup_form_serializes() -> None:
    """The first setup form must be accepted by Home Assistant's HTTP API."""
    serialized = voluptuous_serialize.convert(
        connection_schema(), custom_serializer=cv.custom_serializer
    )

    assert [field["name"] for field in serialized] == ["host", "port", "unit_id", "name"]
    assert serialized[1]["selector"]["number"]["step"] == 1
    assert serialized[2]["selector"]["number"]["step"] == 1
