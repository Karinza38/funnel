"""Test configuration and fixtures."""
# pylint: disable=import-outside-toplevel, redefined-outer-name

from __future__ import annotations

from datetime import datetime, timezone
from types import MethodType, SimpleNamespace
import re
import threading
import typing as t

import pytest

from funnel.models import (
    AuthClient,
    AuthClientCredential,
    Label,
    Organization,
    OrganizationMembership,
    Project,
    Proposal,
    Team,
    User,
    db,
)

if t.TYPE_CHECKING:
    from flask_sqlalchemy import SQLAlchemy
    from sqlalchemy.orm import Session as DatabaseSessionClass

    from flask import Flask
    from flask.testing import FlaskClient


# --- Pytest config --------------------------------------------------------------------


def pytest_addoption(parser) -> None:
    """Allow db_session to be configured in the command line."""
    parser.addoption(
        '--dbsession',
        action='store',
        default='rollback',
        choices=('rollback', 'truncate'),
        help="Use db_session with 'rollback' (default) or 'truncate'"
        " (slower but more production-like)",
    )


def pytest_collection_modifyitems(items) -> None:
    """Sort tests to run lower level before higher level."""
    test_order = (
        'tests/unit/models',
        'tests/unit/forms',
        'tests/unit/proxies',
        'tests/unit/transports',
        'tests/unit/views',
        'tests/unit',
        'tests/integration/views',
        'tests/integration',
        'tests/features',
        'tests/e2e',
    )

    def sort_key(item) -> t.Tuple[int, str]:
        module_file = item.module.__file__
        for counter, path in enumerate(test_order):
            if path in module_file:
                return (counter, module_file)
        return (-1, module_file)

    items.sort(key=sort_key)


# --- Fixtures -------------------------------------------------------------------------


@pytest.fixture(scope='session')
def response_with_forms():
    from flask.wrappers import Response

    from lxml.html import FormElement, HtmlElement, fromstring  # nosec

    # --- ResponseWithForms, to make form submission in the test client testing easier
    # --- Adapted from the abandoned Flask-Fillin package

    _meta_refresh_content_re = re.compile(
        r"""
        \s*
        (?P<timeout>\d+)      # Timeout
        \s*
        ;?                    # ; separator for optional URL
        \s*
        (?:URL\s*=\s*["']?)?  # Optional 'URL=' or 'URL="' prefix
        (?P<url>.*?)          # Optional URL
        (?:["']?\s*)          # Optional closing quote for URL
        """,
        re.ASCII | re.IGNORECASE | re.VERBOSE,
    )

    class MetaRefreshContent(t.NamedTuple):
        """Timeout and optional URL in a Meta Refresh tag."""

        timeout: int
        url: t.Optional[str] = None

    class ResponseWithForms(Response):
        """
        Wrapper for the test client response that makes form submission easier.

        Usage::

            def test_mytest(client) -> None:
                response = client.get('/page_with_forms')
                form = response.form('login')
                form.fields['username'] = 'my username'
                form.fields['password'] = 'secret'
                form.fields['remember'] = True
                next_response = form.submit(client)
        """

        _parsed_html: t.Optional[HtmlElement] = None

        @property
        def html(self) -> HtmlElement:
            """Return the parsed HTML tree."""
            if self._parsed_html is None:
                self._parsed_html = fromstring(self.data)

                # add click method to all links
                def _click(
                    self, client, **kwargs
                ):  # pylint: disable=redefined-outer-name
                    # `self` is the `a` element here
                    path = self.attrib['href']
                    return client.get(path, **kwargs)

                for link in self._parsed_html.iter('a'):
                    link.click = MethodType(_click, link)  # type: ignore[attr-defined]

                # add submit method to all forms
                def _submit(
                    self, client, path=None, **kwargs
                ):  # pylint: disable=redefined-outer-name
                    # `self` is the `form` element here
                    data = dict(self.form_values())
                    if 'data' in kwargs:
                        data.update(kwargs['data'])
                        del kwargs['data']
                    if path is None:
                        path = self.action
                    if 'method' not in kwargs:
                        kwargs['method'] = self.method
                    return client.open(path, data=data, **kwargs)

                for form in self._parsed_html.forms:  # type: ignore[attr-defined]
                    form.submit = MethodType(_submit, form)
            return self._parsed_html

        @property
        def forms(self) -> t.List[FormElement]:
            """
            Return list of all forms in the document.

            Contains the LXML form type as documented at
            http://lxml.de/lxmlhtml.html#forms with an additional `.submit(client)`
            method to submit the form.
            """
            return self.html.forms

        def form(
            self, id_: t.Optional[str] = None, name: t.Optional[str] = None
        ) -> t.Optional[FormElement]:
            """Return the first form matching given id or name in the document."""
            if id_:
                forms = self.html.cssselect(f'form#{id_}')
            elif name:
                forms = self.html.cssselect(f'form[name={name}]')
            else:
                forms = self.forms
            if forms:
                return forms[0]
            return None

        def links(self, selector: str = 'a') -> t.List[HtmlElement]:
            """Get all the links matching the given CSS selector."""
            return self.html.cssselect(selector)

        def link(self, selector: str = 'a') -> t.Optional[HtmlElement]:
            """Get first link matching the given CSS selector."""
            links = self.links(selector)
            if links:
                return links[0]
            return None

        @property
        def metarefresh(self) -> t.Optional[MetaRefreshContent]:
            """Return content of Meta Refresh tag if present."""
            meta_elements = self.html.cssselect('meta[http-equiv="refresh"]')
            if not meta_elements:
                return None
            content = meta_elements[0].attrib.get('content')
            if content is None:
                return None
            match = _meta_refresh_content_re.fullmatch(content)
            if match is None:
                return None
            return MetaRefreshContent(int(match['timeout']), match['url'] or None)

    return ResponseWithForms


@pytest.fixture(scope='session')
def colorama() -> t.Iterator[SimpleNamespace]:
    """Provide the colorama print colorizer."""
    from colorama import Back, Fore, Style, deinit, init

    init()
    yield SimpleNamespace(Fore=Fore, Back=Back, Style=Style)
    deinit()


@pytest.fixture(scope='session')
def print_stack(pytestconfig, colorama) -> t.Callable[[int, int], None]:
    """Print a stack trace up to an outbound call from within this repository."""
    from inspect import stack as inspect_stack
    import os.path

    boundary_path = str(pytestconfig.rootpath)
    if not boundary_path.endswith('/'):
        boundary_path += '/'

    def func(skip: int = 0, indent: int = 2) -> None:
        # Retrieve call stack, removing ourselves and as many frames as the caller wants
        # to skip
        prefix = ' ' * indent
        stack = inspect_stack()[2 + skip :]

        lines = []
        # Reverse list to order from outermost to innermost, and remove outer frames
        # that are outside our code
        stack.reverse()
        while stack and not stack[0].filename.startswith(boundary_path):
            stack.pop(0)

        # Find the first exit from our code and keep only that line and later to
        # remove unneccesary context
        for index, fi in enumerate(stack):
            if not fi.filename.startswith(boundary_path):
                stack = stack[index - 1 :]
                break

        for fi in stack:
            line_color = (
                colorama.Fore.RED
                if fi.filename.startswith(boundary_path)
                else colorama.Fore.GREEN
            )
            code_line = (
                fi.code_context[fi.index or 0].strip() if fi.code_context else ''
            )
            lines.append(
                f'{prefix}{line_color}'
                f'{os.path.relpath(fi.filename)}:{fi.lineno}::{fi.function}'
                f'\t{code_line}'
                f'{colorama.Style.RESET_ALL}'
            )
        del stack
        # Now print the lines
        print(*lines, sep='\n')  # noqa: T201

    return func


@pytest.fixture(scope='session')
def app() -> Flask:
    """App as a fixture to avoid imports in tests."""
    from funnel import app

    return app


@pytest.fixture()
def app_context(app) -> t.Iterator:
    """Create an app context for the test."""
    with app.app_context() as ctx:
        yield ctx


@pytest.fixture()
def request_context(app) -> t.Iterator:
    """Create a request context with default values for the test."""
    with app.test_request_context() as ctx:
        yield ctx


config_test_keys: t.Dict[str, t.Set[str]] = {
    'recaptcha': {'RECAPTCHA_PUBLIC_KEY', 'RECAPTCHA_PRIVATE_KEY'},
    'twilio': {'SMS_TWILIO_SID', 'SMS_TWILIO_TOKEN'},
    'exotel': {'SMS_EXOTEL_SID', 'SMS_EXOTEL_TOKEN'},
    'gmaps': {'GOOGLE_MAPS_API_KEY'},
    'youtube': {'YOUTUBE_API_KEY'},
    'vimeo': {'VIMEO_CLIENT_ID', 'VIMEO_CLIENT_SECRET', 'VIMEO_ACCESS_TOKEN'},
    'oauth-twitter': {'OAUTH_TWITTER_KEY', 'OAUTH_TWITTER_SECRET'},
    'oauth-google': {'OAUTH_GOOGLE_KEY', 'OAUTH_GOOGLE_SECRET'},
    'oauth-github': {'OAUTH_GITHUB_KEY', 'OAUTH_GITHUB_SECRET'},
    'oauth-linkedin': {'OAUTH_LINKEDIN_KEY', 'OAUTH_LINKEDIN_SECRET'},
    'oauth-zoom': {'OAUTH_ZOOM_KEY', 'OAUTH_ZOOM_SECRET'},
    'geoip-data': {'GEOIP_DB_CITY', 'GEOIP_DB_ASN'},
    'telegram-notify': {'TELEGRAM_NOTIFY_APIKEY'},
    'telegram-stats': {'TELEGRAM_STATS_APIKEY', 'TELEGRAM_STATS_CHATID'},
    'telegram-error': {'TELEGRAM_ERROR_APIKEY', 'TELEGRAM_ERROR_CHATID'},
}


@pytest.fixture(autouse=True)
def _requires_config(request) -> None:
    """Skip test if app is missing config (using ``requires_config`` mark)."""
    if request.node.get_closest_marker('requires_config'):
        app = request.getfixturevalue('app')
        for mark in request.node.iter_markers('requires_config'):
            for config in mark.args:
                if config not in config_test_keys:
                    pytest.fail(f"Unknown required config {config}")
                for setting_key in config_test_keys[config]:
                    if not app.config.get(setting_key):
                        pytest.skip(
                            f"Skipped due to missing config for {config} in app.config:"
                            f" {setting_key}"
                        )


@pytest.fixture(scope='session')
def _app_events(colorama, print_stack, app) -> t.Iterator:
    """Fixture to report Flask signals with a stack trace when debugging a test."""
    from functools import partial

    import flask

    def signal_handler(signal_name, *args, **kwargs):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}Signal:{colorama.Style.NORMAL}"
            f" {colorama.Fore.YELLOW}{signal_name}{colorama.Style.RESET_ALL}"
        )
        print_stack(2)  # Skip two stack frames from Blinker

    request_started = partial(signal_handler, 'request_started')
    request_finished = partial(signal_handler, 'request_finished')
    request_tearing_down = partial(signal_handler, 'request_tearing_down')
    appcontext_tearing_down = partial(signal_handler, 'appcontext_tearing_down')
    appcontext_pushed = partial(signal_handler, 'appcontext_pushed')
    appcontext_popped = partial(signal_handler, 'appcontext_popped')

    flask.request_started.connect(request_started, app)
    flask.request_finished.connect(request_finished, app)
    flask.request_tearing_down.connect(request_tearing_down, app)
    flask.appcontext_tearing_down.connect(appcontext_tearing_down, app)
    flask.appcontext_pushed.connect(appcontext_pushed, app)
    flask.appcontext_popped.connect(appcontext_popped, app)

    yield

    flask.request_started.disconnect(request_started, app)
    flask.request_finished.disconnect(request_finished, app)
    flask.request_tearing_down.disconnect(request_tearing_down, app)
    flask.appcontext_tearing_down.disconnect(appcontext_tearing_down, app)
    flask.appcontext_pushed.disconnect(appcontext_pushed, app)
    flask.appcontext_popped.disconnect(appcontext_popped, app)


@pytest.fixture()
def _database_events(colorama, print_stack) -> t.Iterator:
    """
    Fixture to report database session events for debugging a test.

    If a test is exhibiting unusual behaviour, add this fixture to trace db events::

        @pytest.mark.usefixtures('_database_events')
        def test_whatever():
            ...
    """
    from sqlalchemy import event, inspect
    from sqlalchemy.orm import Session as DatabaseSessionClass

    def safe_repr(entity):
        try:
            return repr(entity)
        except Exception:  # noqa: B902  # pylint: disable=broad-except
            if hasattr(entity, '__class__'):
                return f'{entity.__class__.__qualname__}(class-repr-error)'
            if hasattr(entity, '__name__'):
                return f'{entity.__name__}(repr-error)'
            return 'repr-error'

    @event.listens_for(db.Model, 'init', propagate=True)
    def event_init(obj, args, kwargs):
        rargs = ', '.join(safe_repr(_a) for _a in args)
        rkwargs = ', '.join(f'{_k}={safe_repr(_v)}' for _k, _v in kwargs.items())
        rparams = f'{rargs, rkwargs}' if rargs else rkwargs
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: new:{colorama.Style.NORMAL}"
            f" {obj.__class__.__qualname__}({rparams})"
        )

    @event.listens_for(DatabaseSessionClass, 'transient_to_pending')
    def event_transient_to_pending(_session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: transient to pending:{colorama.Style.NORMAL}"
            f" {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'pending_to_transient')
    def event_pending_to_transient(_session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: pending to transient:{colorama.Style.NORMAL}"
            f" {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'pending_to_persistent')
    def event_pending_to_persistent(_session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: pending to persistent:{colorama.Style.NORMAL}"
            f" {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'loaded_as_persistent')
    def event_loaded_as_persistent(_session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: loaded as persistent:{colorama.Style.NORMAL}"
            f" {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'persistent_to_transient')
    def event_persistent_to_transient(_session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: persistent to transient:"
            f"{colorama.Style.NORMAL} {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'persistent_to_deleted')
    def event_persistent_to_deleted(_session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: persistent to deleted:{colorama.Style.NORMAL}"
            f" {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'deleted_to_detached')
    def event_deleted_to_detached(_session, obj):
        i = inspect(obj)
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: deleted to detached:{colorama.Style.NORMAL}"
            f" {obj.__class__.__qualname__}/{i.identity}"
        )

    @event.listens_for(DatabaseSessionClass, 'persistent_to_detached')
    def event_persistent_to_detached(_session, obj):
        i = inspect(obj)
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: persistent to detached:"
            f"{colorama.Style.NORMAL} {obj.__class__.__qualname__}/{i.identity}"
        )

    @event.listens_for(DatabaseSessionClass, 'detached_to_persistent')
    def event_detached_to_persistent(_session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: detached to persistent:"
            f"{colorama.Style.NORMAL} {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'deleted_to_persistent')
    def event_deleted_to_persistent(session, obj):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}obj: deleted to persistent:{colorama.Style.NORMAL}"
            f" {safe_repr(obj)}"
        )

    @event.listens_for(DatabaseSessionClass, 'do_orm_execute')
    def event_do_orm_execute(orm_execute_state):
        state_is = []
        if orm_execute_state.is_column_load:
            state_is.append("is_column_load")
        if orm_execute_state.is_delete:
            state_is.append("is_delete")
        if orm_execute_state.is_insert:
            state_is.append("is_insert")
        if orm_execute_state.is_orm_statement:
            state_is.append("is_orm_statement")
        if orm_execute_state.is_relationship_load:
            state_is.append("is_relationship_load")
        if orm_execute_state.is_select:
            state_is.append("is_select")
        if orm_execute_state.is_update:
            state_is.append("is_update")
        class_name = (
            orm_execute_state.bind_mapper.class_.__qualname__
            if orm_execute_state.bind_mapper
            else None
        )
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}exec:{colorama.Style.NORMAL} {class_name}:"
            f" {', '.join(state_is)}"
        )

    @event.listens_for(DatabaseSessionClass, 'after_begin')
    def event_after_begin(_session, transaction, _connection):
        if transaction.nested:
            if transaction.parent.nested:
                print(  # noqa: T201
                    f"{colorama.Style.BRIGHT}session:{colorama.Style.NORMAL}"
                    f" BEGIN (double nested)"
                )
            else:
                print(  # noqa: T201
                    f"{colorama.Style.BRIGHT}session:{colorama.Style.NORMAL}"
                    f" BEGIN (nested)"
                )
        else:
            print(  # noqa: T201
                f"{colorama.Style.BRIGHT}session:{colorama.Style.NORMAL} BEGIN (outer)"
            )
        print_stack()

    @event.listens_for(DatabaseSessionClass, 'after_commit')
    def event_after_commit(session):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}session:{colorama.Style.NORMAL} COMMIT"
            f" ({session.info!r})"
        )

    @event.listens_for(DatabaseSessionClass, 'after_flush')
    def event_after_flush(session, _flush_context):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}session:{colorama.Style.NORMAL} FLUSH"
            f" ({session.info})"
        )

    @event.listens_for(DatabaseSessionClass, 'after_rollback')
    def event_after_rollback(session):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}session:{colorama.Style.NORMAL} ROLLBACK"
            f" ({session.info})"
        )
        print_stack()

    @event.listens_for(DatabaseSessionClass, 'after_soft_rollback')
    def event_after_soft_rollback(session, _previous_transaction):
        print(  # noqa: T201
            f"{colorama.Style.BRIGHT}session:{colorama.Style.NORMAL} SOFT ROLLBACK"
            f" ({session.info})"
        )
        print_stack()

    @event.listens_for(DatabaseSessionClass, 'after_transaction_create')
    def event_after_transaction_create(_session, transaction):
        if transaction.nested:
            if transaction.parent.nested:
                print(  # noqa: T201
                    f"{colorama.Style.BRIGHT}transaction:{colorama.Style.NORMAL}"
                    f" CREATE (savepoint)"
                )
            else:
                print(  # noqa: T201
                    f"{colorama.Style.BRIGHT}transaction:{colorama.Style.NORMAL}"
                    f" CREATE (fixture)"
                )
        else:
            print(  # noqa: T201
                f"{colorama.Style.BRIGHT}transaction:{colorama.Style.NORMAL}"
                f" CREATE (db)"
            )
        print_stack()

    @event.listens_for(DatabaseSessionClass, 'after_transaction_end')
    def event_after_transaction_end(_session, transaction):
        if transaction.nested:
            if transaction.parent.nested:
                print(  # noqa: T201
                    f"{colorama.Style.BRIGHT}transaction:{colorama.Style.NORMAL} END"
                    f" (double nested)"
                )
            else:
                print(  # noqa: T201
                    f"{colorama.Style.BRIGHT}transaction:{colorama.Style.NORMAL} END"
                    f" (nested)"
                )
        else:
            print(  # noqa: T201
                f"{colorama.Style.BRIGHT}transaction:{colorama.Style.NORMAL} END"
                f" (outer)"
            )
        print_stack()

    yield

    event.remove(db.Model, 'init', event_init)
    event.remove(
        DatabaseSessionClass, 'transient_to_pending', event_transient_to_pending
    )
    event.remove(
        DatabaseSessionClass, 'pending_to_transient', event_pending_to_transient
    )
    event.remove(
        DatabaseSessionClass, 'pending_to_persistent', event_pending_to_persistent
    )
    event.remove(
        DatabaseSessionClass, 'loaded_as_persistent', event_loaded_as_persistent
    )
    event.remove(
        DatabaseSessionClass, 'persistent_to_transient', event_persistent_to_transient
    )
    event.remove(
        DatabaseSessionClass, 'persistent_to_deleted', event_persistent_to_deleted
    )
    event.remove(DatabaseSessionClass, 'deleted_to_detached', event_deleted_to_detached)
    event.remove(
        DatabaseSessionClass, 'persistent_to_detached', event_persistent_to_detached
    )
    event.remove(
        DatabaseSessionClass, 'detached_to_persistent', event_detached_to_persistent
    )
    event.remove(
        DatabaseSessionClass, 'deleted_to_persistent', event_deleted_to_persistent
    )
    event.remove(DatabaseSessionClass, 'do_orm_execute', event_do_orm_execute)
    event.remove(DatabaseSessionClass, 'after_begin', event_after_begin)
    event.remove(DatabaseSessionClass, 'after_commit', event_after_commit)
    event.remove(DatabaseSessionClass, 'after_flush', event_after_flush)
    event.remove(DatabaseSessionClass, 'after_rollback', event_after_rollback)
    event.remove(DatabaseSessionClass, 'after_soft_rollback', event_after_soft_rollback)
    event.remove(
        DatabaseSessionClass, 'after_transaction_create', event_after_transaction_create
    )
    event.remove(
        DatabaseSessionClass, 'after_transaction_end', event_after_transaction_end
    )


@pytest.fixture(scope='session')
def database(request, app) -> SQLAlchemy:
    """Provide a database structure."""
    from funnel import redis_store

    with app.app_context():
        db.create_all()
        redis_store.flushdb()

    @request.addfinalizer
    def drop_tables():
        with app.app_context():
            db.drop_all()

    return db


@pytest.fixture(scope='session')
def _db(database):  # noqa: PT005
    """Database fixture required by pytest-flask-sqlalchemy (unused)."""
    # Also see pyproject.toml for mock configuration
    return database


class RemoveIsRollback:
    """Change session.remove() to session.rollback()."""

    def __init__(self, session, rollback_provider):
        self.session = session
        self.original_remove = session.remove
        self.rollback_provider = rollback_provider
        self.owning_thread = threading.current_thread()

    def __enter__(self):
        # pylint: disable=unnecessary-lambda

        # If called in the owning thread (which is typical), deflect
        # ``session.remove()`` to ``session.rollback()``. If called in a sub-thread
        # (Flask-Executor), do nothing because there is no session to rollback, but
        # letting it be removed will close the main thread's session (!). This may be a
        # bug. # TODO
        self.session.remove = lambda *args, **kwargs: (
            self.rollback_provider()(*args, **kwargs)
            if threading.current_thread() == self.owning_thread
            else None
        )

    def __exit__(self, exc_type, exc_value, traceback):
        self.session.remove = self.original_remove


@pytest.fixture()
def db_session_truncate(app, database) -> t.Iterator[DatabaseSessionClass]:
    """Empty the database after each use of the fixture."""
    from sqlalchemy.orm import close_all_sessions

    from funnel import redis_store

    with RemoveIsRollback(database.session, lambda: database.session.rollback):
        yield database.session
    close_all_sessions()

    # Iterate through all database engines and empty their tables
    for bind in [None] + list(app.config.get('SQLALCHEMY_BINDS') or ()):
        engine = database.get_engine(app=app, bind=bind)
        with engine.begin() as connection:
            connection.execute(
                '''
                DO $$
                DECLARE tablenames text;
                BEGIN
                    tablenames := string_agg(
                        quote_ident(schemaname) || '.' || quote_ident(tablename),
                        ', ')
                        FROM pg_tables WHERE schemaname = 'public';
                    EXECUTE 'TRUNCATE TABLE ' || tablenames || ' RESTART IDENTITY';
                END; $$
            '''
            )

    # Clear Redis db too
    redis_store.flushdb()


@pytest.fixture()
def db_session_rollback(database) -> t.Iterator[DatabaseSessionClass]:
    """Create a nested transaction for the test and rollback after."""
    from sqlalchemy import event

    from funnel import redis_store

    db_connection = database.engine.connect()
    original_session = database.session
    transaction = db_connection.begin()
    database.session = database.create_scoped_session(
        options={'bind': db_connection, 'binds': {}}
    )
    database.session.info['fixture'] = True

    # For handling tests that actually call `session.rollback()`, we use a SQL savepoint
    # and add an event handler that restarts the savepoint. SQLAlchemy 1.4 deprecated
    # session.commit() being used to commit a savepoint, and 2.0 will remove it,
    # potentially breaking this fixture. It will need revision then.
    #
    # References:
    #
    # * 1.3: https://docs.sqlalchemy.org/en/13/orm/session_transaction.html
    #   #joining-a-session-into-an-external-transaction-such-as-for-test-suites
    # * 1.4: https://docs.sqlalchemy.org/en/14/orm/session_transaction.html
    #   #joining-a-session-into-an-external-transaction-such-as-for-test-suites

    savepoint = database.session.begin_nested()

    # XXX: SQLAlchemy 2.0 will need commit and rollback on the savepoint instead of the
    # session. This fixture is likely to break under 2.0 and will need revision

    @event.listens_for(database.session, 'after_transaction_end')
    def restart_savepoint(session, transaction_in):
        """If the savepoint terminates due to commit or rollback, restart it."""
        nonlocal savepoint
        if transaction_in.nested and not transaction_in.parent.nested:
            # This is a top-level savepoint, so restart it
            session.expire_all()
            savepoint = session.begin_nested()

    with RemoveIsRollback(database.session, lambda: savepoint.rollback):
        yield database.session

    event.remove(database.session, 'after_transaction_end', restart_savepoint)
    database.session.close()
    transaction.rollback()
    db_connection.close()
    database.session = original_session

    # Clear Redis db too
    redis_store.flushdb()


@pytest.fixture()
def db_session(request) -> DatabaseSessionClass:
    """
    Database session fixture.

    This fixture may be overridden in another conftest.py to return one of the two
    available session fixtures:

    * ``db_session_truncate``: Which allows unmediated database access but empties table
      contents after each use
    * ``db_session_savepoint``: Which nests the session in a SAVEPOINT and rolls back
      after each use

    This version of the fixture uses the --dbsession command-line option to choose the
    base fixture.
    """
    return request.getfixturevalue(
        {
            'rollback': 'db_session_rollback',
            'truncate': 'db_session_truncate',
        }[request.config.getoption('--dbsession')]
    )


@pytest.fixture()
def client(response_with_forms, app, db_session) -> FlaskClient:
    """Provide a test client that commits the db session before any action."""
    from flask.testing import FlaskClient

    client: FlaskClient = FlaskClient(app, response_with_forms, use_cookies=True)
    client_open = client.open

    def commit_before_open(*args, **kwargs):
        db_session.commit()
        return client_open(*args, **kwargs)

    client.open = commit_before_open  # type: ignore[assignment]
    return client


@pytest.fixture(scope='session')
def browser_patches():  # noqa : PT004
    """Patch webdriver for pytest-splinter."""
    from pytest_splinter.webdriver_patches import patch_webdriver

    # Required due to https://github.com/pytest-dev/pytest-splinter/issues/158
    patch_webdriver()


@pytest.fixture(scope='session')
def splinter_driver_kwargs(splinter_webdriver):
    """Disable certification verification for webdriver."""
    from selenium import webdriver

    if splinter_webdriver == 'chrome':
        options = webdriver.ChromeOptions()
        options.add_argument('--ignore-ssl-errors=yes')
        options.add_argument('--ignore-certificate-errors')

        return {'options': options}
    return {}


@pytest.fixture(scope='package')
def live_server(database, app):
    """Run application in a separate process."""
    from werkzeug import run_simple

    from funnel.devtest import BackgroundWorker, devtest_app

    # Use HTTPS for live server (set to False if required)
    use_https = True
    scheme = 'https' if use_https else 'http'
    # Use app's port from SERVER_NAME as basis for the port to run the live server on
    port_str = app.config['SERVER_NAME'].partition(':')[-1]
    if not port_str or not port_str.isdigit():
        pytest.fail(
            f"App does not have SERVER_NAME specified as host:port in config:"
            f" {app.config['SERVER_NAME']}"
        )
    port = int(port_str)

    # Save app config before modifying it to match live server environment
    original_app_config = {}
    for m_app in devtest_app.apps_by_host.values():
        original_app_config[m_app] = {
            'PREFERRED_URL_SCHEME': m_app.config['PREFERRED_URL_SCHEME'],
            'SERVER_NAME': m_app.config['SERVER_NAME'],
        }
        m_app.config['PREFERRED_URL_SCHEME'] = scheme
        m_host = m_app.config['SERVER_NAME'].split(':', 1)[0]
        m_app.config['SERVER_NAME'] = f'{m_host}:{port}'

    # Start background worker and wait until it's receiving connections
    server = BackgroundWorker(
        run_simple,
        args=('127.0.0.1', port, devtest_app),
        kwargs={
            'use_reloader': False,
            'use_debugger': True,
            'use_evalex': False,
            'threaded': True,
            'ssl_context': 'adhoc' if use_https else None,
        },
        probe_at=('127.0.0.1', port),
    )
    try:
        server.start()
    except RuntimeError as exc:
        # Server did not respond to probe until timeout; mark test as failed
        server.stop()
        pytest.fail(str(exc))

    with app.app_context():
        # Return live server config within an app context so that the test function
        # can use url_for without creating a context. However, secondary apps will
        # need context specifically established for url_for on them
        yield SimpleNamespace(
            url=f'{scheme}://{app.config["SERVER_NAME"]}/',
            urls=[
                f'{scheme}://{m_app.config["SERVER_NAME"]}/'
                for m_app in devtest_app.apps_by_host.values()
            ],
        )

    # Stop server after use
    server.stop()

    # Restore original app config
    for m_app, config in original_app_config.items():
        m_app.config.update(config)


@pytest.fixture()
def csrf_token(client):
    """Supply a CSRF token for use in form submissions."""
    return client.get('/api/baseframe/1/csrf/refresh').get_data(as_text=True)


@pytest.fixture()
def login(app, client, db_session) -> SimpleNamespace:
    """Provide a login fixture."""

    def as_(user):
        db_session.commit()
        with client.session_transaction() as session:
            # TODO: This depends on obsolete code in views/login_session that replaces
            # cookie session authentication with db-backed authentication. It's long
            # pending removal
            session['userid'] = user.userid
        # Perform a request to convert the session userid into a UserSession
        client.get('/api/1/user/get')

    def logout():
        # TODO: Test this
        client.delete_cookie(
            client.server_name, 'lastuser', domain=app.config['LASTUSER_COOKIE_DOMAIN']
        )

    return SimpleNamespace(as_=as_, logout=logout)


# --- Sample data: users, organizations, projects, etc ---------------------------------

# These names are adapted from the Discworld universe. Backstories can be found at:
# * https://discworld.fandom.com/
# * https://wiki.lspace.org/


# --- Users


@pytest.fixture()
def user_twoflower(db_session) -> User:
    """
    Twoflower is a tourist from the Agatean Empire who goes on adventures.

    As a tourist unfamiliar with local customs, Twoflower represents our naive user,
    having only made a user account but not having picked a username or made any other
    affiliations.
    """
    user = User(fullname="Twoflower")
    db_session.add(user)
    return user


@pytest.fixture()
def user_rincewind(db_session) -> User:
    """
    Rincewind is a wizard and a former member of Unseen University.

    Rincewind is Twoflower's guide in the first two books, and represents our fully
    initiated user in tests.
    """
    user = User(username='rincewind', fullname="Rincewind")
    db_session.add(user)
    return user


@pytest.fixture()
def user_death(db_session) -> User:
    """
    Death is the epoch user, present at the beginning and always having the last word.

    Since Death predates all other users in tests, any call to `merge_users` or
    `migrate_user` always transfers assets to Death. The fixture has created_at set to
    the epoch to represent this. Death is also a site admin.
    """
    user = User(
        username='death',
        fullname="Death",
        created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(user)
    return user


@pytest.fixture()
def user_mort(db_session) -> User:
    """
    Mort is Death's apprentice, and a site admin in tests.

    Mort has a created_at in the past (the publication date of the book), granting
    priority when merging user accounts. Unlike Death, Mort does not have a username or
    profile, so Mort will acquire it from a merged user.
    """
    user = User(fullname="Mort", created_at=datetime(1987, 11, 12, tzinfo=timezone.utc))
    db_session.add(user)
    return user


@pytest.fixture()
def user_susan(db_session) -> User:
    """
    Susan Sto Helit (also written Sto-Helit) is Death's grand daughter.

    Susan inherits Death's role as a site admin and plays a correspondent with Mort.
    """
    user = User(username='susan', fullname="Susan Sto Helit")
    db_session.add(user)
    return user


@pytest.fixture()
def user_lutze(db_session) -> User:
    """
    Lu-Tze is a history monk and sweeper at the Monastery of Oi-Dong.

    Lu-Tze plays the role of a site editor, cleaning up after messy users.
    """
    user = User(username='lu-tze', fullname="Lu-Tze")
    db_session.add(user)
    return user


@pytest.fixture()
def user_ridcully(db_session) -> User:
    """
    Mustrum Ridcully, archchancellor of Unseen University.

    Ridcully serves as an owner of the Unseen University organization in tests.
    """
    user = User(username='ridcully', fullname="Mustrum Ridcully")
    db_session.add(user)
    return user


@pytest.fixture()
def user_librarian(db_session) -> User:
    """
    Librarian of Unseen University, currently an orangutan.

    The Librarian serves as an admin of the Unseen University organization in tests.
    """
    user = User(username='librarian', fullname="The Librarian")
    db_session.add(user)
    return user


@pytest.fixture()
def user_ponder_stibbons(db_session) -> User:
    """
    Ponder Stibbons, maintainer of Hex, the computer powered by an Anthill Inside.

    Admin of UU org.
    """
    user = User(username='ponder-stibbons', fullname="Ponder Stibbons")
    db_session.add(user)
    return user


@pytest.fixture()
def user_vetinari(db_session) -> User:
    """
    Havelock Vetinari, patrician (aka dictator) of Ankh-Morpork.

    Co-owner of the City Watch organization in our tests.
    """
    user = User(username='vetinari', fullname="Havelock Vetinari")
    db_session.add(user)
    return user


@pytest.fixture()
def user_vimes(db_session) -> User:
    """
    Samuel Vimes, commander of the Ankh-Morpork City Watch.

    Co-owner of the City Watch organization in our tests.
    """
    user = User(username='vimes', fullname="Sam Vimes")
    db_session.add(user)
    return user


@pytest.fixture()
def user_carrot(db_session) -> User:
    """
    Carrot Ironfoundersson, captain of the Ankh-Morpork City Watch.

    Admin of the organization in our tests.
    """
    user = User(username='carrot', fullname="Carrot Ironfoundersson")
    db_session.add(user)
    return user


@pytest.fixture()
def user_angua(db_session) -> User:
    """
    Delphine Angua von Überwald, member of the Ankh-Morpork City Watch, and foreigner.

    Represents a user who (a) gets promoted in her organization, and (b) prefers an
    foreign, unsupported language.
    """
    # We assign here the locale for Interlingue ('ie'), a constructed language, on the
    # assumption that it will never be supported. "Uberwald" is the German translation
    # of Transylvania, which is located in Romania. Interlingue is the work of an
    # Eastern European, and has since been supplanted by Interlingua, with ISO 639-1
    # code 'ia'. It is therefore reasonably safe to assume Interlingue is dead.
    user = User(fullname="Angua von Überwald", locale='ie', auto_locale=False)
    db_session.add(user)
    return user


@pytest.fixture()
def user_dibbler(db_session) -> User:
    """
    Cut Me Own Throat (or C.M.O.T) Dibbler, huckster who exploits small opportunities.

    Represents the spammer in our tests, from spam comments to spam projects.
    """
    user = User(username='dibbler', fullname="CMOT Dibbler")
    db_session.add(user)
    return user


@pytest.fixture()
def user_wolfgang(db_session) -> User:
    """
    Wolfgang von Überwald, brother of Angua, violent shapeshifter.

    Represents an attacker who changes appearance by changing identifiers or making
    sockpuppet user accounts.
    """
    user = User(username='wolfgang', fullname="Wolfgang von Überwald")
    db_session.add(user)
    return user


@pytest.fixture()
def user_om(db_session) -> User:
    """
    Great God Om of the theocracy of Omnia, who has lost his believers.

    Moves between having a user account and an org account in tests, creating a new user
    account for Brutha, the last believer.
    """
    user = User(username='omnia', fullname="Om")
    db_session.add(user)
    return user


# --- Organizations


@pytest.fixture()
def org_ankhmorpork(db_session, user_vetinari) -> Organization:
    """
    City of Ankh-Morpork, here representing the government rather than location.

    Havelock Vetinari is the Patrician (aka dictator), and sponsors various projects to
    develop the city.
    """
    org = Organization(name='ankh-morpork', title="Ankh-Morpork", owner=user_vetinari)
    db_session.add(org)
    return org


@pytest.fixture()
def org_uu(
    db_session, user_ridcully, user_librarian, user_ponder_stibbons
) -> Organization:
    """
    Unseen University is located in Ankh-Morpork.

    Staff:

    * Alberto Malich, founder emeritus (not listed here since no corresponding role)
    * Mustrum Ridcully, archchancellor (owner)
    * The Librarian, head of the library (admin)
    * Ponder Stibbons, Head of Inadvisably Applied Magic (admin)
    """
    org = Organization(name='UU', title="Unseen University", owner=user_ridcully)
    db_session.add(org)
    db_session.add(
        OrganizationMembership(
            organization=org,
            user=user_librarian,
            is_owner=False,
            granted_by=user_ridcully,
        )
    )
    db_session.add(
        OrganizationMembership(
            organization=org,
            user=user_ponder_stibbons,
            is_owner=False,
            granted_by=user_ridcully,
        )
    )
    return org


@pytest.fixture()
def org_citywatch(db_session, user_vetinari, user_vimes, user_carrot) -> Organization:
    """
    City Watch of Ankh-Morpork (a sub-organization).

    Staff:

    * Havelock Vetinari, Patrician of the city, legal owner but with no operating role
    * Sam Vimes, commander (owner)
    * Carrot Ironfoundersson, captain (admin)
    * Angua von Uberwald, corporal (unlisted, as there is no member role)
    """
    org = Organization(name='city-watch', title="City Watch", owner=user_vetinari)
    db_session.add(org)
    db_session.add(
        OrganizationMembership(
            organization=org, user=user_vimes, is_owner=True, granted_by=user_vetinari
        )
    )
    db_session.add(
        OrganizationMembership(
            organization=org, user=user_carrot, is_owner=False, granted_by=user_vimes
        )
    )
    return org


# --- Projects
# Fixtures from this point on drift away from Discworld, to reflect the unique contours
# of the product being tested. Maintaining fidelity to Discworld is hard.


@pytest.fixture()
def project_expo2010(db_session, org_ankhmorpork, user_vetinari) -> Project:
    """Ankh-Morpork hosts its 2010 expo."""
    db_session.flush()

    project = Project(
        profile=org_ankhmorpork.profile,
        user=user_vetinari,
        title="Ankh-Morpork 2010",
        tagline="Welcome to Ankh-Morpork, tourists!",
        description="The city doesn't have tourists. Let's change that.",
    )
    db_session.add(project)
    return project


@pytest.fixture()
def project_expo2011(db_session, org_ankhmorpork, user_vetinari) -> Project:
    """Ankh-Morpork hosts its 2011 expo."""
    db_session.flush()

    project = Project(
        profile=org_ankhmorpork.profile,
        user=user_vetinari,
        title="Ankh-Morpork 2011",
        tagline="Welcome back, our pub's changed",
        description="The Broken Drum is gone, but we have The Mended Drum now.",
    )
    db_session.add(project)
    return project


@pytest.fixture()
def project_ai1(db_session, org_uu, user_ponder_stibbons) -> Project:
    """
    Anthill Inside conference, hosted by Unseen University (an inspired event).

    Based on Soul Music, which features the first appearance of Hex, published 1994.
    """
    db_session.flush()

    project = Project(
        profile=org_uu.profile,
        user=user_ponder_stibbons,
        title="Soul Music",
        tagline="Hex makes an initial appearance",
        description="Hex has its origins in a device that briefly appeared in Soul"
        " Music, created by Ponder Stibbons and some student Wizards in the High Energy"
        " Magic building. In this form it was simply a complex network of glass tubes,"
        " containing ants. The wizards could then use punch cards to control which"
        " tubes the ants could crawl through, enabling it to perform simple"
        " mathematical functions.",
    )
    db_session.add(project)
    return project


@pytest.fixture()
def project_ai2(db_session, org_uu, user_ponder_stibbons) -> Project:
    """
    Anthill Inside conference, hosted by Unseen University (an inspired event).

    Based on Interesting Times.
    """
    db_session.flush()

    project = Project(
        profile=org_uu.profile,
        user=user_ponder_stibbons,
        title="Interesting Times",
        tagline="Hex invents parts for itself",
        description="Hex has become a lot more complex, and is constantly reinventing"
        " itself, meaning several new components of it are mysteries to those at UU.",
    )
    db_session.add(project)
    return project


# --- Client apps


@pytest.fixture()
def client_hex(db_session, org_uu) -> Project:
    """
    Hex, supercomputer at Unseen University, powered by an Anthill Inside.

    Owned by UU (owner) and administered by Ponder Stibbons (no corresponding role).
    """
    # TODO: AuthClient needs to move to profile as parent
    auth_client = AuthClient(
        title="Hex",
        organization=org_uu,
        confidential=True,
        website='https://example.org/',
        redirect_uris=['https://example.org/callback'],
    )
    db_session.add(auth_client)
    return auth_client


@pytest.fixture()
def client_hex_credential(db_session, client_hex) -> SimpleNamespace:
    cred, secret = AuthClientCredential.new(client_hex)
    db_session.add(cred)
    return SimpleNamespace(cred=cred, secret=secret)


@pytest.fixture()
def all_fixtures(  # pylint: disable=too-many-arguments,too-many-locals
    db_session,
    user_twoflower,
    user_rincewind,
    user_death,
    user_mort,
    user_susan,
    user_lutze,
    user_ridcully,
    user_librarian,
    user_ponder_stibbons,
    user_vetinari,
    user_vimes,
    user_carrot,
    user_angua,
    user_dibbler,
    user_wolfgang,
    user_om,
    org_ankhmorpork,
    org_uu,
    org_citywatch,
    project_expo2010,
    project_expo2011,
    project_ai1,
    project_ai2,
    client_hex,
) -> SimpleNamespace:
    """Return All Discworld fixtures at once."""
    db_session.commit()
    return SimpleNamespace(**locals())


# XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
# --- Old fixtures, to be removed when tests are updated -------------------------------


TEST_DATA = {
    'users': {
        'testuser': {
            'name': "testuser",
            'fullname': "Test User",
        },
        'testuser2': {
            'name': "testuser2",
            'fullname': "Test User 2",
        },
        'test-org-owner': {
            'name': "test-org-owner",
            'fullname': "Test User 2",
        },
        'test-org-admin': {
            'name': "test-org-admin",
            'fullname': "Test User 3",
        },
    }
}


@pytest.fixture()
def new_user(db_session):
    user = User(**TEST_DATA['users']['testuser'])
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def new_user2(db_session):
    user = User(**TEST_DATA['users']['testuser2'])
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def new_user_owner(db_session):
    user = User(**TEST_DATA['users']['test-org-owner'])
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def new_user_admin(db_session):
    user = User(**TEST_DATA['users']['test-org-admin'])
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def new_organization(db_session, new_user_owner, new_user_admin):
    org = Organization(owner=new_user_owner, title="Test org", name='test-org')
    db_session.add(org)

    admin_membership = OrganizationMembership(
        organization=org, user=new_user_admin, is_owner=False, granted_by=new_user_owner
    )
    db_session.add(admin_membership)
    db_session.commit()
    return org


@pytest.fixture()
def new_team(db_session, new_user, new_organization):
    team = Team(title="Owners", organization=new_organization)
    db_session.add(team)
    team.users.append(new_user)
    db_session.commit()
    return team


@pytest.fixture()
def new_project(db_session, new_organization, new_user):
    project = Project(
        profile=new_organization.profile,
        user=new_user,
        title="Test Project",
        tagline="Test tagline",
        description="Test description",
        location="Test Location",
    )
    db_session.add(project)
    db_session.commit()
    return project


@pytest.fixture()
def new_project2(db_session, new_organization, new_user_owner):
    project = Project(
        profile=new_organization.profile,
        user=new_user_owner,
        title="Test Project",
        tagline="Test tagline",
        description="Test description",
        location="Test Location",
    )
    db_session.add(project)
    db_session.commit()
    return project


@pytest.fixture()
def new_main_label(db_session, new_project):
    main_label_a = Label(
        title="Parent Label A", project=new_project, description="A test parent label"
    )
    new_project.all_labels.append(main_label_a)
    label_a1 = Label(title="Label A1", icon_emoji="👍", project=new_project)
    label_a2 = Label(title="Label A2", project=new_project)

    main_label_a.options.append(label_a1)
    main_label_a.options.append(label_a2)
    main_label_a.required = True
    main_label_a.restricted = True
    db_session.commit()

    return main_label_a


@pytest.fixture()
def new_main_label_unrestricted(db_session, new_project):
    main_label_b = Label(
        title="Parent Label B", project=new_project, description="A test parent label"
    )
    new_project.all_labels.append(main_label_b)
    label_b1 = Label(title="Label B1", icon_emoji="👍", project=new_project)
    label_b2 = Label(title="Label B2", project=new_project)

    main_label_b.options.append(label_b1)
    main_label_b.options.append(label_b2)
    main_label_b.required = False
    main_label_b.restricted = False
    db_session.commit()

    return main_label_b


@pytest.fixture()
def new_label(db_session, new_project):
    label_b = Label(title="Label B", icon_emoji="🔟", project=new_project)
    new_project.all_labels.append(label_b)
    db_session.add(label_b)
    db_session.commit()
    return label_b


@pytest.fixture()
def new_proposal(db_session, new_user, new_project):
    proposal = Proposal(
        user=new_user,
        project=new_project,
        title="Test Proposal",
        body="Test proposal description",
    )
    db_session.add(proposal)
    db_session.commit()
    return proposal
