"""Project crew and (future) participant registration membership."""

from __future__ import annotations

from typing import List, Set

from werkzeug.utils import cached_property

from coaster.sqlalchemy import DynamicAssociationProxy, immutable, with_roles

from . import DynamicMapped, Mapped, Model, declared_attr, relationship, sa
from .helpers import reopen
from .membership_mixin import ImmutableUserMembershipMixin
from .project import Project
from .user import User

__all__ = ['ProjectCrewMembership', 'project_child_role_map']

#: Roles in a project and their remapped names in objects attached to a project
project_child_role_map = {
    'editor': {'project_editor'},
    'promoter': {'project_promoter'},
    'usher': {'project_usher'},
    'crew': {'project_crew'},
    'participant': {'project_participant'},
    'reader': {'reader'},
}

#: ProjectCrewMembership maps project's `profile_admin` role to membership's `editor`
#: role in addition to the recurring role grant map
project_membership_role_map = {'profile_admin': {'profile_admin', 'editor'}}
project_membership_role_map.update(project_child_role_map)


class ProjectCrewMembership(ImmutableUserMembershipMixin, Model):
    """Users can be crew members of projects, with specified access rights."""

    __tablename__ = 'project_crew_membership'
    __allow_unmapped__ = True

    #: Legacy data has no granted_by
    __null_granted_by__ = True

    #: List of is_role columns in this model
    __data_columns__ = ('is_editor', 'is_promoter', 'is_usher', 'label')

    __roles__ = {
        'all': {
            'read': {
                'urls',
                'user',
                'project',
                'is_editor',
                'is_promoter',
                'is_usher',
                'label',
            }
        },
        'project_crew': {
            'read': {
                'record_type_label',
                'granted_at',
                'granted_by',
                'revoked_at',
                'revoked_by',
                'is_self_granted',
                'is_self_revoked',
            }
        },
    }
    __datasets__ = {
        'primary': {
            'urls',
            'uuid_b58',
            'offered_roles',
            'is_editor',
            'is_promoter',
            'is_usher',
            'label',
            'user',
            'project',
        },
        'without_parent': {
            'urls',
            'uuid_b58',
            'offered_roles',
            'is_editor',
            'is_promoter',
            'is_usher',
            'label',
            'user',
        },
        'related': {
            'urls',
            'uuid_b58',
            'offered_roles',
            'is_editor',
            'is_promoter',
            'is_usher',
            'label',
        },
    }

    project_id: Mapped[int] = sa.orm.mapped_column(
        sa.Integer, sa.ForeignKey('project.id', ondelete='CASCADE'), nullable=False
    )
    project: Mapped[Project] = with_roles(
        relationship(
            Project,
            backref=sa.orm.backref(
                'crew_memberships',
                lazy='dynamic',
                cascade='all',
                passive_deletes=True,
            ),
        ),
        grants_via={None: project_membership_role_map},
    )
    parent_id: Mapped[int] = sa.orm.synonym('project_id')
    parent_id_column = 'project_id'
    parent: Mapped[Project] = sa.orm.synonym('project')

    # Project crew roles (at least one must be True):

    #: Editors can edit all common and editorial details of an event
    is_editor: Mapped[bool] = sa.orm.mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    #: Promoters are responsible for promotion and have write access
    #: to common details plus read access to everything else. Unlike
    #: editors, they cannot edit the schedule
    is_promoter: Mapped[bool] = sa.orm.mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    #: Ushers help participants find their way around an event and have
    #: the ability to scan badges at the door
    is_usher: Mapped[bool] = sa.orm.mapped_column(
        sa.Boolean, nullable=False, default=False
    )

    #: Optional label, indicating the member's role in the project
    label = immutable(
        sa.orm.mapped_column(
            sa.Unicode,
            sa.CheckConstraint(
                "label <> ''", name='project_crew_membership_label_check'
            ),
            nullable=True,
        )
    )

    @declared_attr.directive
    @classmethod
    def __table_args__(cls) -> tuple:
        """Table arguments."""
        args = list(super().__table_args__)
        kwargs = args.pop(-1) if args and isinstance(args[-1], dict) else None
        args.append(
            sa.CheckConstraint(
                sa.or_(
                    cls.is_editor.is_(True),
                    cls.is_promoter.is_(True),
                    cls.is_usher.is_(True),
                ),
                name='project_crew_membership_has_role',
            )
        )
        if kwargs:
            args.append(kwargs)
        return tuple(args)

    @cached_property
    def offered_roles(self) -> Set[str]:
        """Roles offered by this membership record."""
        roles = {'crew', 'participant'}
        if self.is_editor:
            roles.add('editor')
        if self.is_promoter:
            roles.add('promoter')
        if self.is_usher:
            roles.add('usher')
        return roles


# Project relationships: all crew, vs specific roles
@reopen(Project)
class __Project:
    active_crew_memberships: DynamicMapped[List[ProjectCrewMembership]] = with_roles(
        relationship(
            ProjectCrewMembership,
            lazy='dynamic',
            primaryjoin=sa.and_(
                ProjectCrewMembership.project_id == Project.id,
                ProjectCrewMembership.is_active,
            ),
            viewonly=True,
        ),
        grants_via={
            'user': {
                'editor': {'editor', 'project_editor'},
                'promoter': {'promoter', 'project_promoter'},
                'usher': {'usher', 'project_usher'},
                'participant': {'participant', 'project_participant'},
                'crew': {'crew', 'project_crew'},
            }
        },
    )

    active_editor_memberships: DynamicMapped[
        List[ProjectCrewMembership]
    ] = relationship(
        ProjectCrewMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectCrewMembership.project_id == Project.id,
            ProjectCrewMembership.is_active,
            ProjectCrewMembership.is_editor.is_(True),
        ),
        viewonly=True,
    )

    active_promoter_memberships: DynamicMapped[
        List[ProjectCrewMembership]
    ] = relationship(
        ProjectCrewMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectCrewMembership.project_id == Project.id,
            ProjectCrewMembership.is_active,
            ProjectCrewMembership.is_promoter.is_(True),
        ),
        viewonly=True,
    )

    active_usher_memberships: DynamicMapped[List[ProjectCrewMembership]] = relationship(
        ProjectCrewMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectCrewMembership.project_id == Project.id,
            ProjectCrewMembership.is_active,
            ProjectCrewMembership.is_usher.is_(True),
        ),
        viewonly=True,
    )

    crew = DynamicAssociationProxy('active_crew_memberships', 'user')
    editors = DynamicAssociationProxy('active_editor_memberships', 'user')
    promoters = DynamicAssociationProxy('active_promoter_memberships', 'user')
    ushers = DynamicAssociationProxy('active_usher_memberships', 'user')


# Similarly for users (add as needs come up)
@reopen(User)
class __User:
    # pylint: disable=invalid-unary-operand-type

    # This relationship is only useful to check if the user has ever been a crew member.
    # Most operations will want to use one of the active membership relationships.
    projects_as_crew_memberships = relationship(
        ProjectCrewMembership,
        lazy='dynamic',
        foreign_keys=[ProjectCrewMembership.user_id],
        viewonly=True,
    )

    # This is used to determine if it is safe to purge the subject's database record
    projects_as_crew_noninvite_memberships = relationship(
        ProjectCrewMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectCrewMembership.user_id == User.id,
            ~ProjectCrewMembership.is_invite,
        ),
        viewonly=True,
    )
    projects_as_crew_active_memberships = relationship(
        ProjectCrewMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectCrewMembership.user_id == User.id,
            ProjectCrewMembership.is_active,
        ),
        viewonly=True,
    )

    projects_as_crew = DynamicAssociationProxy(
        'projects_as_crew_active_memberships', 'project'
    )

    projects_as_editor_active_memberships = relationship(
        ProjectCrewMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectCrewMembership.user_id == User.id,
            ProjectCrewMembership.is_active,
            ProjectCrewMembership.is_editor.is_(True),
        ),
        viewonly=True,
    )

    projects_as_editor = DynamicAssociationProxy(
        'projects_as_editor_active_memberships', 'project'
    )


User.__active_membership_attrs__.add('projects_as_crew_active_memberships')
User.__noninvite_membership_attrs__.add('projects_as_crew_noninvite_memberships')
