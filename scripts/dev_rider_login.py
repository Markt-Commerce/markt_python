#!/usr/bin/env python
"""Log a rider in locally without waiting for an email.

Rider sign-in sends a six-digit code to the delivery partner's *email* --
there is no SMS anywhere in this codebase, so Twilio is not what is standing
between you and the app. What is standing there is the round trip: the code
is only written to Redis once Resend accepts the message
(DeliveryService.send_otp), so a bounced address or a network blip means no
code exists to type, and the app can only tell you it failed.

This writes the code straight into Redis under the same key the login
endpoint reads, creating the partner if they do not exist yet. Nothing in
the application changes: there is no bypass, no test-mode flag, no branch in
send_otp that could ever reach production. It is the ordinary flow with the
email step done for you.

    python scripts/dev_rider_login.py 2348031234567
    python scripts/dev_rider_login.py 2348031234567 --name "Test Rider"

Then enter that phone number in the app and type the code it prints.

Refuses to run against anything but a local database, for the obvious
reason: it hands out a working credential.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres"}

# Fixed rather than random. You will type it a hundred times.
DEV_OTP = "123456"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phone",
        help="Digits only, including the country code, exactly as the app "
        "sends it: 234 followed by the number without its leading zero.",
    )
    parser.add_argument("--name", default="Dev Rider")
    parser.add_argument("--email", default=None, help="Defaults to <phone>@dev.local")
    parser.add_argument("--otp", default=DEV_OTP)
    args = parser.parse_args()

    from main.config import settings

    host = str(getattr(settings, "DB_HOST", "")).strip()
    if host not in LOCAL_HOSTS:
        print(f"REFUSING: DB_HOST is {host!r}, which is not local.", file=sys.stderr)
        print("This hands out a working login. Local databases only.", file=sys.stderr)
        return 1

    db_name = getattr(settings, "DB_NAME", "?")
    print(f"Database: {host}:{getattr(settings, 'DB_PORT', '?')}/{db_name}")

    from main.run import app
    from external.database import db
    from external.redis import redis_client
    from app.deliveries.models import DeliveryStatus, DeliveryUser
    from app.deliveries.services import DeliveryService, _normalize_phone

    phone = _normalize_phone(args.phone)
    if not phone.isdigit():
        print(f"REFUSING: {args.phone!r} is not digits-only.", file=sys.stderr)
        return 1
    if not (
        DeliveryService.PHONE_MIN_LEN <= len(phone) <= DeliveryService.PHONE_MAX_LEN
    ):
        print(
            f"REFUSING: {phone} is {len(phone)} digits; the API accepts "
            f"{DeliveryService.PHONE_MIN_LEN}-{DeliveryService.PHONE_MAX_LEN}. "
            "Include the country code and drop the leading zero "
            "(0803... in Nigeria becomes 234803...).",
            file=sys.stderr,
        )
        return 1

    with app.app_context():
        rider = db.session.query(DeliveryUser).filter_by(phone_number=phone).first()
        if rider:
            print(f"Rider:    {rider.id}  {rider.name}  ({rider.status.value})")
            if rider.status == DeliveryStatus.SUSPENDED:
                print(
                    "NOTE: this rider is SUSPENDED and login will be refused. "
                    "Reactivate them first.",
                    file=sys.stderr,
                )
        else:
            rider = DeliveryUser(
                phone_number=phone,
                email=args.email or f"{phone}@dev.local",
                name=args.name,
                status=DeliveryStatus.ACTIVE,
            )
            db.session.add(rider)
            db.session.commit()
            print(f"Rider:    {rider.id}  {rider.name}  (created)")

        key = f"{DeliveryService.CACHE_KEY_PREFIX}{phone}"
        redis_client.setex(key, DeliveryService.CACHE_EXPIRE_SECONDS, args.otp)

    minutes = DeliveryService.CACHE_EXPIRE_SECONDS // 60
    print()
    print(f"  Phone:  {phone}")
    print(f"  Code:   {args.otp}")
    print(f"  Valid:  {minutes} minutes")
    print()
    print("In the app, pick the country so the dial code matches, then enter")
    print("the rest of the number. Re-run this if the code expires.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
