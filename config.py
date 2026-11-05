from pydantic_settings import BaseSettings
class AuthSettings(BaseSettings):
    client_id: str
    client_key: str
    tapis_base_url: str
    app_base_url: str
    tenant: str
    callback_url: str
    class Config:
        env_file: str = ".env"
        extra = "ignore"

class AppSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    param_server_url: str
    sandbox_server_url: str
    mongodb_uri: str
    class Config:
        env_file: str = ".env"
        extra = "ignore"

auth_settings = AuthSettings()
app_settings = AppSettings()