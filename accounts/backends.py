from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from common.phone_numbers import normalize_phone_number


class EmailOrUsernameModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()

        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        lookup = Q(username__iexact=username) | Q(email__iexact=username)
        if "@" not in username and not any(character.isalpha() for character in username):
            phone = normalize_phone_number(username)
            if phone:
                lookup |= Q(phone=phone)

        try:
            user = UserModel._default_manager.get(lookup)
        except UserModel.DoesNotExist:
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            user = (
                UserModel._default_manager.filter(
                    lookup
                )
                .order_by("id")
                .first()
            )

        if user is not None and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None