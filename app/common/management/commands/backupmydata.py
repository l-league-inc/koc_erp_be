from django.core.management import BaseCommand
from django.conf import settings
import boto3


class Command(BaseCommand):
    def handle(self, *args, **options):
        session = boto3.Session()
        s3_client = session.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_KEY,
        )
        bucket_name = settings.AWS_UPLOAD_BUCKET
        backup_file_name = f"db.json"
        object_key = f"backup/db.json"
        # upload
        s3_client.upload_file(backup_file_name, bucket_name, object_key)
        self.stdout.write(self.style.SUCCESS(f"Backup file {backup_file_name} uploaded to {bucket_name} successfully."))