"""Ingeniería de características compartida entre entrenamiento e inferencia."""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from src.config import CATEGORICAL_FEATURES, MACHINE_TYPES, NUMERIC_FEATURES

ENGINEERED_FEATURES = ["Temp_x_Vibration", "Power_per_Vibration", "Thermal_Stress"]


def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Temp_x_Vibration"] = df["Temperature"] * df["Vibration"]
    df["Power_per_Vibration"] = df["Power_Usage"] / df["Vibration"].replace(0, np.nan)
    df["Power_per_Vibration"] = df["Power_per_Vibration"].fillna(0.0)
    # Estrés térmico: temperatura alta combinada con humedad
    df["Thermal_Stress"] = df["Temperature"] * (1 + df["Humidity"] / 100)
    return df


def build_preprocessor() -> Pipeline:
    columns = ColumnTransformer(
        [
            ("num", StandardScaler(), NUMERIC_FEATURES + ENGINEERED_FEATURES),
            (
                "cat",
                OneHotEncoder(categories=[MACHINE_TYPES], handle_unknown="ignore"),
                CATEGORICAL_FEATURES,
            ),
        ]
    )
    return Pipeline(
        [
            ("features", FunctionTransformer(add_engineered_features)),
            ("columns", columns),
        ]
    )
