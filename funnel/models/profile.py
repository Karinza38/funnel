"""Account (nee Profile) model, linked to a User or Organization model."""

from __future__ import annotations

from typing import Iterable, List, Optional, Union
from uuid import UUID  # noqa: F401 # pylint: disable=unused-import

from sqlalchemy.sql import expression

from furl import furl

from baseframe import __
from coaster.sqlalchemy import LazyRoleSet, Query, StateManager, immutable, with_roles
from coaster.utils import LabeledEnum

from ..typing import OptionalMigratedTables
from . import (
    BaseMixin,
    Mapped,
    MarkdownCompositeDocument,
    TSVectorType,
    UrlType,
    UuidMixin,
    db,
    hybrid_property,
    sa,
)
from .helpers import (
    RESERVED_NAMES,
    ImgeeFurl,
    ImgeeType,
    add_search_trigger,
    quote_autocomplete_tsquery,
    valid_username,
    visual_field_delimiter,
)
from .user import EnumerateMembershipsMixin, Organization, User
from .utils import do_migrate_instances

__all__ = ['Profile']


class PROFILE_STATE(LabeledEnum):  # noqa: N801
    """The visibility state of an account (auto/public/private)."""

    AUTO = (1, 'auto', __("Autogenerated"))
    PUBLIC = (2, 'public', __("Public"))
    PRIVATE = (3, 'private', __("Private"))

    NOT_PUBLIC = {AUTO, PRIVATE}
    NOT_PRIVATE = {AUTO, PUBLIC}


# This model does not use BaseNameMixin because it has no title column. The title comes
# from the linked User or Organization
class Profile(
    EnumerateMembershipsMixin,
    UuidMixin,
    BaseMixin,
    db.Model,  # type: ignore[name-defined]
):
    """
    Consolidated account for :class:`User` and :class:`Organization` models.

    Accounts (nee Profiles) hold the account name in a shared namespace between these
    models (aka "username"), and also host projects and other future document types.
    """

    __tablename__ = 'profile'
    __allow_unmapped__ = True
    __uuid_primary_key__ = False
    # length limit 63 to fit DNS label limit
    __name_length__ = 63
    reserved_names = RESERVED_NAMES

    #: The "username" assigned to a user or organization.
    #: Length limit 63 to fit DNS label limit
    name = sa.Column(
        sa.Unicode(__name_length__),
        sa.CheckConstraint("name <> ''"),
        nullable=False,
        unique=True,
    )
    # Only one of the following three may be set:
    #: User that owns this name (limit one per user)
    user_id = sa.Column(
        sa.Integer,
        sa.ForeignKey('user.id', ondelete='SET NULL'),
        unique=True,
        nullable=True,
    )

    # No `cascade='delete-orphan'` in User and Organization backrefs as accounts cannot
    # be trivially deleted

    user: Mapped[Optional[User]] = with_roles(
        sa.orm.relationship(
            'User',
            backref=sa.orm.backref('profile', uselist=False, cascade='all'),
        ),
        grants={'owner'},
    )
    #: Organization that owns this name (limit one per organization)
    organization_id = sa.Column(
        sa.Integer,
        sa.ForeignKey('organization.id', ondelete='SET NULL'),
        unique=True,
        nullable=True,
    )
    organization: Mapped[Optional[Organization]] = sa.orm.relationship(
        'Organization',
        backref=sa.orm.backref('profile', uselist=False, cascade='all'),
    )
    #: Reserved account (not assigned to any party)
    reserved = sa.Column(sa.Boolean, nullable=False, default=False, index=True)

    _state = sa.Column(
        'state',
        sa.Integer,
        StateManager.check_constraint('state', PROFILE_STATE),
        nullable=False,
        default=PROFILE_STATE.AUTO,
    )
    state = StateManager(
        '_state', PROFILE_STATE, doc="Current state of the account page"
    )

    tagline = sa.Column(sa.Unicode, nullable=True)
    description = MarkdownCompositeDocument.create(
        'description', default='', nullable=False
    )
    website: Mapped[Optional[furl]] = sa.Column(UrlType, nullable=True)
    logo_url: Mapped[Optional[ImgeeFurl]] = sa.Column(ImgeeType, nullable=True)
    banner_image_url: Mapped[Optional[ImgeeFurl]] = sa.Column(ImgeeType, nullable=True)

    # These two flags are read-only. There is no provision for writing to them within
    # the app:

    #: Protected accounts cannot be deleted
    is_protected = with_roles(
        immutable(sa.Column(sa.Boolean, default=False, nullable=False)),
        read={'owner', 'admin'},
    )
    #: Verified accounts get listed on the home page and are not considered throwaway
    #: accounts for spam control. There are no other privileges at this time
    is_verified = with_roles(
        immutable(sa.Column(sa.Boolean, default=False, nullable=False, index=True)),
        read={'all'},
    )

    #: Revision number maintained by SQLAlchemy, starting at 1
    revisionid = with_roles(sa.Column(sa.Integer, nullable=False), read={'all'})

    search_vector: Mapped[TSVectorType] = sa.orm.deferred(
        sa.Column(
            TSVectorType(
                'name',
                'description_text',
                weights={'name': 'A', 'description_text': 'B'},
                regconfig='english',
                hltext=lambda: sa.func.concat_ws(
                    visual_field_delimiter, Profile.name, Profile.description_html
                ),
            ),
            nullable=False,
        )
    )

    is_active = with_roles(
        sa.orm.column_property(
            sa.case(
                (
                    user_id.isnot(None),  # ← when, ↙ then
                    sa.select(User.state.ACTIVE)  # type: ignore[has-type]
                    .where(User.id == user_id)
                    .correlate_except(User)  # type: ignore[arg-type]
                    .scalar_subquery(),
                ),
                (
                    organization_id.isnot(None),  # ← when, ↙ then
                    sa.select(Organization.state.ACTIVE)  # type: ignore[has-type]
                    .where(Organization.id == organization_id)
                    .correlate_except(Organization)  # type: ignore[arg-type]
                    .scalar_subquery(),
                ),
                else_=expression.false(),
            )
        ),
        read={'all'},
        datasets={'primary', 'related'},
    )

    __table_args__ = (
        sa.CheckConstraint(
            sa.case((user_id.isnot(None), 1), else_=0)
            + sa.case((organization_id.isnot(None), 1), else_=0)
            + sa.case((reserved.is_(True), 1), else_=0)
            == 1,
            name='profile_owner_check',
        ),
        sa.Index(
            'ix_profile_name_lower',
            sa.func.lower(name).label('name_lower'),
            unique=True,
            postgresql_ops={'name_lower': 'varchar_pattern_ops'},
        ),
        sa.Index('ix_profile_search_vector', 'search_vector', postgresql_using='gin'),
    )

    __mapper_args__ = {'version_id_col': revisionid}

    __roles__ = {
        'all': {
            'read': {
                'urls',
                'uuid_b58',
                'name',
                'title',
                'description',
                'website',
                'logo_url',
                'user',
                'organization',
                'banner_image_url',
                'is_organization_profile',
                'is_user_profile',
                'owner',
            },
            'call': {'url_for', 'features', 'forms', 'state', 'views'},
        }
    }

    __datasets__ = {
        'primary': {
            'urls',
            'uuid_b58',
            'name',
            'title',
            'description',
            'logo_url',
            'website',
            'user',
            'organization',
            'owner',
            'is_verified',
        },
        'related': {
            'urls',
            'uuid_b58',
            'name',
            'title',
            'description',
            'logo_url',
            'is_verified',
        },
    }

    state.add_conditional_state(
        'ACTIVE_AND_PUBLIC', state.PUBLIC, lambda profile: profile.is_active
    )

    def __repr__(self) -> str:
        """Represent :class:`Profile` as a string."""
        return f'<Profile "{self.name}">'

    @property
    def owner(self) -> Union[User, Organization]:
        """Return the user or organization that owns this account."""
        return self.user or self.organization

    @owner.setter
    def owner(self, value: Union[User, Organization]) -> None:
        if isinstance(value, User):
            self.user = value
            self.organization = None
        elif isinstance(value, Organization):
            self.user = None
            self.organization = value
        else:
            raise ValueError(value)
        self.reserved = False

    @hybrid_property
    def is_user_profile(self) -> bool:
        """Test if this is a user account."""
        return self.user_id is not None

    @is_user_profile.expression
    def is_user_profile(cls):  # noqa: N805  # pylint: disable=no-self-argument
        """Test if this is a user account in a SQL expression."""
        return cls.user_id.isnot(None)

    @hybrid_property
    def is_organization_profile(self) -> bool:
        """Test if this is an organization account."""
        return self.organization_id is not None

    @is_organization_profile.expression
    def is_organization_profile(cls):  # noqa: N805  # pylint: disable=no-self-argument
        """Test if this is an organization account in a SQL expression."""
        return cls.organization_id.isnot(None)

    @property
    def is_public(self) -> bool:
        """Test if this account is public."""
        return bool(self.state.PUBLIC)

    with_roles(is_public, read={'all'})

    @hybrid_property
    def title(self) -> str:
        if self.user:
            return self.user.fullname
        if self.organization:
            return self.organization.title
        return ''

    @title.setter
    def title(self, value: str) -> None:
        if self.user:
            self.user.fullname = value
        elif self.organization:
            self.organization.title = value
        else:
            raise ValueError("Reserved accounts do not have titles")

    @title.expression
    def title(cls):  # noqa: N805  # pylint: disable=no-self-argument
        return sa.case(
            (
                # if...
                cls.user_id.isnot(None),
                # then...
                sa.select(User.fullname).where(cls.user_id == User.id).as_scalar(),
            ),
            (
                # elif...
                cls.organization_id.isnot(None),
                # then...
                sa.select(Organization.title)
                .where(cls.organization_id == Organization.id)
                .as_scalar(),
            ),
            else_='',
        )

    @property
    def pickername(self) -> str:
        if self.user:
            return self.user.pickername
        if self.organization:
            return self.organization.pickername
        return self.title

    def roles_for(
        self, actor: Optional[User] = None, anchors: Iterable = ()
    ) -> LazyRoleSet:
        if self.owner:
            roles = self.owner.roles_for(actor, anchors)
        else:
            roles = super().roles_for(actor, anchors)
        if self.state.PUBLIC:
            roles.add('reader')
        return roles

    @classmethod
    def get(cls, name: str) -> Optional[Profile]:
        return cls.query.filter(
            sa.func.lower(Profile.name) == sa.func.lower(name)
        ).one_or_none()

    @classmethod
    def all_public(cls) -> Query:
        return cls.query.filter(cls.state.PUBLIC)

    @classmethod
    def validate_name_candidate(cls, name: str) -> Optional[str]:
        """
        Validate an account name candidate.

        Returns one of several error codes, or `None` if all is okay:

        * ``blank``: No name supplied
        * ``reserved``: Name is reserved
        * ``invalid``: Invalid characters in name
        * ``long``: Name is longer than allowed size
        * ``user``: Name is assigned to a user
        * ``org``: Name is assigned to an organization
        """
        if not name:
            return 'blank'
        if name.lower() in cls.reserved_names:
            return 'reserved'
        if not valid_username(name):
            return 'invalid'
        if len(name) > cls.__name_length__:
            return 'long'
        existing = (
            cls.query.filter(sa.func.lower(cls.name) == sa.func.lower(name))
            .options(
                sa.orm.load_only(
                    cls.id, cls.uuid, cls.user_id, cls.organization_id, cls.reserved
                )
            )
            .one_or_none()
        )
        if existing is not None:
            if existing.reserved:
                return 'reserved'
            if existing.user_id:
                return 'user'
            if existing.organization_id:
                return 'org'
        return None

    @classmethod
    def is_available_name(cls, name: str) -> bool:
        return cls.validate_name_candidate(name) is None

    @sa.orm.validates('name')
    def validate_name(self, key: str, value: str):
        if value.lower() in self.reserved_names or not valid_username(value):
            raise ValueError("Invalid account name: " + value)
        # We don't check for existence in the db since this validator only
        # checks for valid syntax. To confirm the name is actually available,
        # the caller must call :meth:`is_available_name` or attempt to commit
        # to the db and catch IntegrityError.
        return value

    @classmethod
    def migrate_user(  # type: ignore[return]
        cls, old_user: User, new_user: User
    ) -> OptionalMigratedTables:
        """Migrate one user account to another when merging user accounts."""
        if old_user.profile is not None and new_user.profile is None:
            # New user doesn't have an account (nee profile). Simply transfer ownership
            new_user.profile = old_user.profile
        elif old_user.profile is not None and new_user.profile is not None:
            # Both have accounts. Move everything that refers to old account
            done = do_migrate_instances(
                old_user.profile, new_user.profile, 'migrate_profile'
            )
            if done:
                db.session.delete(old_user.profile)
        # Do nothing if old_user.profile is None and new_user.profile is not None

    @property
    def teams(self) -> List:
        if self.organization:
            return self.organization.teams
        return []

    @with_roles(call={'owner'})
    @state.transition(
        state.NOT_PUBLIC,
        state.PUBLIC,
        title=__("Make public"),
        if_=lambda profile: (
            profile.reserved is False
            and profile.is_active
            and (profile.user is None or profile.user.features.not_likely_throwaway)
        ),
    )
    def make_public(self) -> None:
        """Make an account public if it is eligible."""

    @with_roles(call={'owner'})
    @state.transition(state.NOT_PRIVATE, state.PRIVATE, title=__("Make private"))
    def make_private(self) -> None:
        """Make an account private."""

    def is_safe_to_delete(self) -> bool:
        """Test if account is not protected and has no projects."""
        return self.is_protected is False and self.projects.count() == 0

    def is_safe_to_purge(self) -> bool:
        """Test if account is safe to delete and has no memberships (active or not)."""
        return self.is_safe_to_delete() and not self.has_any_memberships()

    def do_delete(self, actor: User) -> bool:
        """Delete contents of this account."""
        if self.is_safe_to_delete():
            for membership in self.active_memberships():
                membership = membership.freeze_subject_attribution(actor)
                if membership.revoke_on_subject_delete:
                    membership.revoke(actor=actor)
            return True
        return False

    @classmethod
    def autocomplete(cls, prefix: str) -> List[Profile]:
        """Return accounts beginning with the query, for autocomplete."""
        prefix = prefix.strip()
        if not prefix:
            return []
        tsquery = quote_autocomplete_tsquery(prefix)
        return (
            cls.query.options(sa.orm.defer(cls.is_active))
            .join(User)
            .filter(
                User.state.ACTIVE,
                sa.or_(
                    cls.search_vector.bool_op('@@')(tsquery),
                    User.search_vector.bool_op('@@')(tsquery),
                ),
            )
            .union(
                cls.query.options(sa.orm.defer(cls.is_active))
                .join(Organization)
                .filter(
                    Organization.state.ACTIVE,
                    sa.or_(
                        cls.search_vector.bool_op('@@')(tsquery),
                        Organization.search_vector.bool_op('@@')(tsquery),
                    ),
                ),
            )
            .order_by(cls.name)
            .all()
        )


add_search_trigger(Profile, 'search_vector')
