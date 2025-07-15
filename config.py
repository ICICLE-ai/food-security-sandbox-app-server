# import os
# import yaml

# APP_CONFIG_PATH = os.environ.get('APP_CONFIG_PATH', 'config.yaml')
# if not os.path.exists(APP_CONFIG_PATH):
#     raise Exception(f"Could not open the config file; tried here: {APP_CONFIG_PATH}. Giving up and exiting.")

# with open(APP_CONFIG_PATH, 'r') as f:
#     config = yaml.safe_load(f)


# # override with environment vars
# if os.environ.get('client_id'):
#     config['client_id'] = os.environ.get('client_id')

# if os.environ.get('client_key'):
#     config['client_key'] = os.environ.get('client_key')

# if os.environ.get('tapis_base_url'):
#     config['tapis_base_url'] = os.environ.get('tapis_base_url')

# if os.environ.get('app_base_url'):
#     config['app_base_url'] = os.environ.get('app_base_url')
    
# if os.environ.get('tenant'):
#     config['tenant'] = os.environ.get('tenant')
from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    client_id = str
    client_key = str
    tapis_base_url = str
    app_base_url = str
    tenant = str

settings = Settings()