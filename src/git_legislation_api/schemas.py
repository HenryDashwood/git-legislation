"""Pydantic response models for the read API."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DocumentSummary(BaseModel):
    id: str
    legislation_type: str
    year: str
    calendar_year: int | None = None
    number: str
    title: str
    document_uri: str
    status: str | None = None
    extent: str | None = None
    latest_version_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="ignore")


class VersionSummary(BaseModel):
    id: str
    document_id: str
    version_kind: str
    snapshot_date: date | None = None
    source_uri: str | None = None
    source_object_key: str | None = None
    markdown_object_key: str | None = None
    word_count: int
    is_metadata_only: bool
    created_at: datetime

    model_config = ConfigDict(extra="ignore")


class DocumentDetail(DocumentSummary):
    latest_version: VersionSummary | None = None


class ProvisionSummary(BaseModel):
    id: str
    version_id: str
    document_id: str
    ordinal: int
    provision_type: str | None = None
    number: str | None = None
    heading: str
    anchor: str

    model_config = ConfigDict(extra="ignore")


class ProvisionDetail(ProvisionSummary):
    markdown: str
    plain_text: str


class FileSummary(BaseModel):
    id: int
    document_id: str
    version_id: str | None = None
    file_kind: str
    source_url: str | None = None
    object_key: str | None = None
    sha256: str | None = None
    is_canonical: bool
    bucket: str | None = None
    byte_size: int | None = None
    content_type: str | None = None
    object_sha256: str | None = None
    created_at: datetime

    model_config = ConfigDict(extra="ignore")


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    limit: int
    offset: int


class VersionListResponse(BaseModel):
    items: list[VersionSummary]


class ProvisionListResponse(BaseModel):
    items: list[ProvisionSummary]


class FileListResponse(BaseModel):
    items: list[FileSummary]
