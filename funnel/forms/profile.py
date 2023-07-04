"""Forms for user and organization accounts."""

from __future__ import annotations

from baseframe import __, forms

from ..models import Profile, User
from .helpers import image_url_validator, nullable_strip_filters
from .organization import OrganizationForm

__all__ = [
    'ProfileForm',
    'ProfileLogoForm',
    'ProfileBannerForm',
    'ProfileTransitionForm',
]


@Profile.forms('main')
class ProfileForm(OrganizationForm):
    """
    Edit a profile.

    A `profile` keyword argument is necessary for the ImgeeField.
    """

    __expects__ = ('profile', 'user')
    profile: Profile
    user: User

    tagline = forms.StringField(
        __("Bio"),
        validators=[forms.validators.Optional(), forms.validators.Length(max=160)],
        filters=nullable_strip_filters,
        description=__("A brief statement about your organization"),
    )
    description = forms.MarkdownField(
        __("Welcome message"),
        validators=[forms.validators.Optional()],
        description=__("Optional – This message will be shown on the account’s page"),
    )
    logo_url = forms.ImgeeField(
        label=__("Account image"),
        validators=[
            forms.validators.Optional(),
            forms.validators.Length(max=2000),
            image_url_validator(),
        ],
        filters=nullable_strip_filters,
    )
    website = forms.URLField(
        __("Website URL"),
        validators=[
            forms.validators.Optional(),
            forms.validators.Length(max=2000),
            forms.validators.URL(),
            forms.validators.ValidUrl(),
        ],
        filters=nullable_strip_filters,
    )

    def set_queries(self) -> None:
        """Prepare form for use."""
        self.logo_url.profile = self.profile.name

    def make_for_user(self) -> None:
        """Customise form for a user account."""
        self.title.label.text = __("Your name")
        self.title.description = __(
            "Your full name, in the form others can recognise you by"
        )
        self.tagline.description = __("A brief statement about yourself")
        self.name.description = __(
            "A single word that is uniquely yours, for your account page and @mentions."
            " Pick something permanent: changing it will break existing links"
        )
        self.description.label.text = __("More about you")
        self.description.description = __(
            "Optional – This message will be shown on the account’s page"
        )


@Profile.forms('transition')
class ProfileTransitionForm(forms.Form):
    """Form to transition an account between public and private state."""

    edit_obj: Profile

    transition = forms.SelectField(
        __("Account visibility"), validators=[forms.validators.DataRequired()]
    )

    def set_queries(self) -> None:
        """Prepare form for use."""
        self.transition.choices = list(self.edit_obj.state.transitions().items())


@Profile.forms('logo')
class ProfileLogoForm(forms.Form):
    """
    Form for profile logo.

    A `profile` keyword argument is necessary for the ImgeeField.
    """

    __expects__ = ('profile',)
    profile: Profile

    logo_url = forms.ImgeeField(
        __("Account image"),
        validators=[
            forms.validators.Optional(),
            forms.validators.Length(max=2000),
            image_url_validator(),
        ],
        filters=nullable_strip_filters,
    )

    def set_queries(self) -> None:
        """Prepare form for use."""
        self.logo_url.widget_type = 'modal'
        self.logo_url.profile = self.profile.name


@Profile.forms('banner_image')
class ProfileBannerForm(forms.Form):
    """
    Form for profile banner.

    A `profile` keyword argument is necessary for the ImgeeField.
    """

    __expects__ = ('profile',)
    profile: Profile

    banner_image_url = forms.ImgeeField(
        __("Banner image"),
        validators=[
            forms.validators.Optional(),
            forms.validators.Length(max=2000),
            image_url_validator(),
        ],
        filters=nullable_strip_filters,
    )

    def set_queries(self) -> None:
        """Prepare form for use."""
        self.banner_image_url.widget_type = 'modal'
        self.banner_image_url.profile = self.profile.name
