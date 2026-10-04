"""Strict external request models; stored records use the same validated shape."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator, model_validator


ShortText = Annotated[str, Field(max_length=100)]
Symptom = Annotated[str, Field(min_length=1, max_length=40)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Credentials(ApiModel):
    username: str = Field(min_length=3, max_length=40)
    password: SecretStr = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,40}", value, flags=re.ASCII):
            raise ValueError("用户名须为 3–40 位英文字母、数字或下划线")
        return value


class RegisterInput(Credentials):
    display_name: str = Field(min_length=1, max_length=40)
    consent: StrictBool

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("昵称不能为空")
        return value.strip()

    @field_validator("consent")
    @classmethod
    def require_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("请先同意健康信息存储说明")
        return value


class DeleteAccountInput(ApiModel):
    password: SecretStr = Field(min_length=10, max_length=128)


class User(ApiModel):
    id: str
    username: str
    display_name: str
    created_at: str


class AuthResult(ApiModel):
    user: User
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: str


class Vitals(ApiModel):
    temperature: float | None = Field(default=None, ge=30, le=45)
    heart_rate: Annotated[int, Field(strict=True, ge=20, le=250)] | None = None
    spo2: Annotated[int, Field(strict=True, ge=50, le=100)] | None = None

    @field_validator("temperature", mode="before")
    @classmethod
    def reject_non_numbers(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("体温须为数值")
        return value


class Medication(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    dose: ShortText = ""
    frequency: ShortText = ""

    @field_validator("name", "dose", "frequency")
    @classmethod
    def clean_text(cls, value: str, info) -> str:
        value = value.strip()
        if info.field_name == "name" and not value:
            raise ValueError("用药名称不能为空")
        return value


class EpisodeInput(ApiModel):
    chief_complaint: str = Field(min_length=1, max_length=200)
    symptoms: list[Symptom] = Field(default_factory=list, max_length=20)
    severity: int = Field(ge=1, le=5, strict=True)
    started_at: date
    ended_at: date | None = None
    status: Literal["ongoing", "ended"] = "ongoing"
    outcome: Literal["ongoing", "improving", "resolved", "worsened"] = "ongoing"
    vitals: Vitals = Field(default_factory=Vitals)
    medications: list[Medication] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=3000)

    @field_validator("chief_complaint", "notes")
    @classmethod
    def clean_text(cls, value: str, info) -> str:
        value = value.strip()
        if info.field_name == "chief_complaint" and not value:
            raise ValueError("请填写主要不适")
        return value

    @field_validator("symptoms")
    @classmethod
    def clean_symptoms(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("症状名称不能为空")
        return list(dict.fromkeys(cleaned))

    @field_validator("started_at", "ended_at", mode="before")
    @classmethod
    def require_date_string(cls, value):
        if value is not None and not isinstance(value, date):
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value, flags=re.ASCII):
                raise ValueError("日期格式须为 YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def validate_dates(self):
        today = datetime.now(timezone(timedelta(hours=8))).date()
        if self.started_at > today or (self.ended_at and self.ended_at > today):
            raise ValueError("日期不能晚于今天（北京时间）")
        if self.ended_at and self.ended_at < self.started_at:
            raise ValueError("结束日期不能早于开始日期")
        if self.status == "ended" and self.ended_at is None:
            raise ValueError("已结束的记录须填写结束日期")
        if self.status == "ongoing" and self.ended_at is not None:
            raise ValueError("进行中的记录不能填写结束日期")
        return self


class EpisodeUpdate(EpisodeInput):
    version: int = Field(ge=1, strict=True)


class EpisodeDetail(EpisodeInput):
    id: str
    version: int
    created_at: str
    updated_at: str
    analysis: dict
