from pathlib import Path
from typing import Tuple

import pandas as pd


def export_all(df: pd.DataFrame, output_dir: str | Path, base_name: str = "receivables") -> Tuple[Path, Path, Path]:
    """
    Export dataframe to Excel, CSV, and JSON in the given directory.
    Returns paths to the created files.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    excel_path = out_dir / f"{base_name}.xlsx"
    csv_path = out_dir / f"{base_name}.csv"
    json_path = out_dir / f"{base_name}.json"

    export_df = df.copy()
    export_df.rename(
        columns={
            "region": "Region",
            "customer_name": "Customer",
            "safe": "Safe",
            "warning": "Warning",
            "danger": "Danger",
            "doubtful": "Doubtful",
            "total": "Total",
        },
        inplace=True,
    )

    export_df.to_excel(excel_path, index=False)
    export_df.to_csv(csv_path, index=False)
    export_df.to_json(json_path, orient="records", indent=2)

    return excel_path, csv_path, json_path

