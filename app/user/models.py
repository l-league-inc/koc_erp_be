from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager
from django.apps import apps
from django.contrib import auth
from django.contrib.auth.hashers import make_password

from user.nickname_utils import generate_unique_nickname, is_missing_nickname


class CustomUserManager(UserManager):
    """Custom User Manager Definition"""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Create and save a user with the given email, email, and password.
        """
        if not email:
            raise ValueError("The given email must be set")
        # Lookup the real model class from the global app registry so this
        # manager method can be used in migrations. This is fine because
        # managers are by definition working on the real model.
        GlobalUserModel = apps.get_model(
            self.model._meta.app_label, self.model._meta.object_name
        )
        email = GlobalUserModel.normalize_username(email)
        if is_missing_nickname(extra_fields.get("nickname")):
            extra_fields["nickname"] = generate_unique_nickname()
        user = self.model(email=email, **extra_fields)
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_admin_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(
            email,
            password,
            permission_type=User.UserPermissionTypeChoices.ADMIN,
            **extra_fields,
        )

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(
            email,
            password,
            permission_type=User.UserPermissionTypeChoices.ADMIN,
            **extra_fields,
        )

    def with_perm(
        self, perm, is_active=True, include_superusers=True, backend=None, obj=None
    ):
        if backend is None:
            backends = auth._get_backends(return_tuples=True)
            if len(backends) == 1:
                backend, _ = backends[0]
            else:
                raise ValueError(
                    "You have multiple authentication backends configured and "
                    "therefore must provide the `backend` argument."
                )
        elif not isinstance(backend, str):
            raise TypeError(
                "backend must be a dotted import path string (got %r)." % backend
            )
        else:
            backend = auth.load_backend(backend)
        if hasattr(backend, "with_perm"):
            return backend.with_perm(
                perm,
                is_active=is_active,
                include_superusers=include_superusers,
                obj=obj,
            )
        return self.none()


class User(AbstractUser):
    """Custom User Model Definition"""

    objects = CustomUserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class LoginMethodChoices(models.TextChoices):
        EMAIL = ("email", "이메일")
        KAKAO = ("kakao", "카카오")
        GOOGLE = ("google", "구글")
        TOSS = ("toss", "토스")
        APPLE = ("apple", "애플")

    class UserTypeChoices(models.TextChoices):
        MEMBER = ("member", "회원")

    class UserPermissionTypeChoices(models.TextChoices):
        ADMIN = ("admin", "관리자")
        CUSTOMER = ("customer", "고객")

    class UserStatusChoice(models.TextChoices):
        ACTIVE = ("A", "활성유저")
        INACTIVE = ("I", "미인증유저")
        WITHDRAW = ("W", "탈퇴유저")
        SUSPENDED = ("S", "정지유저")
        DORMANT = ("D", "휴면유저")

    class AddressTypeChoices(models.TextChoices):
        ROAD = "도로명", "도로명"
        JIBUN = "지번", "지번"

    login_method = models.CharField(
        max_length=10,
        choices=LoginMethodChoices.choices,
        default=LoginMethodChoices.EMAIL,
        help_text="로그인 방식",
    )
    type = models.CharField(
        max_length=10,
        choices=UserTypeChoices.choices,
        default=UserTypeChoices.MEMBER,
        help_text="회원 유형",
    )
    permission_type = models.CharField(
        max_length=10,
        choices=UserPermissionTypeChoices.choices,
        default=UserPermissionTypeChoices.CUSTOMER,
        help_text="회원 권한",
    )
    status = models.CharField(
        max_length=10,
        choices=UserStatusChoice.choices,
        default=UserStatusChoice.INACTIVE,
        help_text="회원 유형",
    )
    email = models.EmailField(max_length=254, unique=True, help_text="이메일")
    username = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        editable=False,
    )
    social_username = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="소셜 로그인 아이디",
    )
    social_email = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="소셜 로그인 이메일",
    )
    social_user_id = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="소셜 로그인 유저 아이디",
    )
    name = models.CharField(max_length=30, blank=True, null=True, help_text="이름")
    phone_number = models.CharField(
        max_length=20, blank=True, null=True, help_text="전화번호"
    )
    nickname = models.CharField(
        max_length=30, blank=True, null=True, help_text="닉네임"
    )
    profile_image = models.CharField(
        max_length=200, blank=True, null=True, help_text="프로필 이미지"
    )
    first_name = models.CharField(
        max_length=150,
        editable=False,
    )
    last_name = models.CharField(
        max_length=150,
        editable=False,
    )
    address_type = models.CharField(
        max_length=20,
        choices=AddressTypeChoices.choices,
        blank=True,
        null=True,
        help_text="주소 타입",
    )
    postal_code = models.CharField(
        max_length=20, blank=True, default="", help_text="우편번호"
    )
    address = models.CharField(max_length=200, blank=True, default="", help_text="주소")
    address_detail = models.CharField(
        max_length=200, blank=True, default="", help_text="상세주소"
    )

    birth_date = models.DateField(blank=True, null=True, help_text="생년월일")
    marketing_agree = models.BooleanField(default=False, help_text="마케팅 수신 동의")
    groups = models.ManyToManyField(
        "auth.Group",
        related_name="custom_user_set",  # change this related_name
        blank=True,
        help_text="The groups this user belongs to.",
        verbose_name="groups",
    )

    user_permissions = models.ManyToManyField(
        "auth.Permission",
        related_name="custom_user_permissions_set",  # change this related_name
        blank=True,
        help_text="Specific permissions for this user.",
        verbose_name="user permissions",
    )
    fcm_token = models.CharField(
        max_length=255, blank=True, null=True, help_text="FCM 토큰"
    )
    device_token = models.CharField(
        max_length=255, blank=True, null=True, help_text="디바이스 토큰"
    )
    push_notification = models.BooleanField(default=True, help_text="푸시알림")
    withdraw_at = models.DateTimeField(blank=True, null=True, help_text="탈퇴일시")
    withdraw_reason = models.CharField(
        max_length=500, blank=True, null=True, help_text="탈퇴사유"
    )
    is_withdrawn = models.BooleanField(default=False, help_text="탈퇴 여부")
    # toss
    toss_user_key = models.BigIntegerField(
        blank=True,
        null=True,
        unique=True,
        help_text="토스 사용자 키",
    )
    toss_access_token = models.TextField(
        blank=True,
        null=True,
        help_text="토스 액세스 토큰",
    )
    toss_refresh_token = models.TextField(
        blank=True,
        null=True,
        help_text="토스 리프레시 토큰",
    )
    toss_ci = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="토스 CI (연계정보)",
    )
    # is employee
    is_employee = models.BooleanField(default=False, help_text="직원 여부")

    def __str__(self):
        return f"{self.email}({self.id})"

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()

    def clean(self):
        """
        Admin에서 저장할 때 이메일 형식 검증을 건너뜀.
        소셜 로그인 유저는 이메일 필드에 고유 식별자가 저장될 수 있기 때문.
        """
        # 부모 클래스의 clean()을 호출하되 ValidationError는 무시
        from django.core.exceptions import ValidationError

        try:
            super().clean()
        except ValidationError as e:
            # 이메일 필드의 검증 에러만 필터링해서 무시
            if "email" in e.error_dict:
                e.error_dict.pop("email")
            if e.error_dict:  # 다른 에러가 있으면 다시 발생
                raise

    class Meta:
        verbose_name_plural = "Users"
        ordering = ["-date_joined"]
        constraints = [
            models.UniqueConstraint(
                fields=["email"],
                condition=models.Q(withdraw_at__isnull=True),
                name="unique_email_type",
            )
        ]


class Jwt(models.Model):
    user = models.ForeignKey(
        User, related_name="login_user", on_delete=models.CASCADE, help_text="회원"
    )
    access = models.TextField(help_text="Access Token")
    refresh = models.TextField(help_text="Refresh Token")


class PasswordEmailVerification(models.Model):
    user = models.ForeignKey(
        "user.User",
        related_name="email_verification_user",
        on_delete=models.CASCADE,
        help_text="회원",
    )
    token = models.TextField(help_text="이메일 인증 토큰")
    is_verified = models.BooleanField(default=False, help_text="인증 여부")
    verified_at = models.DateTimeField(null=True, blank=True, help_text="인증일시")
    created_at = models.DateTimeField(auto_now_add=True, help_text="생성일시")
