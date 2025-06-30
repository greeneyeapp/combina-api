from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENWEATHER_API_KEY: str
    OPENAI_API_KEY: str
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    GOOGLE_APPLICATION_CREDENTIALS: str
    
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    APPLE_CLIENT_ID: str = ""  
    APPLE_TEAM_ID: str = ""
    APPLE_KEY_ID: str = ""

    class Config:
        env_file = ".env"
        extra = 'ignore'

settings = Settings()