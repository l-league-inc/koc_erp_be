from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0003_record_icon_comment_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="database",
            name="section",
            field=models.CharField(blank=True, default="", help_text="페이지", max_length=100),
        ),
        migrations.AddField(
            model_name="database",
            name="section_slug",
            field=models.SlugField(blank=True, default="", help_text="페이지 키", max_length=50),
        ),
    ]
