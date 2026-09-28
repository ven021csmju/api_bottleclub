from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class PromotionCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., max_length=255)
    subtitle: str | None = Field(None, max_length=255)
    description: str
    image_url: str = Field(..., alias="imageUrl")
    images: list[str] = Field(default_factory=list)
    hero_image_url: str | None = Field(None, alias="heroImageUrl")
    badge: str | None = Field("PROMOTION", max_length=100)
    discount_tag: str | None = Field(None, alias="discountTag", max_length=100)
    valid_until: str | None = Field(None, alias="validUntil", max_length=100)
    link_url: str | None = Field("/#products", alias="linkUrl", max_length=255)
    cta_text: str | None = Field("ดูสินค้าโปรโมชั่น", alias="ctaText", max_length=100)
    secondary_cta_text: str | None = Field(None, alias="secondaryCtaText", max_length=100)
    secondary_link_url: str | None = Field(None, alias="secondaryLinkUrl", max_length=255)
    is_featured: StrictBool = Field(False, alias="isFeatured")
    is_active: StrictBool = Field(True, alias="isActive")
    sort_order: StrictInt = Field(0, alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("title", "description", "image_url")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class PromotionUpdate(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    title: str | None = Field(None, max_length=255)
    subtitle: str | None = Field(None, max_length=255)
    description: str | None = None
    image_url: str | None = Field(None, alias="imageUrl")
    images: list[str] | None = None
    hero_image_url: str | None = Field(None, alias="heroImageUrl")
    badge: str | None = Field(None, max_length=100)
    discount_tag: str | None = Field(None, alias="discountTag", max_length=100)
    valid_until: str | None = Field(None, alias="validUntil", max_length=100)
    link_url: str | None = Field(None, alias="linkUrl", max_length=255)
    cta_text: str | None = Field(None, alias="ctaText", max_length=100)
    secondary_cta_text: str | None = Field(None, alias="secondaryCtaText", max_length=100)
    secondary_link_url: str | None = Field(None, alias="secondaryLinkUrl", max_length=255)
    is_featured: StrictBool | None = Field(None, alias="isFeatured")
    is_active: StrictBool | None = Field(None, alias="isActive")
    sort_order: StrictInt | None = Field(None, alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("title", "description", "image_url")
    @classmethod
    def non_blank_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class PromotionResponse(BaseModel):
    id: str
    title: str
    subtitle: str | None
    description: str
    image_url: str = Field(alias="imageUrl")
    images: list[str]
    hero_image_url: str | None = Field(alias="heroImageUrl")
    badge: str | None
    discount_tag: str | None = Field(alias="discountTag")
    valid_until: str | None = Field(alias="validUntil")
    link_url: str | None = Field(alias="linkUrl")
    cta_text: str | None = Field(alias="ctaText")
    secondary_cta_text: str | None = Field(alias="secondaryCtaText")
    secondary_link_url: str | None = Field(alias="secondaryLinkUrl")
    is_featured: bool = Field(alias="isFeatured")
    is_active: bool = Field(alias="isActive")
    sort_order: int = Field(alias="sortOrder")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PromotionListResponse(BaseModel):
    success: bool = True
    promotions: list[PromotionResponse]


class PromotionMutationResponse(BaseModel):
    success: bool = True
    promotion: PromotionResponse


class PromotionBulkItem(PromotionUpdate):
    pass


class PromotionBulkResponse(BaseModel):
    success: bool = True
    count: int
