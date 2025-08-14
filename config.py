from pydantic_settings import BaseSettings
class AuthSettings(BaseSettings):
    client_id: str
    client_key: str
    tapis_base_url: str
    app_base_url: str
    tenant: str
    callback_url: str

class AppSettings(BaseSettings):
    host: str
    port: int
    debug: bool
    param_server_url: str
    sandbox_server_url: str
    mongodb_uri: str

auth_settings = AuthSettings()
app_settings = AppSettings()