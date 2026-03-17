from pathlib import Path
from typing import Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph


def export_pdf(
    df: pd.DataFrame,
    output_path: str | Path,
    title: str = "Receivables",
    subtitle: Optional[str] = None,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(str(out), pagesize=landscape(A4))
    styles = getSampleStyleSheet()

    story = [Paragraph(title, styles["Title"])]
    if subtitle:
        story.append(Paragraph(subtitle, styles["Normal"]))
    story.append(Spacer(1, 12))

    cols = ["region", "customer_name", "payment_status", "safe", "warning", "danger", "doubtful", "total"]
    export_df = df[cols].copy()
    export_df.rename(
        columns={
            "region": "Region",
            "customer_name": "Customer",
            "payment_status": "Payment Status",
            "safe": "Safe",
            "warning": "Warning",
            "danger": "Danger",
            "doubtful": "Doubtful",
            "total": "Total",
        },
        inplace=True,
    )

    data = [export_df.columns.tolist()] + export_df.values.tolist()
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    story.append(tbl)
    doc.build(story)
    return out

