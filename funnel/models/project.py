"""Project model."""

from __future__ import annotations

from typing import Iterable, List, Optional

from pytz import utc
from sqlalchemy.orm import attribute_keyed_dict
from werkzeug.utils import cached_property

from baseframe import __, localize_timezone
from coaster.sqlalchemy import LazyRoleSet, StateManager, with_roles
from coaster.utils import LabeledEnum, buid, utcnow

from .. import app
from ..typing import OptionalMigratedTables
from . import (
    BaseScopedNameMixin,
    Mapped,
    MarkdownCompositeDocument,
    TimestampMixin,
    TimezoneType,
    TSVectorType,
    UrlType,
    UuidMixin,
    db,
    json_type,
    sa,
)
from .comment import SET_TYPE, Commentset
from .helpers import (
    RESERVED_NAMES,
    ImgeeType,
    add_search_trigger,
    reopen,
    valid_name,
    visual_field_delimiter,
)
from .profile import Profile
from .user import User

__all__ = ['Project', 'ProjectLocation', 'ProjectRedirect']


# --- Constants ---------------------------------------------------------------


class PROJECT_STATE(LabeledEnum):  # noqa: N801
    DRAFT = (1, 'draft', __("Draft"))
    PUBLISHED = (2, 'published', __("Published"))
    WITHDRAWN = (3, 'withdrawn', __("Withdrawn"))
    DELETED = (4, 'deleted', __("Deleted"))
    DELETABLE = {DRAFT, PUBLISHED, WITHDRAWN}
    PUBLISHABLE = {DRAFT, WITHDRAWN}


class CFP_STATE(LabeledEnum):  # noqa: N801
    NONE = (1, 'none', __("None"))
    PUBLIC = (2, 'public', __("Public"))
    CLOSED = (3, 'closed', __("Closed"))
    ANY = {NONE, PUBLIC, CLOSED}


# --- Models ------------------------------------------------------------------


class Project(UuidMixin, BaseScopedNameMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'project'
    __allow_unmapped__ = True
    reserved_names = RESERVED_NAMES

    user_id = sa.Column(sa.Integer, sa.ForeignKey('user.id'), nullable=False)
    user: Mapped[User] = sa.orm.relationship(
        User,
        foreign_keys=[user_id],
        backref=sa.orm.backref('projects', cascade='all'),
    )
    profile_id = sa.Column(sa.Integer, sa.ForeignKey('profile.id'), nullable=False)
    profile: Mapped[Profile] = with_roles(
        sa.orm.relationship(
            Profile, backref=sa.orm.backref('projects', cascade='all', lazy='dynamic')
        ),
        read={'all'},
        # If account grants an 'admin' role, make it 'profile_admin' here
        grants_via={None: {'admin': 'profile_admin'}},
        # `profile` only appears in the 'primary' dataset. It must not be included in
        # 'related' or 'without_parent' as it is the parent
        datasets={'primary'},
    )
    parent: Mapped[Profile] = sa.orm.synonym('profile')
    tagline: Mapped[str] = with_roles(
        sa.Column(sa.Unicode(250), nullable=False),
        read={'all'},
        datasets={'primary', 'without_parent', 'related'},
    )
    description = with_roles(
        MarkdownCompositeDocument.create('description', default='', nullable=False),
        read={'all'},
    )
    instructions = with_roles(
        MarkdownCompositeDocument.create('instructions', default='', nullable=True),
        read={'all'},
    )

    location = with_roles(
        sa.Column(sa.Unicode(50), default='', nullable=True),
        read={'all'},
        datasets={'primary', 'without_parent', 'related'},
    )
    parsed_location = sa.Column(json_type, nullable=False, server_default='{}')

    website = with_roles(
        sa.Column(UrlType, nullable=True),
        read={'all'},
        datasets={'primary', 'without_parent'},
    )
    timezone = with_roles(
        sa.Column(TimezoneType(backend='pytz'), nullable=False, default=utc),
        read={'all'},
        datasets={'primary', 'without_parent', 'related'},
    )

    _state = sa.Column(
        'state',
        sa.Integer,
        StateManager.check_constraint('state', PROJECT_STATE),
        default=PROJECT_STATE.DRAFT,
        nullable=False,
        index=True,
    )
    state = with_roles(
        StateManager('_state', PROJECT_STATE, doc="Project state"), call={'all'}
    )
    _cfp_state = sa.Column(
        'cfp_state',
        sa.Integer,
        StateManager.check_constraint('cfp_state', CFP_STATE),
        default=CFP_STATE.NONE,
        nullable=False,
        index=True,
    )
    cfp_state = with_roles(
        StateManager('_cfp_state', CFP_STATE, doc="CfP state"), call={'all'}
    )

    #: Audit timestamp to detect re-publishing to re-surface a project
    first_published_at = sa.Column(sa.TIMESTAMP(timezone=True), nullable=True)
    #: Timestamp of when this project was most recently published
    published_at = with_roles(
        sa.Column(sa.TIMESTAMP(timezone=True), nullable=True, index=True),
        read={'all'},
        write={'promoter'},
        datasets={'primary', 'without_parent', 'related'},
    )
    #: Optional start time for schedule, cached from column property schedule_start_at
    start_at = with_roles(
        sa.Column(sa.TIMESTAMP(timezone=True), nullable=True, index=True),
        read={'all'},
        write={'editor'},
        datasets={'primary', 'without_parent', 'related'},
    )
    #: Optional end time for schedule, cached from column property schedule_end_at
    end_at = with_roles(
        sa.Column(sa.TIMESTAMP(timezone=True), nullable=True, index=True),
        read={'all'},
        write={'editor'},
        datasets={'primary', 'without_parent', 'related'},
    )

    cfp_start_at = sa.Column(sa.TIMESTAMP(timezone=True), nullable=True, index=True)
    cfp_end_at = sa.Column(sa.TIMESTAMP(timezone=True), nullable=True, index=True)

    bg_image = with_roles(
        sa.Column(ImgeeType, nullable=True),
        read={'all'},
        datasets={'primary', 'without_parent', 'related'},
    )
    allow_rsvp: Mapped[bool] = with_roles(
        sa.Column(sa.Boolean, default=True, nullable=False),
        read={'all'},
        datasets={'primary', 'without_parent', 'related'},
    )
    buy_tickets_url: Mapped[Optional[str]] = with_roles(
        sa.Column(UrlType, nullable=True),
        read={'all'},
        datasets={'primary', 'without_parent', 'related'},
    )

    banner_video_url = with_roles(
        sa.Column(UrlType, nullable=True),
        read={'all'},
        datasets={'primary', 'without_parent'},
    )
    boxoffice_data = with_roles(
        sa.Column(json_type, nullable=False, server_default='{}'),
        # This is an attribute, but we deliberately use `call` instead of `read` to
        # block this from dictionary enumeration. FIXME: Break up this dictionary into
        # individual columns with `all` access for ticket embed id and `promoter`
        # access for ticket sync access token.
        call={'all'},
    )

    hasjob_embed_url = with_roles(sa.Column(UrlType, nullable=True), read={'all'})
    hasjob_embed_limit = with_roles(sa.Column(sa.Integer, default=8), read={'all'})

    commentset_id = sa.Column(
        sa.Integer, sa.ForeignKey('commentset.id'), nullable=False
    )
    commentset: Mapped[Commentset] = sa.orm.relationship(
        Commentset,
        uselist=False,
        cascade='all',
        single_parent=True,
        back_populates='project',
    )

    parent_id = sa.Column(
        sa.Integer, sa.ForeignKey('project.id', ondelete='SET NULL'), nullable=True
    )
    parent_project: Mapped[Optional[Project]] = sa.orm.relationship(
        'Project', remote_side='Project.id', backref='subprojects'
    )

    #: Featured project flag. This can only be set by website editors, not
    #: project editors or account admins.
    site_featured = with_roles(
        sa.Column(sa.Boolean, default=False, nullable=False),
        read={'all'},
        write={'site_editor'},
        datasets={'primary', 'without_parent'},
    )

    #: Revision number maintained by SQLAlchemy, used for vCal files, starting at 1
    revisionid = with_roles(sa.Column(sa.Integer, nullable=False), read={'all'})

    search_vector: Mapped[TSVectorType] = sa.orm.deferred(
        sa.Column(
            TSVectorType(
                'name',
                'title',
                'description_text',
                'instructions_text',
                'location',
                weights={
                    'name': 'A',
                    'title': 'A',
                    'description_text': 'B',
                    'instructions_text': 'B',
                    'location': 'C',
                },
                regconfig='english',
                hltext=lambda: sa.func.concat_ws(
                    visual_field_delimiter,
                    Project.title,
                    Project.location,
                    Project.description_html,
                    Project.instructions_html,
                ),
            ),
            nullable=False,
        )
    )

    livestream_urls = with_roles(
        sa.Column(sa.ARRAY(sa.UnicodeText, dimensions=1), server_default='{}'),
        read={'all'},
        datasets={'primary', 'without_parent'},
    )

    __table_args__ = (
        sa.UniqueConstraint('profile_id', 'name'),
        sa.Index('ix_project_search_vector', 'search_vector', postgresql_using='gin'),
        sa.CheckConstraint(
            sa.or_(  # type: ignore[arg-type]
                sa.and_(start_at.is_(None), end_at.is_(None)),
                sa.and_(start_at.isnot(None), end_at.isnot(None), end_at > start_at),
            ),
            'project_start_at_end_at_check',
        ),
        sa.CheckConstraint(
            sa.or_(  # type: ignore[arg-type]
                sa.and_(cfp_start_at.is_(None), cfp_end_at.is_(None)),
                sa.and_(cfp_start_at.isnot(None), cfp_end_at.is_(None)),
                sa.and_(
                    cfp_start_at.isnot(None),
                    cfp_end_at.isnot(None),
                    cfp_end_at > cfp_start_at,
                ),
            ),
            'project_cfp_start_at_cfp_end_at_check',
        ),
    )

    __mapper_args__ = {'version_id_col': revisionid}

    __roles__ = {
        'all': {
            'read': {
                'absolute_url',  # From UrlForMixin
                'name',  # From BaseScopedNameMixin
                'short_title',  # From BaseScopedNameMixin
                'title',  # From BaseScopedNameMixin
                'urls',  # From UrlForMixin
                'created_at',  # From TimestampMixin, used for ical render timestamp
                'updated_at',  # From TimestampMixin, used for ical render timestamp
            },
            'call': {
                'features',  # From RegistryMixin
                'forms',  # From RegistryMixin
                'url_for',  # From UrlForMixin
                'view_for',  # From UrlForMixin
                'views',  # From RegistryMixin
            },
        },
    }

    __datasets__ = {
        'primary': {
            'absolute_url',  # From UrlForMixin
            'name',  # From BaseScopedNameMixin
            'title',  # From BaseScopedNameMixin
            'urls',  # From UrlForMixin
        },
        'without_parent': {
            'absolute_url',  # From UrlForMixin
            'name',  # From BaseScopedNameMixin
            'title',  # From BaseScopedNameMixin
        },
        'related': {
            'absolute_url',  # From UrlForMixin
            'name',  # From BaseScopedNameMixin
            'title',  # From BaseScopedNameMixin
        },
    }

    state.add_conditional_state(
        'PAST',
        state.PUBLISHED,
        lambda project: project.end_at is not None and utcnow() >= project.end_at,
        lambda project: sa.func.utcnow() >= project.end_at,
        label=('past', __("Past")),
    )
    state.add_conditional_state(
        'LIVE',
        state.PUBLISHED,
        lambda project: (
            project.start_at is not None
            and project.start_at <= utcnow() < project.end_at
        ),
        lambda project: sa.and_(
            project.start_at <= sa.func.utcnow(),
            sa.func.utcnow() < project.end_at,
        ),
        label=('live', __("Live")),
    )
    state.add_conditional_state(
        'UPCOMING',
        state.PUBLISHED,
        lambda project: project.start_at is not None and utcnow() < project.start_at,
        lambda project: sa.func.utcnow() < project.start_at,
        label=('upcoming', __("Upcoming")),
    )
    state.add_conditional_state(
        'PUBLISHED_WITHOUT_SESSIONS',
        state.PUBLISHED,
        lambda project: project.start_at is None,
        lambda project: project.start_at.is_(None),
        label=('published_without_sessions', __("Published without sessions")),
    )

    cfp_state.add_conditional_state(
        'HAS_PROPOSALS',
        cfp_state.ANY,
        lambda project: db.session.query(  # type: ignore[has-type]
            project.proposals.exists()
        ).scalar(),
        label=('has_proposals', __("Has submissions")),
    )
    cfp_state.add_conditional_state(
        'HAS_SESSIONS',
        cfp_state.ANY,
        lambda project: db.session.query(  # type: ignore[has-type]
            project.sessions.exists()
        ).scalar(),
        label=('has_sessions', __("Has sessions")),
    )
    cfp_state.add_conditional_state(
        'DRAFT',
        cfp_state.NONE,
        lambda project: project.instructions_html != '',
        lambda project: sa.and_(
            project.instructions_html.isnot(None), project.instructions_html != ''
        ),
        label=('draft', __("Draft")),
    )
    cfp_state.add_conditional_state(
        'OPEN',
        cfp_state.PUBLIC,
        lambda project: project.cfp_end_at is None or (utcnow() < project.cfp_end_at),
        lambda project: sa.or_(
            project.cfp_end_at.is_(None), sa.func.utcnow() < project.cfp_end_at
        ),
        label=('open', __("Open")),
    )
    cfp_state.add_conditional_state(
        'EXPIRED',
        cfp_state.PUBLIC,
        lambda project: project.cfp_end_at is not None
        and utcnow() >= project.cfp_end_at,
        lambda project: sa.and_(
            project.cfp_end_at.isnot(None), sa.func.utcnow() >= project.cfp_end_at
        ),
        label=('expired', __("Expired")),
    )

    cfp_state.add_state_group(
        'OPENABLE',
        cfp_state.CLOSED,
        cfp_state.NONE,
        cfp_state.EXPIRED,
    )
    cfp_state.add_state_group(
        'UNAVAILABLE',
        cfp_state.CLOSED,
        cfp_state.EXPIRED,
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.commentset = Commentset(settype=SET_TYPE.PROJECT)
        # Add the creator as editor and promoter
        new_membership = ProjectCrewMembership(
            parent=self,
            user=self.user,
            granted_by=self.user,
            is_editor=True,
            is_promoter=True,
        )
        db.session.add(new_membership)

    def __repr__(self) -> str:
        """Represent :class:`Project` as a string."""
        return f'<Project {self.profile.name}/{self.name} "{self.title}">'

    @with_roles(call={'editor'})
    @cfp_state.transition(
        cfp_state.OPENABLE,
        cfp_state.PUBLIC,
        title=__("Enable submissions"),
        message=__("Submissions will be accepted until the optional closing date"),
        type='success',
    )
    def open_cfp(self):
        """Change state to accept submissions."""
        # If closing date is in the past, remove it
        if self.cfp_end_at is not None and self.cfp_end_at <= utcnow():
            self.cfp_end_at = None
        # If opening date is not set, set it
        if self.cfp_start_at is None:
            self.cfp_start_at = sa.func.utcnow()

    @with_roles(call={'editor'})  # skipcq: PTC-W0049
    @cfp_state.transition(
        cfp_state.PUBLIC,
        cfp_state.CLOSED,
        title=__("Disable submissions"),
        message=__("Submissions will no longer be accepted"),
        type='success',
    )
    def close_cfp(self):
        """Change state to not accept submissions."""

    @with_roles(call={'editor'})
    @state.transition(
        state.PUBLISHABLE,
        state.PUBLISHED,
        title=__("Publish project"),
        message=__("The project has been published"),
        type='success',
    )
    def publish(self) -> bool:
        """Publish a project and return a flag if this is the first publishing."""
        first_published = False
        if not self.first_published_at:
            self.first_published_at = sa.func.utcnow()
            first_published = True
        self.published_at = sa.func.utcnow()
        return first_published

    @with_roles(call={'editor'})  # skipcq: PTC-W0049
    @state.transition(
        state.PUBLISHED,
        state.WITHDRAWN,
        title=__("Withdraw project"),
        message=__("The project has been withdrawn and is no longer listed"),
        type='success',
    )
    def withdraw(self):
        """Withdraw a project."""

    @property
    def title_inline(self) -> str:
        """Suffix a colon if the title does not end in ASCII sentence punctuation."""
        if self.title and self.tagline:
            # pylint: disable=unsubscriptable-object
            if self.title[-1] not in ('?', '!', ':', ';', '.', ','):
                return self.title + ':'
        return self.title

    with_roles(title_inline, read={'all'}, datasets={'primary', 'without_parent'})

    @property
    def title_suffix(self) -> str:
        """
        Return the profile's title if the project's title doesn't derive from it.

        Used in HTML title tags to render <title>{{ project }} - {{ suffix }}</title>.
        """
        if not self.title.startswith(self.parent.title):
            return self.profile.title
        return ''

    with_roles(title_suffix, read={'all'})

    @property
    def title_parts(self) -> List[str]:
        """
        Return the hierarchy of titles of this project.

        If the project's title is an extension of the account's title, only the
        project's title is returned as a single list item. If they are distinct, both
        are returned.

        This list is used by :prop:`joined_title` to produce a slash-separated title,
        but can be used directly when another rendering is required.
        """
        if self.short_title == self.title:
            # Project title does not derive from account title, so use both
            return [self.profile.title, self.title]
        # Project title extends account title, so account title is not needed
        return [self.title]

    with_roles(title_parts, read={'all'})

    @property
    def joined_title(self) -> str:
        """Return the project's title joined with the account's title, if divergent."""
        return ' / '.join(self.title_parts)

    with_roles(
        joined_title, read={'all'}, datasets={'primary', 'without_parent', 'related'}
    )

    @with_roles(read={'all'}, datasets={'primary', 'without_parent', 'related'})
    @cached_property
    def datelocation(self) -> str:
        """
        Return a date and location string for the project.

        The format depends on project dates:

        1. If it's a single day event:
            > 11 Feb 2018, Bangalore

        2. If multi-day event in same month:
            > 09–12 Feb 2018, Bangalore

        3. If multi-day event across months:
            > 27 Feb–02 Mar 2018, Bangalore

        4. If multi-day event across years:
            > 30 Dec 2018–02 Jan 2019, Bangalore
        """
        # FIXME: Replace strftime with Babel formatting
        daterange = ''
        if self.start_at is not None and self.end_at is not None:
            schedule_start_at_date = self.start_at_localized.date()
            schedule_end_at_date = self.end_at_localized.date()
            daterange_format = '{start_date}–{end_date} {year}'
            if schedule_start_at_date == schedule_end_at_date:
                # if both dates are same, in case of single day project
                strf_date = ''
                daterange_format = '{end_date} {year}'
            elif schedule_start_at_date.year != schedule_end_at_date.year:
                # if the start date and end dates are in different years,
                strf_date = '%d %b %Y'
            elif schedule_start_at_date.month != schedule_end_at_date.month:
                # If multi-day event across months
                strf_date = '%d %b'
            elif schedule_start_at_date.month == schedule_end_at_date.month:
                # If multi-day event in same month
                strf_date = '%d'
            daterange = daterange_format.format(
                start_date=schedule_start_at_date.strftime(strf_date),
                end_date=schedule_end_at_date.strftime('%d %b'),
                year=schedule_end_at_date.year,
            )
        return ', '.join([_f for _f in [daterange, self.location] if _f])

    # TODO: Removing Delete feature till we figure out siteadmin feature
    # @with_roles(call={'editor'})
    # @state.transition(
    #     state.DELETABLE, state.DELETED, title=__("Delete project"),
    #     message=__("The project has been deleted"), type='success')
    # def delete(self):
    #     pass

    @sa.orm.validates('name', 'profile')
    def _validate_and_create_redirect(self, key, value):
        # TODO: When labels, venues and other resources are relocated from project to
        # account, this validator can no longer watch for `profile` change. We'll need a
        # more elaborate transfer mechanism that remaps resources to equivalent ones in
        # the new `profile`.
        if key == 'name':
            value = value.strip() if value is not None else None
        if not value or (key == 'name' and not valid_name(value)):
            raise ValueError(f"Invalid value for {key}: {value!r}")
        existing_value = getattr(self, key)
        if value != existing_value and existing_value is not None:
            ProjectRedirect.add(self)
        return value

    @with_roles(read={'all'}, datasets={'primary', 'without_parent'})
    @cached_property
    def cfp_start_at_localized(self):
        return (
            localize_timezone(self.cfp_start_at, tz=self.timezone)
            if self.cfp_start_at
            else None
        )

    @with_roles(read={'all'}, datasets={'primary', 'without_parent'})
    @cached_property
    def cfp_end_at_localized(self):
        return (
            localize_timezone(self.cfp_end_at, tz=self.timezone)
            if self.cfp_end_at
            else None
        )

    @with_roles(read={'all'}, datasets={'primary', 'without_parent'})
    @cached_property
    def start_at_localized(self):
        """Return localized start_at timestamp."""
        return (
            localize_timezone(self.start_at, tz=self.timezone)
            if self.start_at
            else None
        )

    @with_roles(read={'all'}, datasets={'primary', 'without_parent'})
    @cached_property
    def end_at_localized(self):
        """Return localized end_at timestamp."""
        return localize_timezone(self.end_at, tz=self.timezone) if self.end_at else None

    def update_schedule_timestamps(self):
        """Update cached timestamps from sessions."""
        self.start_at = self.schedule_start_at
        self.end_at = self.schedule_end_at

    def roles_for(
        self, actor: Optional[User] = None, anchors: Iterable = ()
    ) -> LazyRoleSet:
        roles = super().roles_for(actor, anchors)
        # https://github.com/hasgeek/funnel/pull/220#discussion_r168718052
        roles.add('reader')
        return roles

    def is_safe_to_delete(self) -> bool:
        """Return True if project has no proposals."""
        return self.proposals.count() == 0

    @classmethod
    def order_by_date(cls):
        """
        Return an order by clause for the project's start_at or published_at.

        param bool desc: Use descending order (default True)
        """
        clause = sa.case(
            (cls.start_at.isnot(None), cls.start_at),
            else_=cls.published_at,
        )
        return clause

    @classmethod
    def all_unsorted(cls):
        """Return query of all published projects, without ordering criteria."""
        return (
            cls.query.join(Profile)
            .outerjoin(Venue)
            .filter(cls.state.PUBLISHED, Profile.is_verified.is_(True))
        )

    @classmethod
    def all(cls):  # noqa: A003
        """Return all published projects, ordered by date."""
        return cls.all_unsorted().order_by(cls.order_by_date())

    # The base class offers `get(parent, name)`. We accept f'{parent}/{name}' here for
    # convenience as this is only used in shell access.
    @classmethod
    def get(cls, profile_project):  # pylint: disable=arguments-differ
        """Get a project by its URL slug in the form ``<profile>/<project>``."""
        profile_name, project_name = profile_project.split('/')
        return (
            cls.query.join(Profile)
            .filter(Profile.name_is(profile_name), Project.name == project_name)
            .one_or_none()
        )

    @classmethod
    def migrate_profile(  # type: ignore[return]
        cls, old_profile: Profile, new_profile: Profile
    ) -> OptionalMigratedTables:
        """Migrate from one account to another when merging users."""
        names = {project.name for project in new_profile.projects}
        for project in old_profile.projects:
            if project.name in names:
                app.logger.warning(
                    "Project %r had a conflicting name in account migration,"
                    " so renaming by adding adding random value to name",
                    project,
                )
                project.name += '-' + buid()
            project.profile = new_profile


add_search_trigger(Project, 'search_vector')


@reopen(Profile)
class __Profile:
    id: Mapped[int]  # noqa: A003

    listed_projects = sa.orm.relationship(
        Project,
        lazy='dynamic',
        primaryjoin=sa.and_(
            Profile.id == Project.profile_id,
            Project.state.PUBLISHED,
        ),
        viewonly=True,
    )
    draft_projects = sa.orm.relationship(
        Project,
        lazy='dynamic',
        primaryjoin=sa.and_(
            Profile.id == Project.profile_id,
            sa.or_(Project.state.DRAFT, Project.cfp_state.DRAFT),
        ),
        viewonly=True,
    )
    projects_by_name = with_roles(
        sa.orm.relationship(
            Project, collection_class=attribute_keyed_dict('name'), viewonly=True
        ),
        read={'all'},
    )

    def draft_projects_for(self, user: Optional[User]) -> List[Project]:
        if user is not None:
            return [
                membership.project
                for membership in user.projects_as_crew_active_memberships.join(Project)
                .join(Profile)
                .filter(
                    # Project is attached to this account
                    Project.profile_id == self.id,
                    # Project is in draft state OR has a draft call for proposals
                    sa.or_(Project.state.DRAFT, Project.cfp_state.DRAFT),
                )
            ]
        return []

    def unscheduled_projects_for(self, user: Optional[User]) -> List[Project]:
        if user is not None:
            return [
                membership.project
                for membership in user.projects_as_crew_active_memberships.join(Project)
                .join(Profile)
                .filter(
                    # Project is attached to this account
                    Project.profile_id == self.id,
                    # Project is in draft state OR has a draft call for proposals
                    sa.or_(Project.state.PUBLISHED_WITHOUT_SESSIONS),
                )
            ]
        return []

    @with_roles(read={'all'}, datasets={'primary', 'without_parent', 'related'})
    @cached_property
    def published_project_count(self) -> int:
        return (
            self.listed_projects.filter(Project.state.PUBLISHED).order_by(None).count()
        )


class ProjectRedirect(TimestampMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'project_redirect'
    __allow_unmapped__ = True

    profile_id = sa.Column(
        sa.Integer, sa.ForeignKey('profile.id'), nullable=False, primary_key=True
    )
    profile: Mapped[Profile] = sa.orm.relationship(
        Profile, backref=sa.orm.backref('project_redirects', cascade='all')
    )
    parent: Mapped[Profile] = sa.orm.synonym('profile')
    name = sa.Column(sa.Unicode(250), nullable=False, primary_key=True)

    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('project.id', ondelete='SET NULL'), nullable=True
    )
    project: Mapped[Project] = sa.orm.relationship(Project, backref='redirects')

    def __repr__(self) -> str:
        """Represent :class:`ProjectRedirect` as a string."""
        if not self.project:
            return f'<ProjectRedirect {self.profile.name}/{self.name}: (none)>'
        return (
            f'<ProjectRedirect {self.profile.name}/{self.name}'
            f' → {self.project.profile.name}/{self.project.name}>'
        )

    def redirect_view_args(self):
        if self.project:
            return {'profile': self.profile.name, 'project': self.project.name}
        return {}

    @classmethod
    def add(cls, project, profile=None, name=None):
        """
        Add a project redirect in a given profile.

        :param project: The project to create a redirect for
        :param profile: The profile to place the redirect in, defaulting to existing
        :param str name: Name to redirect, defaulting to project's existing name

        Typical use is when a project is renamed, to create a redirect from its previous
        name, or when it's moved between projects, to create a redirect from previous
        project.
        """
        if profile is None:
            profile = project.profile
        if name is None:
            name = project.name
        redirect = ProjectRedirect.query.get((profile.id, name))
        if redirect is None:
            redirect = ProjectRedirect(profile=profile, name=name, project=project)
            db.session.add(redirect)
        else:
            redirect.project = project
        return redirect

    @classmethod
    def migrate_profile(  # type: ignore[return]
        cls, old_profile: Profile, new_profile: Profile
    ) -> OptionalMigratedTables:
        """
        Discard redirects when migrating profiles.

        Since there is no profile redirect, all project redirects will also be
        unreachable and are no longer relevant.
        """
        names = {pr.name for pr in new_profile.project_redirects}
        for pr in old_profile.project_redirects:
            if pr.name not in names:
                pr.profile = new_profile
            else:
                # Discard project redirect since the name is already taken by another
                # redirect in the new account
                db.session.delete(pr)


class ProjectLocation(TimestampMixin, db.Model):  # type: ignore[name-defined]
    __tablename__ = 'project_location'
    __allow_unmapped__ = True
    #: Project we are tagging
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('project.id'), primary_key=True, nullable=False
    )
    project: Mapped[Project] = sa.orm.relationship(
        Project, backref=sa.orm.backref('locations', cascade='all')
    )
    #: Geonameid for this project
    geonameid = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    primary = sa.Column(sa.Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        """Represent :class:`ProjectLocation` as a string."""
        pri_sec = 'primary' if self.primary else 'secondary'
        return (
            f'<ProjectLocation {self.geonameid} {pri_sec} for project {self.project!r}>'
        )


@reopen(Commentset)
class __Commentset:
    project = with_roles(
        sa.orm.relationship(Project, uselist=False, back_populates='commentset'),
        grants_via={None: {'editor': 'document_subscriber'}},
    )


# Tail imports
# pylint: disable=wrong-import-position
from .project_membership import ProjectCrewMembership  # isort:skip
from .venue import Venue  # isort:skip  # skipcq: FLK-E402
