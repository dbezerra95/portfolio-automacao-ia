import csv
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook

Record = tuple[str, str, Decimal]


def reconcile(system: list[Record], payroll: list[Record], tolerance: Decimal) -> list[tuple[str, str, str, Decimal | None, Decimal | None]]:
    """Compare unique participant/month records with an inclusive tolerance."""
    if tolerance < 0:
        raise ValueError("Tolerance must be non-negative")
    def index(rows: list[Record]) -> dict[tuple[str, str], Decimal]:
        result = {}
        for participant, month, value in rows:
            key = (participant, month)
            if key in result:
                raise ValueError(f"Duplicate participant and competence: {key}")
            result[key] = value
        return result
    left, right = index(system), index(payroll)
    results = []
    for participant, month in sorted(left.keys() | right.keys()):
        a, b = left.get((participant, month)), right.get((participant, month))
        status = "Ausente no sistema" if a is None else "Ausente na folha" if b is None else "Conciliado" if abs(a - b) <= tolerance else "Divergência de valor"
        results.append((participant, month, status, a, b))
    return results


def make_report(csv_path: Path, payroll_path: Path, month: str, tolerance: Decimal, output: Path) -> dict[str, int]:
    with csv_path.open(encoding="utf-8", newline="") as stream:
        system = [(row["participant_id"], row["competencia"], Decimal(row["valor"])) for row in csv.DictReader(stream) if row["competencia"] == month]
    workbook = load_workbook(payroll_path, read_only=True, data_only=True)
    try:
        rows = workbook.active.iter_rows(values_only=True)
        if next(rows, None) != ("participant_id", "competencia", "valor"):
            raise ValueError("Invalid payroll header")
        payroll = [(str(p), str(m), Decimal(str(v))) for p, m, v in rows if str(m) == month]
    finally:
        workbook.close()
    results = reconcile(system, payroll, tolerance)
    report = Workbook()
    sheet = report.active
    sheet.title = "Conciliação"
    sheet.append(["Participante", "Competência", "Situação", "Sistema", "Folha"])
    counts: dict[str, int] = {}
    for participant, competence, status, a, b in results:
        sheet.append([participant, competence, status, float(a) if a is not None else None, float(b) if b is not None else None])
        counts[status] = counts.get(status, 0) + 1
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {"A": 18, "B": 18, "C": 25, "D": 15, "E": 15}.items():
        sheet.column_dimensions[column].width = width
    output.parent.mkdir(parents=True, exist_ok=True)
    report.save(output)
    return counts
