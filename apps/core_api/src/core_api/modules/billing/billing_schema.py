from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BillingAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    status: str
    provider: str | None
    provider_customer_id: str | None
    current_product_code: str | None
    current_period_ends_at: datetime | None
    created_at: datetime
