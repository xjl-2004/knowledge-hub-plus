import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def _send(to: str, subject: str, text: str, html: str) -> None:
    if not settings.mail_host:
        logger.warning("SMTP 未配置，跳过邮件发送：%s", to)
        raise RuntimeError("SMTP 未配置")
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    kwargs = {
        "hostname": settings.mail_host,
        "port": settings.mail_port,
        "username": settings.mail_user,
        "password": settings.mail_pass,
        "timeout": 15,
    }
    if settings.mail_secure:
        kwargs["use_tls"] = True
    else:
        kwargs["start_tls"] = settings.mail_port == 587
    await aiosmtplib.send(message, **kwargs)


async def send_activation_email(email: str, username: str, token: str) -> None:
    link = f"{settings.app_public_url.rstrip('/')}/auth/verify-email?token={token}"
    await _send(
        email,
        "激活您的知识库账户",
        f"您好 {username}，请点击以下链接激活账户（24 小时内有效）：\n{link}",
        f"<p>您好 <strong>{username}</strong>，</p>"
        f"<p>欢迎注册知识库，请点击下方链接激活账户（24 小时内有效）：</p>"
        f'<p><a href="{link}">{link}</a></p>'
        f"<p>如非本人操作，请忽略此邮件。</p>",
    )


async def send_reset_code_email(email: str, username: str, code: str) -> None:
    await _send(
        email,
        "密码重置验证码",
        f"您好 {username}，您的密码重置验证码是：{code}，10 分钟内有效，请勿泄露。",
        f"<p>您好 <strong>{username}</strong>，</p>"
        f"<p>您正在重置密码，验证码为：</p>"
        f'<p style="font-size:24px;font-weight:bold;letter-spacing:4px;">{code}</p>'
        f"<p>验证码 10 分钟内有效，请勿泄露给他人。</p>"
        f"<p>如非本人操作，请忽略此邮件。</p>",
    )
