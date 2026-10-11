"""Strict external request models; stored records use the same validated shape."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator, model_validator


ShortText = Annotated[str, Field(max_length=100)]
Symptom = Annotated[str, Field(min_length=1, max_length=40)]
AssessmentQuestionId = Literal[
    "breathing_difficulty", "chest_pain", "confusion", "dehydration", "worsening",
    "exposure", "fever_persistent", "pregnancy", "immunosuppression", "medication_reaction",
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AssessmentAnswer(ApiModel):
    question_id: AssessmentQuestionId
    answer: Literal["yes", "no", "unknown"]


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


class AccountProfileInput(ApiModel):
    display_name: str = Field(min_length=1, max_length=40)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("昵称不能为空")
        return value.strip()


class RegisterInput(Credentials, AccountProfileInput):
    consent: StrictBool

    @field_validator("consent")
    @classmethod
    def require_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("请先同意健康信息存储说明")
        return value


class AccountPasswordInput(ApiModel):
    current_password: SecretStr = Field(min_length=10, max_length=128)
    new_password: SecretStr = Field(min_length=10, max_length=128)


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
    started_at: date | None = None
    ended_at: date | None = None
    adherence: Literal["unknown", "as_recorded", "missed"] = "unknown"
    response: Literal["unknown", "improving", "unchanged", "worsened"] = "unknown"
    notes: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def validate_course(self):
        today = datetime.now(timezone(timedelta(hours=8))).date()
        if any(day and day > today for day in (self.started_at, self.ended_at)):
            raise ValueError("用药日期不能晚于今天")
        if self.ended_at and not self.started_at:
            raise ValueError("填写用药结束日期时须同时填写开始日期")
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("用药结束日期不能早于开始日期")
        return self

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
    disease_category: Literal["unknown", "infectious", "hereditary", "other"] = "unknown"
    diagnosis_name: str = Field(default="", max_length=100)
    diagnosis_source: Literal["unknown", "self_report", "clinician"] = "unknown"
    infection_group: Literal["unspecified", "respiratory", "gastrointestinal"] = "unspecified"
    observation_ids: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(default_factory=list, max_length=100)
    assessment_answers: list[AssessmentAnswer] = Field(default_factory=list, max_length=12)

    @field_validator("assessment_answers")
    @classmethod
    def unique_assessment_answers(cls, values):
        if len({item.question_id for item in values}) != len(values):
            raise ValueError("同一补问不能重复回答")
        return values

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
        if self.infection_group != "unspecified" and self.disease_category != "infectious":
            raise ValueError("感染分组只适用于传染病记录")
        if self.diagnosis_source != "unknown" and not self.diagnosis_name.strip():
            raise ValueError("请填写对应的诊断名称")
        return self


class EpisodeUpdate(EpisodeInput):
    version: int = Field(ge=1, strict=True)


class EpisodeDetail(EpisodeInput):
    id: str
    version: int
    created_at: str
    updated_at: str
    analysis: dict


class RegionInput(ApiModel):
    province: str = Field(default="", max_length=60)
    city: str = Field(default="", max_length=60)
    district: str = Field(default="", max_length=60)
    code: str = Field(default="", max_length=100)
    label: str = Field(default="", max_length=200)


class HealthProfileInput(ApiModel):
    version: int = Field(ge=0, strict=True)
    birth_year: int | None = Field(default=None, ge=1900, le=2100, strict=True)
    chronic_conditions: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=30)
    family_history: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=30)
    region: RegionInput = Field(default_factory=RegionInput)
    regional_consent: StrictBool = False

    @field_validator("chronic_conditions", "family_history")
    @classmethod
    def clean_health_names(cls, values):
        names = list(dict.fromkeys(value.strip() for value in values))
        if any(not name for name in names):
            raise ValueError("健康信息名称不能为空")
        return names

    @field_validator("birth_year")
    @classmethod
    def valid_birth_year(cls, value):
        if value and value > datetime.now(timezone(timedelta(hours=8))).year:
            raise ValueError("出生年份不能晚于今年")
        return value


class ObservationInput(ApiModel):
    source: Literal["health_connect", "healthkit", "bluetooth", "manual"]
    source_id: str = Field(min_length=1, max_length=160)
    metric: Literal["heart_rate", "spo2", "temperature", "steps", "sleep_minutes",
                    "dietary_energy", "hydration", "active_energy", "basal_energy",
                    "hrv_sdnn", "hrv_rmssd", "vo2max",
                    "distance_run", "distance_cycle", "exercise_minutes"]
    value: float = Field(strict=True)
    unit: Literal["bpm", "%", "C", "count", "min", "kcal", "ml", "ms", "mL/kg/min", "m"]
    measured_at: datetime
    context: Literal["resting", "active", "unknown"] = "unknown"
    device_name: str = Field(default="", max_length=100)

    @field_validator("source_id")
    @classmethod
    def nonempty_source_id(cls, value):
        if not value.strip():
            raise ValueError("数据标识不能为空")
        return value.strip()

    @model_validator(mode="after")
    def validate_reading(self):
        limits = {"heart_rate": ("bpm", 20, 250), "spo2": ("%", 50, 100),
                  "temperature": ("C", 30, 45), "steps": ("count", 0, 200000), "sleep_minutes": ("min", 0, 1440),
                  "dietary_energy": ("kcal", 0, 10000), "hydration": ("ml", 0, 20000),
                  "active_energy": ("kcal", 0, 20000), "basal_energy": ("kcal", 0, 20000),
                  "hrv_sdnn": ("ms", 1, 500), "hrv_rmssd": ("ms", 1, 500),
                  "vo2max": ("mL/kg/min", 5, 100),
                  "distance_run": ("m", 0, 200000), "distance_cycle": ("m", 0, 500000),
                  "exercise_minutes": ("min", 0, 1440)}
        unit, low, high = limits[self.metric]
        if self.unit != unit or not low <= self.value <= high:
            raise ValueError("测量单位或数值范围无效")
        if self.metric == "steps" and not self.value.is_integer():
            raise ValueError("步数须为整数")
        now = datetime.now(timezone.utc)
        if self.measured_at.tzinfo is None or self.measured_at.utcoffset() is None:
            raise ValueError("测量时间须包含时区")
        if self.measured_at > now + timedelta(minutes=5) or self.measured_at.year < 1990:
            raise ValueError("测量时间无效")
        self.measured_at = self.measured_at.astimezone(timezone.utc)
        return self


class ObservationImport(ApiModel):
    items: list[ObservationInput] = Field(min_length=1, max_length=500)


class IntakeDraft(ApiModel):
    """Server-canonical shape for a conversation-guided draft episode.

    Every field is optional; the service sanitizes before trusting any value and
    the client only ever fills what a validated model turn returned.
    """

    chief_complaint: str = Field(default="", max_length=200)
    symptoms: list[Symptom] = Field(default_factory=list, max_length=20)
    severity: Annotated[int, Field(strict=True, ge=1, le=5)] | None = None
    started_at: str = Field(default="", max_length=10)
    status: Literal["ongoing", "ended"] = "ongoing"
    ended_at: str = Field(default="", max_length=10)
    outcome: Literal["ongoing", "improving", "resolved", "worsened"] = "ongoing"
    notes: str = Field(default="", max_length=3000)
    disease_category: Literal["unknown", "infectious", "hereditary", "other"] = "unknown"
    diagnosis_name: str = Field(default="", max_length=100)
    diagnosis_source: Literal["unknown", "self_report", "clinician"] = "unknown"
    infection_group: Literal["unspecified", "respiratory", "gastrointestinal"] = "unspecified"
    vitals: Vitals = Field(default_factory=Vitals)

    @field_validator("symptoms")
    @classmethod
    def clean_intake_symptoms(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class IntakeTurnRequest(ApiModel):
    draft: IntakeDraft = Field(default_factory=IntakeDraft)
    message: str = Field(default="", max_length=500)
    turns: Annotated[int, Field(strict=True, ge=0, le=24)] = 0
    cloud_consent: StrictBool = False
    # Capture each utterance once; retries use the same context across midnight.
    client_time: datetime | None = None
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    timezone_offset_minutes: Annotated[int, Field(strict=True, ge=-840, le=840)] = 480

    @field_validator("client_time")
    @classmethod
    def aware_client_time(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("本轮时间必须包含时区")
        return value
