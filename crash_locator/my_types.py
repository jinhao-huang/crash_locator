from pydantic import BaseModel


class PreCheckStatistic(BaseModel):
    total_reports: int = 0
    valid_reports: int = 0
    invalid_reports: int = 0
