from dotenv import load_dotenv
import os

load_dotenv(".env")
load_dotenv(".env.local", override=True)


class Settings:

    PROJECT_NAME: str = "MAXX Backend"

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        ""
    )

    # Retrieval

    DEDUP_THRESHOLD: float = 0.20
    MMR_LAMBDA: float = 0.60

    # Similarity Thresholds

    SIMILARITY_THRESHOLD_GENERAL: float = 0.70
    SIMILARITY_THRESHOLD_GOALS: float = 0.45
    SIMILARITY_THRESHOLD_PREFERENCES: float = 0.50
    SIMILARITY_THRESHOLD_PROJECTS: float = 0.50
    SIMILARITY_THRESHOLD_SELF_SUMMARY: float = 0.00

    # MMR Limits

    MMR_LIMIT_GENERAL: int = 5
    MMR_LIMIT_GOALS: int = 5
    MMR_LIMIT_PREFERENCES: int = 5
    MMR_LIMIT_PROJECTS: int = 6
    MMR_LIMIT_SELF_SUMMARY: int = 7


settings = Settings()