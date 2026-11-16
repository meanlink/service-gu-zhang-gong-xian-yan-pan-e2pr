from pydantic import BaseModel, Field


class CalibrationSchemeInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    reference_service: str = Field(min_length=1, max_length=80)
    note: str = Field(default='', max_length=500)


class CalibrationCredentialInput(BaseModel):
    source_service: str = Field(min_length=1, max_length=80)
    target_service: str = Field(min_length=1, max_length=80)
    lower_min: float
    upper_min: float
    note: str = Field(default='', max_length=300)


class CredentialRevocationInput(BaseModel):
    reason: str = Field(default='', max_length=500)


class SchemeRevocationInput(BaseModel):
    reason: str = Field(default='', max_length=500)
