from pydantic import BaseModel,Field


class OtpSentPayload(BaseModel):
    mobile:str = Field(..., description="The mobile number to which the OTP was sent",max_length=10)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "mobile": "1234567890"
                }
            ]
        }
    }


class OtpVerifyPayload(BaseModel):
    mobile:str = Field(..., description="The mobile number used for verification",max_length=10)
    otp:str = Field(..., description="The OTP code received",max_length=6)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "mobile": "1234567890",
                    "otp": "123456"
                }
            ]
        }
    }