from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    client_id: str
    client_key: str
    tapis_base_url: str
    app_base_url: str
    tenant: str
    callback_url: str

settings = Settings()