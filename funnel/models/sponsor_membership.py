"""Models for sponsors of a project or proposal (submission)."""

from __future__ import annotations

from typing import Set

from werkzeug.utils import cached_property

from coaster.sqlalchemy import DynamicAssociationProxy, immutable, with_roles

from . import db, sa
from .helpers import reopen
from .membership_mixin import (
    FrozenAttributionMixin,
    ImmutableProfileMembershipMixin,
    ReorderMembershipMixin,
)
from .profile import Profile
from .project import Project
from .proposal import Proposal

__all__ = ['ProjectSponsorMembership', 'ProposalSponsorMembership']


class ProjectSponsorMembership(  # type: ignore[misc]
    FrozenAttributionMixin,
    ReorderMembershipMixin,
    ImmutableProfileMembershipMixin,
    db.Model,  # type: ignore[name-defined]
):
    """Sponsor of a project."""

    __tablename__ = 'project_sponsor_membership'

    # List of data columns in this model that must be copied into revisions
    __data_columns__ = ('seq', 'is_promoted', 'label', 'title')

    __roles__ = {
        'all': {
            'read': {
                'is_promoted',
                'label',
                'profile',
                'project',
                'seq',
                'title',
                'urls',
            },
            'call': {'url_for'},
        },
    }
    __datasets__ = {
        'primary': {
            'is_promoted',
            'label',
            'offered_roles',
            'profile',
            'project',
            'seq',
            'title',
            'urls',
            'uuid_b58',
        },
        'without_parent': {
            'is_promoted',
            'label',
            'offered_roles',
            'profile',
            'seq',
            'title',
            'urls',
            'uuid_b58',
        },
        'related': {
            'is_promoted',
            'label',
            'offered_roles',
            'seq',
            'title',
            'urls',
            'uuid_b58',
        },
    }

    revoke_on_subject_delete = False

    project_id: sa.Column[int] = immutable(
        sa.Column(
            sa.Integer, sa.ForeignKey('project.id', ondelete='CASCADE'), nullable=False
        )
    )
    project: sa.orm.relationship[Project] = immutable(
        sa.orm.relationship(
            Project,
            backref=sa.orm.backref(
                'all_sponsor_memberships',
                lazy='dynamic',
                cascade='all',
                passive_deletes=True,
            ),
        )
    )
    parent = sa.orm.synonym('project')
    parent_id = sa.orm.synonym('project_id')

    #: Is this sponsor being promoted for commercial reasons? Projects may have a legal
    #: obligation to reveal this. This column records a declaration from the project.
    is_promoted = immutable(sa.Column(sa.Boolean, nullable=False))

    #: Optional label, indicating the type of sponsor
    label = immutable(
        sa.Column(
            sa.Unicode,
            sa.CheckConstraint(
                sa.column('label') != '', name='project_sponsor_membership_label_check'
            ),
            nullable=True,
        )
    )

    # This model does not offer a large text field for promotional messages, since
    # revision control on such a field is a distinct problem from membership
    # revisioning. The planned Page model can be used instead, with this model getting
    # a page id reference column whenever that model is ready.

    @cached_property
    def offered_roles(self) -> Set[str]:
        """Return empty set as this membership does not offer any roles on Project."""
        return set()


@reopen(Project)
class __Project:
    sponsor_memberships = with_roles(
        sa.orm.relationship(
            ProjectSponsorMembership,
            lazy='dynamic',
            primaryjoin=sa.and_(
                ProjectSponsorMembership.project_id == Project.id,
                ProjectSponsorMembership.is_active,  # type: ignore[arg-type]
            ),
            order_by=ProjectSponsorMembership.seq,
            viewonly=True,
        ),
        read={'all'},
    )

    @with_roles(read={'all'})
    @cached_property
    def has_sponsors(self):
        return db.session.query(self.sponsor_memberships.exists()).scalar()

    sponsors = DynamicAssociationProxy('sponsor_memberships', 'profile')


class ProposalSponsorMembership(  # type: ignore[misc]
    FrozenAttributionMixin,
    ReorderMembershipMixin,
    ImmutableProfileMembershipMixin,
    db.Model,  # type: ignore[name-defined]
):
    """Sponsor of a proposal."""

    __tablename__ = 'proposal_sponsor_membership'

    # List of data columns in this model that must be copied into revisions
    __data_columns__ = ('seq', 'is_promoted', 'label', 'title')

    __roles__ = {
        'all': {
            'read': {
                'is_promoted',
                'label',
                'profile',
                'proposal',
                'seq',
                'title',
                'urls',
            },
            'call': {'url_for'},
        }
    }
    __datasets__ = {
        'primary': {
            'is_promoted',
            'label',
            'offered_roles',
            'profile',
            'proposal',
            'seq',
            'title',
            'urls',
            'uuid_b58',
        },
        'without_parent': {
            'is_promoted',
            'label',
            'offered_roles',
            'profile',
            'seq',
            'title',
            'urls',
            'uuid_b58',
        },
        'related': {
            'is_promoted',
            'label',
            'offered_roles',
            'seq',
            'title',
            'urls',
            'uuid_b58',
        },
    }

    revoke_on_subject_delete = False

    proposal_id: sa.Column[int] = immutable(
        sa.Column(
            sa.Integer, sa.ForeignKey('proposal.id', ondelete='CASCADE'), nullable=False
        )
    )
    proposal: sa.orm.relationship[Proposal] = immutable(
        sa.orm.relationship(
            Proposal,
            backref=sa.orm.backref(
                'all_sponsor_memberships',
                lazy='dynamic',
                cascade='all',
                passive_deletes=True,
            ),
        )
    )
    parent = sa.orm.synonym('proposal')
    parent_id = sa.orm.synonym('proposal_id')

    #: Is this sponsor being promoted for commercial reasons? Proposals may have a legal
    #: obligation to reveal this. This column records a declaration from the proposal.
    is_promoted = immutable(sa.Column(sa.Boolean, nullable=False))

    #: Optional label, indicating the type of sponsor
    label = immutable(
        sa.Column(
            sa.Unicode,
            sa.CheckConstraint(
                sa.column('label') != '', name='proposal_sponsor_membership_label_check'
            ),
            nullable=True,
        )
    )

    @cached_property
    def offered_roles(self) -> Set[str]:
        """Return empty set as this membership does not offer any roles on Proposal."""
        return set()


@reopen(Proposal)
class __Proposal:
    sponsor_memberships = with_roles(
        sa.orm.relationship(
            ProposalSponsorMembership,
            lazy='dynamic',
            primaryjoin=sa.and_(
                ProposalSponsorMembership.proposal_id == Proposal.id,
                ProposalSponsorMembership.is_active,  # type: ignore[arg-type]
            ),
            order_by=ProposalSponsorMembership.seq,
            viewonly=True,
        ),
        read={'all'},
    )

    @with_roles(read={'all'})
    @cached_property
    def has_sponsors(self):
        return db.session.query(self.sponsor_memberships.exists()).scalar()

    sponsors = DynamicAssociationProxy('sponsor_memberships', 'profile')


@reopen(Profile)
class __Profile:
    # pylint: disable=invalid-unary-operand-type
    noninvite_project_sponsor_memberships = sa.orm.relationship(
        ProjectSponsorMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectSponsorMembership.profile_id == Profile.id,
            ~ProjectSponsorMembership.is_invite,  # type: ignore[operator]
        ),
        order_by=ProjectSponsorMembership.granted_at.desc(),
        viewonly=True,
    )

    project_sponsor_memberships = sa.orm.relationship(
        ProjectSponsorMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProjectSponsorMembership.profile_id == Profile.id,
            ProjectSponsorMembership.is_active,  # type: ignore[arg-type]
        ),
        order_by=ProjectSponsorMembership.granted_at.desc(),
        viewonly=True,
    )

    project_sponsor_membership_invites = with_roles(
        sa.orm.relationship(
            ProjectSponsorMembership,
            lazy='dynamic',
            primaryjoin=sa.and_(
                ProjectSponsorMembership.profile_id == Profile.id,
                ProjectSponsorMembership.is_invite,  # type: ignore[arg-type]
                ProjectSponsorMembership.revoked_at.is_(None),  # type: ignore[has-type]
            ),
            order_by=ProjectSponsorMembership.granted_at.desc(),
            viewonly=True,
        ),
        read={'admin'},
    )

    noninvite_proposal_sponsor_memberships = sa.orm.relationship(
        ProposalSponsorMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProposalSponsorMembership.profile_id == Profile.id,
            ~ProposalSponsorMembership.is_invite,  # type: ignore[operator]
        ),
        order_by=ProposalSponsorMembership.granted_at.desc(),
        viewonly=True,
    )

    proposal_sponsor_memberships = sa.orm.relationship(
        ProposalSponsorMembership,
        lazy='dynamic',
        primaryjoin=sa.and_(
            ProposalSponsorMembership.profile_id == Profile.id,
            ProposalSponsorMembership.is_active,  # type: ignore[arg-type]
        ),
        order_by=ProposalSponsorMembership.granted_at.desc(),
        viewonly=True,
    )

    proposal_sponsor_membership_invites = with_roles(
        sa.orm.relationship(
            ProposalSponsorMembership,
            lazy='dynamic',
            primaryjoin=sa.and_(
                ProposalSponsorMembership.profile_id == Profile.id,
                ProposalSponsorMembership.is_invite,  # type: ignore[arg-type]
                ProposalSponsorMembership.revoked_at.is_(  # type: ignore[has-type]
                    None
                ),
            ),
            order_by=ProposalSponsorMembership.granted_at.desc(),
            viewonly=True,
        ),
        read={'admin'},
    )

    sponsored_projects = DynamicAssociationProxy(
        'project_sponsor_memberships', 'project'
    )

    sponsored_proposals = DynamicAssociationProxy(
        'proposal_sponsor_memberships', 'proposal'
    )


Profile.__active_membership_attrs__.update(
    {'project_sponsor_memberships', 'proposal_sponsor_memberships'}
)
Profile.__noninvite_membership_attrs__.update(
    {'noninvite_project_sponsor_memberships', 'noninvite_proposal_sponsor_memberships'}
)
