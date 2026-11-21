"""Tests that exercise config-flow schemas with the real Home Assistant runtime."""

import pytest

pytest.importorskip("homeassistant")

import voluptuous_serialize
from homeassistant.helpers import config_validation as cv

from custom_components.kaisai_khx.config_flow import (
    advanced_schema,
    connection_schema,
    efficiency_schema,
    features_schema,
)
from custom_components.kaisai_khx.models import (
    GENERIC_PROFILE_ID,
    KHX_09_PROFILE_ID,
    KHX_14_PROFILE_ID,
    KHX_16_PROFILE_ID,
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
    assert fields["efficiency_enabled"]["default"] is False
    assert len(fields) == 14


def test_efficiency_form_accepts_external_sensor_and_fractional_flow() -> None:
    """The same form can be rendered by the setup flow and options flow."""
    schema = efficiency_schema(KHX_09_PROFILE_ID)
    serialized = voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer)
    assert serialized[0]["selector"]["entity"]["filter"] == [
        {"domain": ["sensor"], "unit_of_measurement": ["W", "kW"]}
    ]
    assert serialized[1]["selector"]["number"]["unit_of_measurement"] == "m³/h"
    values = {"efficiency_power_sensor": "sensor.meter_power", "efficiency_flow_m3h": 0.78}
    assert schema(values) == values


@pytest.mark.parametrize(
    ("profile_id", "flow"),
    ((KHX_09_PROFILE_ID, 1.0), (KHX_14_PROFILE_ID, 1.7), (KHX_16_PROFILE_ID, 2.9)),
)
def test_efficiency_form_defaults_to_model_reference_flow(profile_id: str, flow: float) -> None:
    schema = efficiency_schema(profile_id)
    fields = voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer)

    assert fields[1]["default"] == flow
    assert schema({"efficiency_power_sensor": "sensor.meter_power"})["efficiency_flow_m3h"] == flow


def test_efficiency_form_keeps_saved_flow() -> None:
    schema = efficiency_schema(KHX_09_PROFILE_ID, saved_flow=0.78)
    fields = voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer)

    assert fields[1]["default"] == 0.78


def test_efficiency_form_requires_manual_flow_without_model_reference() -> None:
    fields = voluptuous_serialize.convert(
        efficiency_schema(GENERIC_PROFILE_ID), custom_serializer=cv.custom_serializer
    )

    assert "default" not in fields[1]


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
    assert [field["name"] for field in without_dhw] == [
        "scan_interval",
        "current_temperature_register",
        "weather_entity",
        "indoor_temperature_entity",
    ]
    assert without_dhw[2]["selector"]["entity"]["domain"] == ["weather"]
    assert without_dhw[3]["selector"]["entity"]["domain"] == ["sensor"]
