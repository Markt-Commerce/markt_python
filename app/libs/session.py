from contextlib import contextmanager
from external.database import db


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    try:
        yield db.session
        db.session.commit()
    except:
        db.session.rollback()
        raise


@contextmanager
def read_scope():
    """A read-only scope whose objects stay usable after it closes.

    `session_scope` commits on exit, and SQLAlchemy expires every instance in
    the identity map on commit. Any attribute touched afterwards -- even
    `obj.id` -- issues a fresh SELECT for that single row. Code that loads a
    batch inside a scope and then builds payloads outside it therefore pays one
    query per object, which is an N+1 that no amount of `joinedload` can fix
    because the eager-loaded state is discarded too.

    This yields the same session with expiry suppressed and rolls back instead
    of committing, so loaded objects survive the block with their attributes
    intact. Read paths only -- anything that writes must use `session_scope`.
    """
    # db.session is a scoped_session proxy and doesn't carry the flag itself;
    # it lives on the Session the registry hands back.
    session = db.session()
    previous = session.expire_on_commit
    session.expire_on_commit = False
    try:
        # No commit and no rollback on the happy path: both expire every
        # instance in the identity map, which is the exact thing this scope
        # exists to avoid. Nothing here writes, so there is nothing to flush;
        # the connection is returned when the request tears the session down.
        yield session
    except:
        session.rollback()
        raise
    finally:
        session.expire_on_commit = previous
