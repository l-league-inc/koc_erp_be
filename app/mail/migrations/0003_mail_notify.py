from django.db import migrations, models

import mail.models


class Migration(migrations.Migration):

    dependencies = [
        ("mail", "0002_naver_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="usermailaccount",
            name="notify_importances",
            field=models.JSONField(
                default=mail.models.default_notify_importances,
                help_text="알림을 받을 중요도. urgent, normal, low",
            ),
        ),
        migrations.AddField(
            model_name="usermailaccount",
            name="inbox_uidvalidity",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="받은편지함 UIDVALIDITY. 바뀌면 커서를 다시 잡습니다.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="usermailaccount",
            name="inbox_last_uid",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="알림을 처리한 마지막 받은편지함 UID",
                null=True,
            ),
        ),
    ]
