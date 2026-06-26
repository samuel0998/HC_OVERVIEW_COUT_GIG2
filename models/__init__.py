import sqlalchemy as sa
from flask import current_app, has_request_context, session
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session
from sqlalchemy import exc as sa_exc
from sqlalchemy import orm as sa_orm


def get_current_fc():
    default_fc = current_app.config.get("DEFAULT_FC", "GIG2")
    if has_request_context():
        return session.get("fc") or default_fc
    return current_app.config.get("ACTIVE_FC") or default_fc


class FCRoutingSession(Session):
    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        if bind is not None:
            return bind

        engines = self._db.engines

        if mapper is not None:
            try:
                mapper_inspected = sa.inspect(mapper)
            except sa_exc.NoInspectionAvailable as e:
                if isinstance(mapper, type):
                    raise sa_orm.exc.UnmappedClassError(mapper) from e
                raise

            bind_key = mapper_inspected.local_table.metadata.info.get("bind_key")
            if bind_key is not None:
                return engines[bind_key]

        fc = get_current_fc()
        return engines.get(fc) or engines[None]


db = SQLAlchemy(session_options={"class_": FCRoutingSession})
