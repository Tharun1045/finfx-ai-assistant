from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, examples=["How long do transfers take?"])
    use_llm: bool = True


class ConvertRequest(BaseModel):
    amount: float = Field(..., gt=0)
    from_currency: str = Field(..., min_length=3, max_length=3)
    to_currency: str = Field(..., min_length=3, max_length=3)


class SqlRequest(BaseModel):
    question: str = Field(..., min_length=3)


class TransferRequest(BaseModel):
    customer_name: str = Field(..., min_length=2, examples=["Aisha Patel"])
    from_currency: str = Field(..., min_length=3, max_length=3, examples=["GBP"])
    to_currency: str = Field(..., min_length=3, max_length=3, examples=["INR"])
    amount: float = Field(..., gt=0, examples=[5000])
    beneficiary_country: str = Field(..., min_length=2, examples=["India"])
    purpose: str = Field(..., min_length=2, examples=["Family support"])
