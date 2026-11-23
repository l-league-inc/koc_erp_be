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

### KOC Drive

버전을 넣어 Windows 실행 파일을 만듭니다. 번호를 생략하면 프로젝트에 적힌 버전을 씁니다.

```
make drive VERSION=1.4.0
```

결과물은 `clients/koc-drive/dist/KocDrive-win-x64.zip`입니다. 압축 안에는 `KOC ERP.exe`만 있습니다.

### Deploy on railway
