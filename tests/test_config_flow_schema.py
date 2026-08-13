"""Tests that exercise config-flow schemas with the real Home Assistant runtime."""

import pytest

pytest.importorskip("homeassistant")

import voluptuous_serialize
from homeassistant.helpers import config_validation as cv

from custom_components.kaisai_khx.config_flow import (
    advanced_schema,
    connection_schema,
    features_schema,
)


def test_first_setup_form_serializes() -> None:
    """The first setup form must be accepted by Home Assistant's HTTP API."""
    serialized = voluptuous_serialize.convert(
        connection_schema(), custom_serializer=cv.custom_serializer
    )

    assert [field["name"] for field in serialized] == ["host", "port", "unit_id", "name"]
    assert serialized[1]["selector"]["number"]["step"] == 1
    assert serialized[2]["selector"]["number"]["step"] == 1


def test_post_setup_feature_form_serializes_with_saved_values() -> None:
    """The options feature step exposes every feature and preserves its state."""
    serialized = voluptuous_serialize.convert(
        features_schema({"dhw_enabled": True, "cooling_enabled": False}),
        custom_serializer=cv.custom_serializer,
    )

    fields = {field["name"]: field for field in serialized}
    assert "profile" not in fields
    assert fields["dhw_enabled"]["default"] is True
    assert fields["cooling_enabled"]["default"] is False
    assert len(fields) == 13


def test_post_setup_advanced_form_tracks_dhw_feature() -> None:
    """DHW temperature becomes selectable only when DHW is enabled."""
    without_dhw = voluptuous_serialize.convert(
        advanced_schema({}, dhw_enabled=False), custom_serializer=cv.custom_serializer
    )
    with_dhw = voluptuous_serialize.convert(
        advanced_schema({}, dhw_enabled=True), custom_serializer=cv.custom_serializer
    )

    without_options = without_dhw[1]["selector"]["select"]["options"]
    with_options = with_dhw[1]["selector"]["select"]["options"]
    assert {option["value"] for option in without_options} == {
        "water_inlet_temperature",
        "water_outlet_temperature",
    }
    assert "water_tank_temperature" in {option["value"] for option in with_options}
