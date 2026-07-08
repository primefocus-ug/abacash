from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _


class EmailOrUsernameAuthenticationForm(AuthenticationForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Username or Email")
        self.fields["username"].widget.attrs.update(
            {
                "autofocus": True,
                "placeholder": _("Username or email address"),
            }
        )