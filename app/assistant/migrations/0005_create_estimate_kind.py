from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0004_send_mail_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="proposedaction",
            name="kind",
            field=models.CharField(
                choices=[
                    ("create_record", "레코드 생성"),
                    ("update_record", "레코드 수정"),
                    ("create_skill", "스킬 생성"),
                    ("update_skill", "스킬 수정"),
                    ("send_mail", "메일 발송"),
                    ("create_estimate", "견적서 작성"),
                ],
                help_text="동작",
                max_length=20,
            ),
        ),
    ]
