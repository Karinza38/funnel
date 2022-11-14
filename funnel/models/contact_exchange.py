"""Model for contacts scanned from badges at in-person events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime
from itertools import groupby
from typing import Collection, Iterable, Optional
from uuid import UUID

from sqlalchemy.ext.associationproxy import association_proxy

from coaster.sqlalchemy import LazyRoleSet
from coaster.utils import uuid_to_base58

from ..typing import OptionalMigratedTables
from . import RoleMixin, TimestampMixin, db, sa
from .project import Project
from .sync_ticket import TicketParticipant
from .user import User

__all__ = ['ContactExchange']


# Data classes for returning contacts grouped by project and date
@dataclass
class ProjectId:
    """Holder for minimal :class:`~funnel.models.project.Project` information."""

    id: int  # noqa: A003
    uuid: UUID
    uuid_b58: str
    title: str
    timezone: str


@dataclass
class DateCountContacts:
    """Contacts per date of a Project's schedule."""

    date: datetime
    count: int
    contacts: Collection[ContactExchange]


class ContactExchange(
    TimestampMixin,
    RoleMixin,
    db.Model,  # type: ignore[name-defined]
):
    """Model to track who scanned whose badge, in which project."""

    __tablename__ = 'contact_exchange'
    #: User who scanned this contact
    user_id = sa.Column(
        sa.Integer, sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True
    )
    user = sa.orm.relationship(
        User,
        backref=sa.orm.backref(
            'scanned_contacts',
            lazy='dynamic',
            order_by='ContactExchange.scanned_at.desc()',
            passive_deletes=True,
        ),
    )
    #: Participant whose contact was scanned
    ticket_participant_id = sa.Column(
        sa.Integer,
        sa.ForeignKey('ticket_participant.id', ondelete='CASCADE'),
        primary_key=True,
        index=True,
    )
    ticket_participant = sa.orm.relationship(
        TicketParticipant,
        backref=sa.orm.backref('scanned_contacts', passive_deletes=True),
    )
    #: Datetime at which the scan happened
    scanned_at = sa.Column(
        sa.TIMESTAMP(timezone=True), nullable=False, default=sa.func.utcnow()
    )
    #: Note recorded by the user (plain text)
    description = sa.Column(sa.UnicodeText, nullable=False, default='')
    #: Archived flag
    archived = sa.Column(sa.Boolean, nullable=False, default=False)

    __roles__ = {
        'owner': {
            'read': {
                'user',
                'ticket_participant',
                'scanned_at',
                'description',
                'archived',
            },
            'write': {'description', 'archived'},
        },
        'subject': {'read': {'user', 'ticket_participant', 'scanned_at'}},
    }

    def roles_for(
        self, actor: Optional[User] = None, anchors: Iterable = ()
    ) -> LazyRoleSet:
        roles = super().roles_for(actor, anchors)
        if actor is not None:
            if actor == self.user:
                roles.add('owner')
            if actor == self.ticket_participant.user:
                roles.add('subject')
        return roles

    @classmethod
    def migrate_user(  # type: ignore[return]
        cls, old_user: User, new_user: User
    ) -> OptionalMigratedTables:
        """Migrate one user account to another when merging user accounts."""
        ticket_participant_ids = {
            ce.ticket_participant_id for ce in new_user.scanned_contacts
        }
        for ce in old_user.scanned_contacts:
            if ce.ticket_participant_id not in ticket_participant_ids:
                ce.user = new_user
            else:
                # Discard duplicate contact exchange
                db.session.delete(ce)

    @classmethod
    def grouped_counts_for(cls, user, archived=False):
        """Return count of contacts grouped by project and date."""
        query = db.session.query(
            cls.scanned_at, Project.id, Project.uuid, Project.timezone, Project.title
        ).filter(
            cls.ticket_participant_id == TicketParticipant.id,
            TicketParticipant.project_id == Project.id,
            cls.user == user,
        )

        if not archived:
            # If archived: return everything (contacts including archived contacts)
            # If not archived: return only unarchived contacts
            query = query.filter(cls.archived.is_(False))

        # from_self turns `SELECT columns` into `SELECT new_columns FROM (SELECT
        # columns)`
        query = (
            query.from_self(
                Project.id.label('id'),
                Project.uuid.label('uuid'),
                Project.title.label('title'),
                Project.timezone.label('timezone'),
                sa.cast(
                    sa.func.date_trunc(
                        'day', sa.func.timezone(Project.timezone, cls.scanned_at)
                    ),
                    sa.Date,
                ).label('date'),
                sa.func.count().label('count'),
            )
            .group_by(
                sa.text('id'),
                sa.text('uuid'),
                sa.text('title'),
                sa.text('timezone'),
                sa.text('date'),
            )
            .order_by(sa.text('date DESC'))
        )

        # Issued SQL:
        #
        # SELECT
        #   project_id AS id,
        #   project_uuid AS uuid,
        #   project_title AS title,
        #   project_timezone AS "timezone",
        #   date_trunc(
        #     'day',
        #     timezone("timezone", contact_exchange_scanned_at)
        #   )::date AS date,
        #   count(*) AS count
        # FROM (
        #   SELECT
        #     contact_exchange.scanned_at AS contact_exchange_scanned_at,
        #     project.id AS project_id,
        #     project.uuid AS project_uuid,
        #     project.title AS project_title,
        #     project.timezone AS project_timezone
        #   FROM contact_exchange, ticket_participant, project
        #   WHERE
        #     contact_exchange.ticket_participant_id = ticket_participant.id
        #     AND ticket_participant.project_id = project.id
        #     AND contact_exchange.user_id = :user_id
        #   ) AS anon_1
        # GROUP BY id, uuid, title, timezone, date
        # ORDER BY date DESC;

        # Our query result looks like this:
        # [(id, uuid, title, timezone, date, count), ...]
        # where (id, uuid, title, timezone) repeat for each date
        #
        # Transform it into this:
        # [
        #   (ProjectId(id, uuid, uuid_b58, title, timezone), [
        #     DateCountContacts(date, count, contacts),
        #     ...  # More dates
        #     ]
        #   ),
        #   ...  # More projects
        #   ]

        # We don't do it here, but this can easily be converted into a dictionary of
        # {project: dates}:
        # >>> OrderedDict(result)  # Preserve order with most recent projects first
        # >>> dict(result)         # Don't preserve order

        groups = [
            (
                k,
                [
                    DateCountContacts(
                        r.date,
                        r.count,
                        cls.contacts_for_project_and_date(user, k, r.date, archived),
                    )
                    for r in g
                ],
            )
            for k, g in groupby(
                query,
                lambda r: ProjectId(
                    r.id, r.uuid, uuid_to_base58(r.uuid), r.title, r.timezone
                ),
            )
        ]

        return groups

    @classmethod
    def contacts_for_project_and_date(
        cls, user: User, project: Project, date: date_type, archived=False
    ):
        """Return contacts for a given user, project and date."""
        query = cls.query.join(TicketParticipant).filter(
            cls.user == user,
            # For safety always use objects instead of column values. The following
            # expression should have been `Participant.project == project`. However, we
            # are using `id` here because `project` may be an instance of ProjectId
            # returned by `grouped_counts_for`
            TicketParticipant.project_id == project.id,
            sa.cast(
                sa.func.date_trunc(
                    'day', sa.func.timezone(project.timezone.zone, cls.scanned_at)
                ),
                sa.Date,
            )
            == date,
        )
        if not archived:
            # If archived: return everything (contacts including archived contacts)
            # If not archived: return only unarchived contacts
            query = query.filter(cls.archived.is_(False))

        return query

    @classmethod
    def contacts_for_project(cls, user, project, archived=False):
        """Return contacts for a given user and project."""
        query = cls.query.join(TicketParticipant).filter(
            cls.user == user,
            # See explanation for the following expression in
            # `contacts_for_project_and_date`
            TicketParticipant.project_id == project.id,
        )
        if not archived:
            # If archived: return everything (contacts including archived contacts)
            # If not archived: return only unarchived contacts
            query = query.filter(cls.archived.is_(False))
        return query


TicketParticipant.scanning_users = association_proxy('scanned_contacts', 'user')
