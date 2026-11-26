from django.core.mail import send_mail
from django.core.mail.backends.smtp import EmailBackend
from . import config


def send(subject: str, message: str, smtp_config: dict = None):
    """Sends one mail. TLS = STARTTLS on a plain connection (port 587 or 2525); SSL = an encrypted connection from the
    start (port 465). HikeAndMap: SSL added - smtp2go and others accept both; only one of the two may be on."""
    if not smtp_config:
        smtp_config = config.load()

    use_ssl = bool(smtp_config.get('smtp_use_ssl'))
    email_backend = EmailBackend(
        host=smtp_config.get('smtp_server'),
        port=smtp_config.get('smtp_port'),
        username=smtp_config.get('smtp_username'),
        password=smtp_config.get('smtp_password'),
        use_tls=bool(smtp_config.get('smtp_use_tls')) and not use_ssl,
        use_ssl=use_ssl,
        timeout=20,
    )

    send_mail(
        subject,
        message,
        smtp_config.get('smtp_from_address'),
        [smtp_config.get('smtp_to_address')],
        connection=email_backend,
        auth_user=smtp_config.get('smtp_username'),
        auth_password=smtp_config.get('smtp_password'),
        fail_silently=False
    )
