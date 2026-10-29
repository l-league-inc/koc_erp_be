### KOC ERP Back-End API Server


### Project Setting

```
{
  "SECRET_KEY": "django-secret-key",
  "DEBUG": "True",
  "DB_HOST": "db",
  "DB_NAME": "devdb",
  "DB_USER": "devuser",
  "DB_PASSWORD": "password1234!",
  "DJANGO_ALLOWED_HOSTS": "*",
  "AWS_UPLOAD_BUCKET": "bucket-name",
  "AWS_REGION": "region-name",
  "AWS_ACCESS_KEY_ID": "aws-access-key-id",
  "AWS_SECRET_KEY": "aws-secret-key"
}
```

### schema save img

```
cd app
```


```
python manage.py graph_models --pygraphviz -a --group-models -o schema.jpg --exclude-models Session,AbstractBaseSession,Group,Permission,CommonModel,ContentType,LogEntry,Jwt,AbstractUser,BannerPriority,Banner --layout dot --arrow-shape normal --rankdir LR
```


### Schema

```
[tool.poetry.group.dev.dependencies]
pre-commit = "^3.8.0"
django-extensions = "^3.2.3"
pygraphviz = "^1.14"
```

```
python manage.py graph_models --pygraphviz -a --group-models -o schema.jpg --exclude-models Session,AbstractBaseSession,Group,Permission,CommonModel,ContentType,LogEntry,Jwt,AbstractUser,BannerPriority,Banner --layout dot --arrow-shape normal --rankdir LR
```

### Deploy on railway
