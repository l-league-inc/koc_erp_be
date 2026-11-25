from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mail", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usermailaccount",
            name="provider",
            field=models.CharField(
                choices=[("daum", "Daum"), ("naver", "Naver")],
                default="daum",
                help_text="메일 제공자",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="usermailaccount",
            name="username",
            field=models.CharField(help_text="메일 로그인 아이디", max_length=255),
        ),
    ]
