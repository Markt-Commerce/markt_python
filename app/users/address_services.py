"""Managing a buyer's saved addresses."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.libs.errors import NotFoundError, ValidationError
from app.libs.geo import is_valid_coordinate
from app.libs.session import session_scope

from .addresses import BuildingType, SavedAddress

logger = logging.getLogger(__name__)

#: Enough for anyone, and a bound on what a compromised session can create.
MAX_SAVED_ADDRESSES = 25


class SavedAddressService:
    @staticmethod
    def list_for_user(session, user_id: str) -> List[SavedAddress]:
        """Default first, then most recently used, then newest.

        That ordering is the whole point of the picker: the address you want
        is nearly always the one you used last, and scrolling past eleven
        others to reach it is the friction this replaces.
        """
        return (
            session.query(SavedAddress)
            .filter_by(user_id=user_id)
            .order_by(
                SavedAddress.is_default.desc(),
                SavedAddress.last_used_at.desc().nullslast(),
                SavedAddress.created_at.desc(),
            )
            .all()
        )

    @staticmethod
    def create(user_id: str, data: Dict[str, Any]) -> SavedAddress:
        lat, lng = data.get("latitude"), data.get("longitude")
        if not is_valid_coordinate(lat, lng):
            # Not a formality. An address with no usable coordinate cannot be
            # quoted for delivery or found by a rider, so it is not an
            # address as far as this app is concerned.
            raise ValidationError(
                "We need the location of this address before we can save it."
            )

        with session_scope() as session:
            count = session.query(SavedAddress).filter_by(user_id=user_id).count()
            if count >= MAX_SAVED_ADDRESSES:
                raise ValidationError(
                    f"You can save up to {MAX_SAVED_ADDRESSES} addresses. "
                    "Delete one you no longer use to add another."
                )

            address = SavedAddress(
                user_id=user_id,
                label=(data.get("label") or "").strip() or None,
                formatted_address=data["formatted_address"].strip(),
                latitude=lat,
                longitude=lng,
                city=(data.get("city") or "").strip() or None,
                state=(data.get("state") or "").strip() or None,
                building_type=data.get("building_type") or BuildingType.HOUSE,
                entry_code=(data.get("entry_code") or "").strip() or None,
                directions=(data.get("directions") or "").strip() or None,
                contact_name=(data.get("contact_name") or "").strip() or None,
                contact_phone=(data.get("contact_phone") or "").strip() or None,
            )
            # The first address someone saves is their default, without being
            # asked. Nobody wants to be prompted to nominate a favourite when
            # they only have one.
            address.is_default = count == 0 or bool(data.get("is_default"))
            if address.is_default:
                SavedAddressService._clear_other_defaults(session, user_id, None)
            session.add(address)
            session.flush()
            session.expunge(address)
            return address

    @staticmethod
    def update(user_id: str, address_id: int, data: Dict[str, Any]) -> SavedAddress:
        with session_scope() as session:
            address = SavedAddressService._owned(session, user_id, address_id)

            if "latitude" in data or "longitude" in data:
                lat = data.get("latitude", address.latitude)
                lng = data.get("longitude", address.longitude)
                if not is_valid_coordinate(lat, lng):
                    raise ValidationError("That doesn't look like a real location.")
                address.latitude, address.longitude = lat, lng

            for field in (
                "label",
                "entry_code",
                "directions",
                "contact_name",
                "contact_phone",
                "city",
                "state",
            ):
                if field in data:
                    setattr(address, field, (data[field] or "").strip() or None)
            if data.get("formatted_address"):
                address.formatted_address = data["formatted_address"].strip()
            if data.get("building_type"):
                address.building_type = data["building_type"]

            if data.get("is_default"):
                SavedAddressService._clear_other_defaults(session, user_id, address.id)
                address.is_default = True

            session.flush()
            session.expunge(address)
            return address

    @staticmethod
    def delete(user_id: str, address_id: int) -> None:
        with session_scope() as session:
            address = SavedAddressService._owned(session, user_id, address_id)
            was_default = address.is_default
            session.delete(address)
            session.flush()

            if was_default:
                # Never leave someone with addresses but no default -- the
                # picker would open with nothing selected and checkout would
                # look broken.
                replacement = (
                    session.query(SavedAddress)
                    .filter_by(user_id=user_id)
                    .order_by(
                        SavedAddress.last_used_at.desc().nullslast(),
                        SavedAddress.created_at.desc(),
                    )
                    .first()
                )
                if replacement is not None:
                    replacement.is_default = True

    @staticmethod
    def mark_used(session, user_id: str, address_id: int) -> None:
        """Called when an order actually ships to this address.

        Best effort: failing to record that someone used an address is not a
        reason to fail their order.
        """
        try:
            address = (
                session.query(SavedAddress)
                .filter_by(id=address_id, user_id=user_id)
                .first()
            )
            if address is not None:
                address.last_used_at = datetime.utcnow()
        except Exception:
            logger.exception("Could not stamp saved address %s as used", address_id)

    @staticmethod
    def _owned(session, user_id: str, address_id: int) -> SavedAddress:
        address = (
            session.query(SavedAddress)
            .filter_by(id=address_id, user_id=user_id)
            .first()
        )
        if address is None:
            # Not "forbidden": whether an address id exists is not something
            # a stranger needs to learn.
            raise NotFoundError("Address not found")
        return address

    @staticmethod
    def _clear_other_defaults(session, user_id: str, keep_id: Optional[int]) -> None:
        q = session.query(SavedAddress).filter(
            SavedAddress.user_id == user_id, SavedAddress.is_default.is_(True)
        )
        if keep_id is not None:
            q = q.filter(SavedAddress.id != keep_id)
        q.update({"is_default": False}, synchronize_session=False)
