import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


class Address(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuario",
        related_name="addresses", on_delete=models.CASCADE,
    )
    full_name = models.CharField("nombre completo", max_length=150)
    phone = models.CharField("teléfono", max_length=30)
    street_address = models.CharField("dirección", max_length=200)
    apartment = models.CharField("piso / puerta (opcional)", max_length=100, blank=True)
    postal_code = models.CharField("código postal", max_length=10)
    city = models.CharField("ciudad", max_length=100)
    province = models.CharField("provincia", max_length=100)
    country = models.CharField("país", max_length=100, default="España")
    is_default = models.BooleanField("dirección predeterminada", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "dirección"
        verbose_name_plural = "direcciones"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.full_name} — {self.street_address}, {self.city}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Address.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)


class LoginCode(models.Model):
    """A one-time 6-digit code emailed to prove control of an inbox — used
    both for passwordless login and for a guest linking a past order to a
    (possibly brand new) account. The code itself is hashed like a password:
    short-lived and single-use, but no reason to keep it readable in the DB."""

    VALID_MINUTES = 10
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60

    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "código de acceso"
        verbose_name_plural = "códigos de acceso"

    def __str__(self):
        return f"Código para {self.email}"

    @classmethod
    def cooldown_active(cls, email):
        cutoff = timezone.now() - timedelta(seconds=cls.RESEND_COOLDOWN_SECONDS)
        return cls.objects.filter(email=email, created_at__gte=cutoff).exists()

    @classmethod
    def issue(cls, email):
        """Create a new code and return (LoginCode, plaintext_code). The
        plaintext only ever exists in memory long enough to email it."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        obj = cls.objects.create(
            email=email,
            code_hash=make_password(code),
            expires_at=timezone.now() + timedelta(minutes=cls.VALID_MINUTES),
        )
        return obj, code

    def is_usable(self):
        return not self.consumed_at and self.attempts < self.MAX_ATTEMPTS and timezone.now() < self.expires_at

    def verify(self, code):
        """One attempt, whether right or wrong, always counts — including
        against an expired/already-consumed code, so a stolen code_id can't
        be replayed to keep probing after it should be dead."""
        if not self.is_usable():
            return False
        self.attempts += 1
        matched = check_password(code, self.code_hash)
        if matched:
            self.consumed_at = timezone.now()
        self.save(update_fields=["attempts", "consumed_at"])
        return matched
