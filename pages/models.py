from django.db import models


class ContactMessage(models.Model):
    name = models.CharField("nombre", max_length=150)
    email = models.EmailField("correo electrónico")
    subject = models.CharField("asunto", max_length=200)
    message = models.TextField("mensaje")
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField("atendido", default=False)

    class Meta:
        verbose_name = "mensaje de contacto"
        verbose_name_plural = "mensajes de contacto"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} — {self.name}"
