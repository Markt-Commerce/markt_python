"""The buyer's address book.

Markt already had three notions of an address and none of them was this:
UserAddress is one row per user and gets overwritten, Buyer.shipping_address
is a JSON blob of the same, and ShippingAddress is an order snapshot. These
cover the rules that make a *book* different from a single field.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.libs.errors import NotFoundError, ValidationError
from app.users.address_services import MAX_SAVED_ADDRESSES, SavedAddressService


def _payload(**kw):
    d = {
        "formatted_address": "Opp 1500 Lecture Theatre Junction, Under G Rd",
        "latitude": 8.1596,
        "longitude": 4.2612,
    }
    d.update(kw)
    return d


@patch("app.users.address_services.session_scope")
def test_an_address_without_a_coordinate_is_refused(mock_scope):
    """Not a formality. An address with no usable coordinate cannot be quoted
    for delivery and cannot be found by a rider, so it is not an address as
    far as this app is concerned."""
    for bad in (
        {"latitude": None, "longitude": None},
        {"latitude": 999, "longitude": 4.2},
    ):
        with pytest.raises(ValidationError):
            SavedAddressService.create("USR_1", _payload(**bad))


@patch("app.users.address_services.session_scope")
def test_the_first_address_becomes_the_default_without_being_asked(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.count.return_value = 0
    mock_scope.return_value.__enter__.return_value = session

    address = SavedAddressService.create("USR_1", _payload())
    assert address.is_default is True


@patch("app.users.address_services.session_scope")
def test_a_later_address_does_not_steal_the_default(mock_scope):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.count.return_value = 3
    mock_scope.return_value.__enter__.return_value = session

    address = SavedAddressService.create("USR_1", _payload())
    assert address.is_default is False


@patch("app.users.address_services.session_scope")
def test_there_is_a_ceiling_on_how_many_can_be_saved(mock_scope):
    """A bound on what a compromised session can create, and nobody has
    twenty-five homes."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.count.return_value = (
        MAX_SAVED_ADDRESSES
    )
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(ValidationError):
        SavedAddressService.create("USR_1", _payload())


@patch("app.users.address_services.session_scope")
def test_someone_elses_address_is_not_found_rather_than_forbidden(mock_scope):
    """Whether an address id exists is not a stranger's business."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mock_scope.return_value.__enter__.return_value = session

    with pytest.raises(NotFoundError):
        SavedAddressService.update("USR_OTHER", 1, {"label": "stolen"})
    with pytest.raises(NotFoundError):
        SavedAddressService.delete("USR_OTHER", 1)


@patch("app.users.address_services.session_scope")
def test_deleting_the_default_promotes_another(mock_scope):
    """A buyer with addresses but no default gets a picker that opens with
    nothing selected and a checkout that looks broken."""
    doomed = MagicMock(is_default=True)
    replacement = MagicMock(is_default=False)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = doomed
    session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = (
        replacement
    )
    mock_scope.return_value.__enter__.return_value = session

    SavedAddressService.delete("USR_1", 1)
    assert replacement.is_default is True


@patch("app.users.address_services.session_scope")
def test_deleting_a_non_default_promotes_nobody(mock_scope):
    doomed = MagicMock(is_default=False)
    other = MagicMock(is_default=False)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = doomed
    session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = (
        other
    )
    mock_scope.return_value.__enter__.return_value = session

    SavedAddressService.delete("USR_1", 1)
    assert other.is_default is False


def test_marking_an_address_used_never_breaks_an_order():
    """Failing to record that someone used an address is not a reason to fail
    the order that used it."""
    session = MagicMock()
    session.query.side_effect = RuntimeError("database went away")
    SavedAddressService.mark_used(session, "USR_1", 1)  # no raise
