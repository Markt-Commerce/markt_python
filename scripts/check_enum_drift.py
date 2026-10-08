#!/usr/bin/env python
"""Report Postgres enum types that have fallen behind their Python enums.

Run against any environment:

    DB_NAME=... python scripts/check_enum_drift.py

Why this exists as a script rather than a test: alembic's autogenerate does not
diff enum labels, so `flask db check` reports a clean schema while a type is
missing values the models expect. And the migration files are not a reliable
oracle either -- some labels reached the database through paths the migrations
don't record, so parsing them statically both misses real drift and invents
drift that isn't there. The only trustworthy comparison is model vs. live
database, which means connecting to one.

The failure this catches is invisible until someone writes a missing value, and
then it is a 500:

    invalid input value for enum order_items_status: "PROCESSING"

That one had broken seller fulfilment entirely -- PROCESSING is the only legal
first transition out of PENDING, and the type did not contain it.

Exits non-zero when anything has drifted, so it can gate a deploy.
"""

import sys


def main() -> int:
    from main.setup import create_app

    app, _ = create_app()
    with app.app_context():
        import sqlalchemy as sa
        from external.database import db
        from main.config import settings

        print(f"Database: {settings.DB_NAME} @ {settings.DB_HOST}:{settings.DB_PORT}\n")

        inspector = sa.inspect(db.engine)
        db_enums = {e["name"]: set(e["labels"]) for e in inspector.get_enums()}

        problems = []
        seen = set()
        for mapper in db.Model.registry.mappers:
            table = mapper.local_table
            if table is None:
                continue
            for column in table.columns:
                if not isinstance(column.type, sa.Enum):
                    continue
                type_name = column.type.name
                if not type_name or type_name not in db_enums:
                    continue
                key = (table.name, column.name)
                if key in seen:
                    continue
                seen.add(key)
                missing = set(column.type.enums) - db_enums[type_name]
                if missing:
                    problems.append(
                        (f"{table.name}.{column.name}", type_name, sorted(missing))
                    )

        if not problems:
            print(f"OK — {len(seen)} enum column(s) checked, none drifted.")
            return 0

        for where, type_name, missing in problems:
            print(f"DRIFT  {where}  (type: {type_name})")
            print(f"       missing in database: {', '.join(missing)}")
            print(
                f"       fix: ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS "
                f"'{missing[0]}';  (one per value, in a migration)\n"
            )
        print(f"{len(problems)} drifted enum(s).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
