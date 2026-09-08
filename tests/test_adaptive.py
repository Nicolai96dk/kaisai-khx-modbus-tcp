"""Adaptive heat-curve learning tests."""

from datetime import UTC, datetime, timedelta

from custom_components.kaisai_khx.adaptive import (
    ADAPTIVE_CORRECTION_LIMIT,
    AdaptiveBucket,
    AdaptiveLearningModel,
)


def observe_range(
    model: AdaptiveLearningModel,
    *,
    start: datetime,
    hours: int,
    indoor_target: float = 21,
    final_indoor_temperature: float = 20,
) -> None:
    """Feed a continuous 15-minute observation range."""
    for quarter_hour in range(hours * 4 + 1):
        model.observe(
            now=start + timedelta(minutes=quarter_hour * 15),
            effective_ambient=2,
            indoor_temperature=(final_indoor_temperature if quarter_hour == hours * 4 else indoor_target),
            indoor_target=indoor_target,
            response_hours=hours,
        )


def test_new_model_observes_before_applying_a_correction() -> None:
    model = AdaptiveLearningModel()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert model.observe(
        now=now,
        effective_ambient=2,
        indoor_temperature=20,
        indoor_target=21,
        response_hours=8,
    )

    assert model.total_samples == 1
    assert model.learning_updates == 0
    assert model.estimate(2).phase == "observing"
    assert model.estimate(2).correction == 0


def test_model_learns_only_from_a_delayed_observation() -> None:
    model = AdaptiveLearningModel()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observe_range(model, start=start, hours=8)

    estimate = model.estimate(2)
    assert model.learning_updates == 1
    assert estimate.correction == 0.2
    assert estimate.confidence == 8
    assert estimate.phase == "blending"
    assert model.last_room_error == 1
    assert model.last_adjustment == 0.2


def test_model_updates_at_most_once_per_hour() -> None:
    model = AdaptiveLearningModel()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observe_range(model, start=start, hours=1, final_indoor_temperature=19)
    first_correction = model.estimate(2).correction

    model.observe(
        now=start + timedelta(hours=1, minutes=30),
        effective_ambient=2,
        indoor_temperature=19,
        indoor_target=21,
        response_hours=1,
    )

    assert model.learning_updates == 1
    assert model.estimate(2).correction == first_correction


def test_model_reaches_active_phase_after_twelve_local_updates() -> None:
    model = AdaptiveLearningModel()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for quarter_hour in range(12 * 4 + 1):
        model.observe(
            now=start + timedelta(minutes=quarter_hour * 15),
            effective_ambient=2,
            indoor_temperature=20,
            indoor_target=21,
            response_hours=1,
        )

    estimate = model.estimate(2)
    assert model.learning_updates == 12
    assert estimate.confidence == 100
    assert estimate.phase == "active"


def test_each_update_and_total_correction_are_safety_bounded() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    model = AdaptiveLearningModel(buckets={"2.5": AdaptiveBucket(correction=2.9, updates=5)})
    observe_range(model, start=start, hours=1, final_indoor_temperature=10)

    assert model.last_adjustment == 0.25
    assert model.estimate(2).correction == ADAPTIVE_CORRECTION_LIMIT


def test_target_change_prevents_misattributed_learning() -> None:
    model = AdaptiveLearningModel()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    model.observe(
        now=start,
        effective_ambient=2,
        indoor_temperature=21,
        indoor_target=20,
        response_hours=1,
    )
    for quarter_hour in range(1, 5):
        model.observe(
            now=start + timedelta(minutes=quarter_hour * 15),
            effective_ambient=2,
            indoor_temperature=18 if quarter_hour == 4 else 22,
            indoor_target=22,
            response_hours=1,
        )

    assert model.learning_updates == 0
    assert model.estimate(2).phase == "observing"


def test_observation_gap_prevents_misattributed_learning() -> None:
    model = AdaptiveLearningModel()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    model.observe(
        now=start,
        effective_ambient=2,
        indoor_temperature=21,
        indoor_target=21,
        response_hours=1,
    )
    model.observe(
        now=start + timedelta(hours=1),
        effective_ambient=2,
        indoor_temperature=18,
        indoor_target=21,
        response_hours=1,
    )

    assert model.learning_updates == 0
    assert model.estimate(2).phase == "observing"


def test_nearby_temperature_buckets_are_blended() -> None:
    model = AdaptiveLearningModel(
        buckets={
            "-2.5": AdaptiveBucket(correction=1, updates=12),
            "2.5": AdaptiveBucket(correction=0, updates=12),
        }
    )

    estimate = model.estimate(0)

    assert estimate.correction == 0.5
    assert estimate.confidence == 100
    assert estimate.phase == "active"


def test_persistent_state_is_sanitized_and_omits_indoor_history() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    model = AdaptiveLearningModel.from_dict(
        {
            "buckets": {
                "2.5": {"correction": 99, "updates": 2},
                "invalid": {"correction": 1, "updates": 2},
            },
            "samples": [
                {
                    "timestamp": now.isoformat(),
                    "effective_ambient": 2,
                    "indoor_target": 21,
                    "indoor_temperature": 20,
                }
            ],
        }
    )

    stored = model.as_dict()
    assert model.estimate(2).correction == ADAPTIVE_CORRECTION_LIMIT
    assert len(stored["samples"]) == 1
    assert "indoor_temperature" not in stored["samples"][0]
