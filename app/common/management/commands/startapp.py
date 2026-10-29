import os
from django.core.management.commands.startapp import Command as StartAppCommand


class Command(StartAppCommand):
    help = "Creates a Django app with custom structure (api.py, inbound.py, outbound.py, utils.py)"

    def handle(self, **options):
        # 기본 startapp 실행
        super().handle(**options)

        # 생성된 앱 디렉토리 경로
        app_name = options.get("name")
        target = options.get("directory") or app_name

        # tests.py 삭제 (tests/ 디렉토리를 사용)
        tests_file = os.path.join(target, "tests.py")
        if os.path.exists(tests_file):
            os.remove(tests_file)
            self.stdout.write(f"  - Removed tests.py")

        # tests 디렉토리 생성
        self._create_tests_directory(target, app_name)

        # 추가 파일 생성
        self._create_additional_files(target, app_name)

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created app "{app_name}" with custom structure'
            )
        )

    def _create_tests_directory(self, app_path: str, app_name: str) -> None:
        """tests 디렉토리와 테스트 파일들을 생성"""
        tests_dir = os.path.join(app_path, "tests")

        if not os.path.exists(tests_dir):
            os.makedirs(tests_dir)
            self.stdout.write(f"  - Created tests/ directory")

        # __init__.py 생성
        init_file = os.path.join(tests_dir, "__init__.py")
        with open(init_file, "w", encoding="utf-8") as f:
            f.write("")
        self.stdout.write(f"  - Created tests/__init__.py")

        # test_apis.py 생성
        test_apis_file = os.path.join(tests_dir, "test_apis.py")
        with open(test_apis_file, "w", encoding="utf-8") as f:
            f.write(self._get_test_template(app_name))
        self.stdout.write(f"  - Created tests/test_apis.py")

    def _create_additional_files(self, app_path: str, app_name: str) -> None:
        """프로젝트 구조에 맞는 추가 파일들을 생성"""

        files = {
            "api.py": self._get_api_template(app_name),
            "inbound.py": self._get_inbound_template(app_name),
            "outbound.py": self._get_outbound_template(app_name),
            "utils.py": self._get_utils_template(app_name),
        }

        for filename, content in files.items():
            filepath = os.path.join(app_path, filename)
            if not os.path.exists(filepath):
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                self.stdout.write(f"  - Created {filename}")

    def _get_api_template(self, app_name: str) -> str:
        """api.py 템플릿"""
        model_name = app_name.capitalize()
        return f"""from ninja import Router, Query
from ninja.pagination import paginate
from api.security import jwt_auth, admin_auth
from typing import List
from asgiref.sync import sync_to_async

from {app_name}.models import {model_name}
from {app_name}.inbound import {model_name}CreateSchema, {model_name}FilterSchema
from {app_name}.outbound import {model_name}ResponseSchema
from {app_name}.utils import get_{app_name}_by_id

router = Router(tags=["{model_name}"])


@router.post(
    "",
    summary="[C] {model_name} 생성",
    description="{model_name}을(를) 생성합니다.",
    response={{200: {model_name}ResponseSchema}},
    auth=jwt_auth,
)
async def create_{app_name}(request, payload: {model_name}CreateSchema):
    {app_name} = await {model_name}.objects.acreate(**payload.dict())
    return {app_name}


@router.get(
    "",
    summary="[C] {model_name} 목록 조회",
    description="{model_name} 목록을 조회합니다.",
    response={{200: List[{model_name}ResponseSchema]}},
    auth=jwt_auth,
)
@paginate
async def get_{app_name}_list(request, filters: {model_name}FilterSchema = Query(...)):

    @sync_to_async
    def apply_filters():
        queryset = {model_name}.objects.all()
        queryset = filters.filter(queryset)
        return list(queryset)

    queryset = await apply_filters()
    return queryset


@router.get(
    "/{{int:{app_name}_id}}",
    summary="[C] {model_name} 상세 조회",
    description="{model_name} 상세 정보를 조회합니다.",
    response={{200: {model_name}ResponseSchema}},
    auth=jwt_auth,
)
async def get_{app_name}_detail(request, {app_name}_id: int):
    {app_name} = await get_{app_name}_by_id({app_name}_id)
    return {app_name}


@router.patch(
    "/{{int:{app_name}_id}}",
    summary="[C] {model_name} 수정",
    description="{model_name}을(를) 수정합니다.",
    response={{200: {model_name}ResponseSchema}},
    auth=jwt_auth,
)
async def update_{app_name}(request, {app_name}_id: int, payload: {model_name}CreateSchema):
    {app_name} = await get_{app_name}_by_id({app_name}_id)
    for key, value in payload.dict(exclude_unset=True).items():
        setattr({app_name}, key, value)
    await {app_name}.asave()
    return {app_name}


@router.delete(
    "/{{int:{app_name}_id}}",
    summary="[C] {model_name} 삭제",
    description="{model_name}을(를) 삭제합니다.",
    response={{204: None}},
    auth=jwt_auth,
)
async def delete_{app_name}(request, {app_name}_id: int):
    {app_name} = await get_{app_name}_by_id({app_name}_id)
    await {app_name}.adelete()
    return 204, None
"""

    def _get_inbound_template(self, app_name: str) -> str:
        """inbound.py 템플릿"""
        model_name = app_name.capitalize()
        return f'''from api.metaclass import CustomModelSchema, Schema
from ninja import FilterSchema
from {app_name}.models import {model_name}
from typing import Optional
from pydantic import Field


class {model_name}CreateSchema(CustomModelSchema):
    """
    {model_name} 생성/수정 요청 스키마
    """
    # TODO: 필드 정의
    # example_field: str = Field(..., description="예시 필드")

    class Meta:
        model = {model_name}
        exclude = [
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
        ]


class {model_name}FilterSchema(FilterSchema):
    """
    {model_name} 필터링 스키마
    """
    # TODO: 필터 필드 정의
    # name: Optional[str] = Field(None, q="name__icontains")
    pass
'''

    def _get_outbound_template(self, app_name: str) -> str:
        """outbound.py 템플릿"""
        model_name = app_name.capitalize()
        return f'''from ninja import ModelSchema, Field
from {app_name}.models import {model_name}


class {model_name}ResponseSchema(ModelSchema):
    """
    {model_name} 응답 스키마
    """

    class Meta:
        model = {model_name}
        fields = "__all__"
'''

    def _get_utils_template(self, app_name: str) -> str:
        """utils.py 템플릿"""
        model_name = app_name.capitalize()
        return f'''from {app_name}.models import {model_name}
from ninja.errors import HttpError


async def get_{app_name}_by_id({app_name}_id: int) -> {model_name}:
    """
    ID로 {model_name}을(를) 조회합니다.

    Args:
        {app_name}_id: {model_name} ID

    Returns:
        {model_name} 인스턴스

    Raises:
        HttpError: {model_name}을(를) 찾을 수 없는 경우
    """
    try:
        {app_name} = await {model_name}.objects.aget(id={app_name}_id)
    except {model_name}.DoesNotExist:
        raise HttpError(404, "{model_name}을(를) 찾을 수 없습니다.")
    return {app_name}
'''

    def _get_test_template(self, app_name: str) -> str:
        """test_apis.py 템플릿"""
        model_name = app_name.capitalize()
        return f'''from django.test import TestCase
from django.contrib.auth import get_user_model
from ninja.testing import TestAsyncClient

from {app_name}.api import router
from {app_name}.models import {model_name}

User = get_user_model()


class Test{model_name}(TestCase):
    """
    {model_name} API 테스트
    """

    def setUp(self):
        """테스트 초기 설정"""
        self.client = TestAsyncClient(router)

        # 테스트 유저 생성
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="password1234!",
            phone_number="01011112222",
        )

        # 관리자 유저 생성
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="password1234!",
            phone_number="01099999999",
        )

        # 테스트 데이터 생성
        # TODO: 실제 모델에 맞게 수정
        # self.{app_name} = {model_name}.objects.create(
        #     # 필드 설정
        # )

    async def test_create_{app_name}(self):
        """
        {model_name} 생성 테스트
        """
        # TODO: 테스트 구현
        pass

    async def test_get_{app_name}_list(self):
        """
        {model_name} 목록 조회 테스트
        """
        # TODO: 테스트 구현
        pass

    async def test_get_{app_name}_detail(self):
        """
        {model_name} 상세 조회 테스트
        """
        # TODO: 테스트 구현
        pass

    async def test_update_{app_name}(self):
        """
        {model_name} 수정 테스트
        """
        # TODO: 테스트 구현
        pass

    async def test_delete_{app_name}(self):
        """
        {model_name} 삭제 테스트
        """
        # TODO: 테스트 구현
        pass
'''
