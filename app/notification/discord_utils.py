import httpx
from django.conf import settings
from ninja.errors import HttpError
import logging

logger = logging.getLogger(__name__)


async def send_discord_message(content, embed=None, avatar_url=None):

    # Discord webhook URL이 설정되지 않은 경우 로그만 출력
    if not hasattr(settings, "DISCORD_WEBHOOK_URL") or not settings.DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook URL is not configured")
        return

    data = {
        "content": content,
    }
    if embed:
        data["embeds"] = [embed]
    if avatar_url:
        data["avatar_url"] = avatar_url

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(settings.DISCORD_WEBHOOK_URL, json=data)
            response.raise_for_status()
            logger.info("Discord message sent successfully")
        except httpx.HTTPStatusError as err:
            logger.error(
                f"Discord webhook error: {err.response.status_code} - {err.response.text}"
            )
            # 테스트나 개발 환경에서는 예외를 발생시키지 않고 로그만 출력
            if not settings.DEBUG:
                raise HttpError(
                    400, f"Discord notification failed: {err.response.status_code}"
                )
        except Exception as err:
            logger.error(f"Unexpected error sending Discord message: {str(err)}")
            if not settings.DEBUG:
                raise HttpError(500, "Discord notification failed")
