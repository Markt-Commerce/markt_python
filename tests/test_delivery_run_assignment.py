"""Unit tests for DeliveryRunAssignmentService: rider discovery,
acceptance, decline, and mid-run failure/reassignment for a DeliveryRun
(10.6-10.7, Phase 10)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.deliveries.models import (
    AssignmentStatus,
    DeliveryRun,
    DeliveryRunStatus,
    DeliveryStatus,
)
from app.deliveries.run_assignment import DeliveryRunAssignmentService
from app.libs.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)


def _query_side_effect(**by_name):
    def side_effect(model):
        m = MagicMock()
        name = getattr(model, "__name__", None)
        config = by_name.get(name)
        if config:
            config(m)
        return m

    return side_effect


# --- get_available_runs -----------------------------------------------------


def test_get_available_runs_raises_not_found_for_missing_partner():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryRunAssignmentService.get_available_runs("DEL_1")


def test_get_available_runs_raises_forbidden_when_suspended():
    delivery_user = SimpleNamespace(status=DeliveryStatus.SUSPENDED)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = delivery_user

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ForbiddenError):
            DeliveryRunAssignmentService.get_available_runs("DEL_1")


def test_get_available_runs_raises_validation_when_no_location():
    delivery_user = SimpleNamespace(status=DeliveryStatus.ACTIVE, last_location=None)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = delivery_user

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ValidationError):
            DeliveryRunAssignmentService.get_available_runs("DEL_1")


@patch("app.deliveries.services.DeliveryService.haversine_distance")
def test_get_available_runs_filters_by_distance_and_missing_area_location(
    mock_distance,
):
    delivery_user = SimpleNamespace(
        status=DeliveryStatus.ACTIVE,
        last_location=SimpleNamespace(latitude=6.45, longitude=3.39),
    )
    near_run = SimpleNamespace(
        id="RUN_NEAR",
        area=SimpleNamespace(name="Campus A", latitude=6.45, longitude=3.39),
        market=SimpleNamespace(name="Market A"),
        price_per_order=250.0,
    )
    far_run = SimpleNamespace(
        id="RUN_FAR",
        area=SimpleNamespace(name="Campus B", latitude=10.0, longitude=10.0),
        market=SimpleNamespace(name="Market B"),
        price_per_order=250.0,
    )
    no_area_location_run = SimpleNamespace(
        id="RUN_NO_LOC",
        area=SimpleNamespace(name="Campus C", latitude=None, longitude=None),
        market=None,
        price_per_order=None,
    )

    session = MagicMock()

    def user_query(m):
        m.filter_by.return_value.first.return_value = delivery_user

    def run_query(m):
        m.filter.return_value.options.return_value.order_by.return_value.all.return_value = [
            near_run,
            far_run,
            no_area_location_run,
        ]

    def run_order_query(m):
        m.filter_by.return_value.count.return_value = 2

    session.query.side_effect = _query_side_effect(
        DeliveryUser=user_query,
        DeliveryRun=run_query,
        DeliveryRunOrder=run_order_query,
    )
    mock_distance.side_effect = [100.0, 50000.0]

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunAssignmentService.get_available_runs(
            "DEL_1", search_radius=5000
        )

    assert result["total"] == 1
    assert result["runs"][0]["run_id"] == "RUN_NEAR"
    assert result["runs"][0]["order_count"] == 2


# --- accept_run --------------------------------------------------------------


@patch("app.deliveries.pickup.create_stops_for_run")
def test_accept_run_success(mock_create_stops):
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.RIDER_ASSIGNMENT)
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    delivery_user = SimpleNamespace(status=DeliveryStatus.ACTIVE)
    session = MagicMock()

    def run_query(m):
        m.filter_by.return_value.with_for_update.return_value.first.return_value = run

    def user_query(m):
        m.filter_by.return_value.first.return_value = delivery_user

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = None

    session.query.side_effect = _query_side_effect(
        DeliveryRun=run_query,
        DeliveryUser=user_query,
        DeliveryRunAssignment=assignment_query,
    )
    session.add.side_effect = lambda obj: setattr(obj, "id", 99)

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunAssignmentService.accept_run("DEL_1", "RUN_1")

    assert result == {
        "run_id": "RUN_1",
        "status": DeliveryRunStatus.RIDER_ACCEPTED.value,
        "assignment_id": 99,
    }
    assert run.status == DeliveryRunStatus.RIDER_ACCEPTED
    mock_create_stops.assert_called_once_with(session, "RUN_1")


def test_accept_run_raises_not_found_for_missing_run():
    session = MagicMock()

    def run_query(m):
        m.filter_by.return_value.with_for_update.return_value.first.return_value = None

    session.query.side_effect = _query_side_effect(DeliveryRun=run_query)

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryRunAssignmentService.accept_run("DEL_1", "RUN_1")


def test_accept_run_raises_conflict_when_already_rejected():
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.RIDER_ASSIGNMENT)
    delivery_user = SimpleNamespace(status=DeliveryStatus.ACTIVE)
    already_rejected = SimpleNamespace(status=AssignmentStatus.REJECTED)
    session = MagicMock()

    def run_query(m):
        m.filter_by.return_value.with_for_update.return_value.first.return_value = run

    def user_query(m):
        m.filter_by.return_value.first.return_value = delivery_user

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = already_rejected

    session.query.side_effect = _query_side_effect(
        DeliveryRun=run_query,
        DeliveryUser=user_query,
        DeliveryRunAssignment=assignment_query,
    )

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            DeliveryRunAssignmentService.accept_run("DEL_1", "RUN_1")


def test_accept_run_raises_conflict_when_already_accepted_by_someone_else():
    """Simulates the race a real row lock protects against: the run is no
    longer at RIDER_ASSIGNMENT by the time this rider's transition runs."""
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.RIDER_ACCEPTED)
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    delivery_user = SimpleNamespace(status=DeliveryStatus.ACTIVE)
    session = MagicMock()

    def run_query(m):
        m.filter_by.return_value.with_for_update.return_value.first.return_value = run

    def user_query(m):
        m.filter_by.return_value.first.return_value = delivery_user

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = None

    session.query.side_effect = _query_side_effect(
        DeliveryRun=run_query,
        DeliveryUser=user_query,
        DeliveryRunAssignment=assignment_query,
    )

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            DeliveryRunAssignmentService.accept_run("DEL_1", "RUN_1")


# --- reject_run ----------------------------------------------------------------


def test_reject_run_records_decline_without_changing_run_status():
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.RIDER_ASSIGNMENT)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = run
    session.add.side_effect = lambda obj: None

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunAssignmentService.reject_run("DEL_1", "RUN_1")

    assert result == {"run_id": "RUN_1", "status": AssignmentStatus.REJECTED.value}
    assert run.status == DeliveryRunStatus.RIDER_ASSIGNMENT
    added = session.add.call_args[0][0]
    assert added.status == AssignmentStatus.REJECTED
    assert added.delivery_user_id == "DEL_1"


def test_reject_run_raises_not_found_for_missing_run():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryRunAssignmentService.reject_run("DEL_1", "RUN_1")


# --- fail_run --------------------------------------------------------------


def test_fail_run_reopens_for_reassignment():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.RIDER_ACCEPTED)
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_query(m):
        m.filter_by.return_value.with_for_update.return_value.first.return_value = run

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRun=run_query
    )

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        result = DeliveryRunAssignmentService.fail_run(
            "DEL_1", "RUN_1", reason="vehicle breakdown"
        )

    assert result == {
        "run_id": "RUN_1",
        "status": DeliveryRunStatus.RIDER_ASSIGNMENT.value,
    }
    assert assignment.status == AssignmentStatus.FAILED
    assert run.status == DeliveryRunStatus.RIDER_ASSIGNMENT


def test_fail_run_raises_not_found_when_no_accepted_assignment():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(NotFoundError):
            DeliveryRunAssignmentService.fail_run("DEL_1", "RUN_1")


def test_fail_run_raises_conflict_when_run_cannot_transition():
    assignment = SimpleNamespace(status=AssignmentStatus.ACCEPTED)
    run = SimpleNamespace(id="RUN_1", status=DeliveryRunStatus.COMPLETED)
    run.transition_to = lambda new_status, _r=run: DeliveryRun.transition_to(
        _r, new_status
    )
    session = MagicMock()

    def assignment_query(m):
        m.filter_by.return_value.first.return_value = assignment

    def run_query(m):
        m.filter_by.return_value.with_for_update.return_value.first.return_value = run

    session.query.side_effect = _query_side_effect(
        DeliveryRunAssignment=assignment_query, DeliveryRun=run_query
    )

    with patch("app.deliveries.run_assignment.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        with pytest.raises(ConflictError):
            DeliveryRunAssignmentService.fail_run("DEL_1", "RUN_1")
