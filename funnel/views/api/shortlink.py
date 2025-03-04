"""API view for creating a shortlink to any content on the website."""

from furl import furl

from baseframe import _
from coaster.utils import getbool
from coaster.views import requestform

from ... import app, shortlinkapp
from ...auth import current_auth
from ...models import Shortlink, db
from ..helpers import app_url_for, validate_is_app_url


# Add future hasjobapp route here
@app.route('/api/1/shortlink/create', methods=['POST'])
@requestform('url', ('shorter', getbool), 'name')
def create_shortlink(
    url: str | furl, shorter: bool = True, name: str | None = None
) -> tuple[dict[str, str], int]:
    """Create a shortlink that's valid for URLs in the app."""
    # Validate URL to be local before allowing a shortlink to it.
    if url:
        url = furl(url)
    if not url or not validate_is_app_url(url):
        return {
            'status': 'error',
            'error': 'url_invalid',
            'error_description': _("This URL is not valid for a shortlink"),
        }, 422
    if name:
        if not current_auth.user or not current_auth.user.is_site_editor:
            return {
                'status': 'error',
                'error': 'unauthorized',
                'error_description': _("A custom name requires special authorization"),
            }, 403
        try:
            sl = Shortlink.new(url, shorter=shorter, name=name, actor=current_auth.user)
        except ValueError:
            existing = Shortlink.get(name)
            # existing will be None if the internal record is marked as disabled
            if existing is None or str(existing.url) != str(url):
                return {
                    'status': 'error',
                    'error': 'unavailable',
                    'error_description': _("This name is not available"),
                }, 422
            sl = existing  # Return existing if it's a match
    else:
        sl = Shortlink.new(url, shorter=shorter, reuse=True)
    status_code = 201 if sl.is_new else 200
    db.session.add(sl)
    db.session.commit()
    return {
        'status': 'ok',
        'shortlink': app_url_for(shortlinkapp, 'link', name=sl.name, _external=True),
        'url': str(url),
    }, status_code
