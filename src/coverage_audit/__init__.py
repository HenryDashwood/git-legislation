import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from xml.etree import ElementTree

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "leg": "http://www.legislation.gov.uk/namespaces/legislation",
    "ukm": "http://www.legislation.gov.uk/namespaces/metadata",
}


@dataclass(frozen=True)
class CoverageAudit:
    at: str
    legislation_type: str
    xml_root: Path
    markdown_root: Path
    fetch_report_path: Path
    convert_report_path: Path
    fetch_report_exists: bool
    convert_report_exists: bool
    fetch_report_fetched: int
    fetch_report_failures: int
    fetch_failure_stages: Counter[str] = field(default_factory=Counter)
    fetch_failure_errors: Counter[str] = field(default_factory=Counter)
    convert_report_converted: int = 0
    convert_report_failures: int = 0
    convert_failure_errors: Counter[str] = field(default_factory=Counter)
    xml_files: int = 0
    valid_legislation_xml: int = 0
    metadata_only_xml: int = 0
    full_text_xml: int = 0
    pdf_linked_xml: int = 0
    empty_xml: int = 0
    malformed_xml: int = 0
    non_legislation_xml: int = 0
    markdown_files: int = 0

    @property
    def expected_from_fetch_report(self) -> int:
        return self.fetch_report_fetched + self.fetch_report_failures

    @property
    def local_xml_problem_count(self) -> int:
        return self.empty_xml + self.malformed_xml + self.non_legislation_xml

    @property
    def markdown_gap_against_valid_xml(self) -> int:
        return max(self.valid_legislation_xml - self.markdown_files, 0)


@dataclass(frozen=True)
class LocalXmlProblem:
    path: Path
    reason: str


@dataclass(frozen=True)
class CleanupResult:
    problems: list[LocalXmlProblem]
    removed: list[Path]
    dry_run: bool


def audit_point_in_time_coverage(
    at: str,
    legislation_type: str = "ukpga",
    output_root: Path = Path("output"),
) -> CoverageAudit:
    xml_root = output_root / "xml" / "point-in-time" / at / legislation_type
    markdown_root = output_root / "markdown" / "point-in-time" / at / legislation_type
    fetch_report_path = output_root / "reports" / "fetch" / "point-in-time" / f"{at}.json"
    convert_report_path = output_root / "reports" / "convert" / "point-in-time" / at / f"{legislation_type}.json"

    fetch_report = _read_json(fetch_report_path)
    convert_report = _read_json(convert_report_path)
    xml_counts = _scan_xml_tree(xml_root)
    fetched = _json_list(fetch_report, "fetched") if fetch_report is not None else []
    fetch_failures = _json_list(fetch_report, "failures") if fetch_report is not None else []
    converted_paths = _json_list(convert_report, "converted_paths") if convert_report is not None else []
    convert_failures = _json_list(convert_report, "failures") if convert_report is not None else []

    return CoverageAudit(
        at=at,
        legislation_type=legislation_type,
        xml_root=xml_root,
        markdown_root=markdown_root,
        fetch_report_path=fetch_report_path,
        convert_report_path=convert_report_path,
        fetch_report_exists=fetch_report is not None,
        convert_report_exists=convert_report is not None,
        fetch_report_fetched=len(fetched),
        fetch_report_failures=len(fetch_failures),
        fetch_failure_stages=Counter(_failure_stage(failure) for failure in fetch_failures),
        fetch_failure_errors=Counter(_summarize_error(_failure_error(failure)) for failure in fetch_failures),
        convert_report_converted=len(converted_paths),
        convert_report_failures=len(convert_failures),
        convert_failure_errors=Counter(_summarize_error(_failure_error(failure)) for failure in convert_failures),
        markdown_files=_count_files(markdown_root, "*.md"),
        **xml_counts,
    )


def find_point_in_time_xml_problems(
    at: str,
    legislation_type: str = "ukpga",
    output_root: Path = Path("output"),
) -> list[LocalXmlProblem]:
    xml_root = output_root / "xml" / "point-in-time" / at / legislation_type
    return _find_xml_problems(xml_root)


def clean_point_in_time_xml(
    at: str,
    legislation_type: str = "ukpga",
    output_root: Path = Path("output"),
    dry_run: bool = False,
) -> CleanupResult:
    problems = find_point_in_time_xml_problems(at=at, legislation_type=legislation_type, output_root=output_root)
    removed: list[Path] = []

    if not dry_run:
        for problem in problems:
            problem.path.unlink()
            removed.append(problem.path)

    return CleanupResult(problems=problems, removed=removed, dry_run=dry_run)


def render_cleanup_result(result: CleanupResult) -> str:
    action = "Would remove" if result.dry_run else "Removed"
    lines = [f"{action} {len(result.problems)} local XML problem files"]
    lines.extend(f"- {problem.reason}: {problem.path}" for problem in result.problems)
    return "\n".join(lines)


def render_point_in_time_failure_details(
    at: str,
    legislation_type: str = "ukpga",
    output_root: Path = Path("output"),
) -> str:
    fetch_report_path = output_root / "reports" / "fetch" / "point-in-time" / f"{at}.json"
    convert_report_path = output_root / "reports" / "convert" / "point-in-time" / at / f"{legislation_type}.json"
    fetch_report = _read_json(fetch_report_path)
    convert_report = _read_json(convert_report_path)

    lines = [f"Failure details for {legislation_type} at {at}", ""]
    lines.append(f"Fetch report: {_path_status(fetch_report_path, fetch_report is not None)}")
    fetch_failures = _json_list(fetch_report, "failures") if fetch_report is not None else []
    if fetch_failures:
        lines.append("Fetch failures:")
        lines.extend(_format_fetch_failure(failure) for failure in fetch_failures)
    else:
        lines.append("Fetch failures: none")

    lines.extend(["", f"Convert report: {_path_status(convert_report_path, convert_report is not None)}"])
    convert_failures = _json_list(convert_report, "failures") if convert_report is not None else []
    if convert_failures:
        lines.append("Conversion failures:")
        lines.extend(_format_convert_failure(failure) for failure in convert_failures)
    else:
        lines.append("Conversion failures: none")

    return "\n".join(lines)


def render_coverage_audit(audit: CoverageAudit) -> str:
    lines = [
        f"Coverage audit for {audit.legislation_type} at {audit.at}",
        "",
        "Reports",
        f"- fetch report: {_path_status(audit.fetch_report_path, audit.fetch_report_exists)}",
        f"- convert report: {_path_status(audit.convert_report_path, audit.convert_report_exists)}",
        "",
        "Fetch coverage",
        f"- expected documents from fetch report: {audit.expected_from_fetch_report}",
        f"- fetched or already present: {audit.fetch_report_fetched}",
        f"- fetch failures: {audit.fetch_report_failures}",
        "",
        "Local XML",
        f"- XML files: {audit.xml_files}",
        f"- valid legislation XML: {audit.valid_legislation_xml}",
        f"- full-text XML: {audit.full_text_xml}",
        f"- metadata-only XML: {audit.metadata_only_xml}",
        f"- XML with PDF alternatives: {audit.pdf_linked_xml}",
        f"- local XML problems: {audit.local_xml_problem_count}",
        f"  - empty: {audit.empty_xml}",
        f"  - malformed: {audit.malformed_xml}",
        f"  - non-legislation XML: {audit.non_legislation_xml}",
        "",
        "Markdown",
        f"- Markdown files: {audit.markdown_files}",
        f"- converted in report: {audit.convert_report_converted}",
        f"- conversion failures: {audit.convert_report_failures}",
        f"- valid XML without Markdown: {audit.markdown_gap_against_valid_xml}",
    ]

    if audit.fetch_failure_errors:
        lines.extend(["", "Fetch failure categories"])
        lines.extend(f"- {error}: {count}" for error, count in audit.fetch_failure_errors.most_common())

    if audit.convert_failure_errors:
        lines.extend(["", "Conversion failure categories"])
        lines.extend(f"- {error}: {count}" for error, count in audit.convert_failure_errors.most_common())

    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _json_list(data: dict[str, object], key: str) -> list[object]:
    value = data.get(key, [])
    return cast("list[object]", value) if isinstance(value, list) else []


def _scan_xml_tree(xml_root: Path) -> dict[str, int]:
    counts = {
        "xml_files": 0,
        "valid_legislation_xml": 0,
        "metadata_only_xml": 0,
        "full_text_xml": 0,
        "pdf_linked_xml": 0,
        "empty_xml": 0,
        "malformed_xml": 0,
        "non_legislation_xml": 0,
    }

    if not xml_root.exists():
        return counts

    for xml_path in sorted(xml_root.rglob("data.xml")):
        counts["xml_files"] += 1
        if xml_path.stat().st_size == 0:
            counts["empty_xml"] += 1
            continue

        try:
            root = ElementTree.parse(xml_path).getroot()
        except ElementTree.ParseError:
            counts["malformed_xml"] += 1
            continue

        if _local_name(root.tag) != "Legislation":
            counts["non_legislation_xml"] += 1
            continue

        counts["valid_legislation_xml"] += 1
        if _has_full_text(root):
            counts["full_text_xml"] += 1
        else:
            counts["metadata_only_xml"] += 1
        if _has_pdf_alternative(root):
            counts["pdf_linked_xml"] += 1

    return counts


def _find_xml_problems(xml_root: Path) -> list[LocalXmlProblem]:
    if not xml_root.exists():
        return []

    problems: list[LocalXmlProblem] = []
    for xml_path in sorted(xml_root.rglob("data.xml")):
        if xml_path.stat().st_size == 0:
            problems.append(LocalXmlProblem(path=xml_path, reason="empty"))
            continue

        try:
            root = ElementTree.parse(xml_path).getroot()
        except ElementTree.ParseError:
            problems.append(LocalXmlProblem(path=xml_path, reason="malformed"))
            continue

        if _local_name(root.tag) != "Legislation":
            problems.append(LocalXmlProblem(path=xml_path, reason="non-legislation XML"))

    return problems


def _count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob(pattern) if path.is_file())


def _has_full_text(root: ElementTree.Element) -> bool:
    return root.find(".//leg:Body", namespaces=NAMESPACES) is not None


def _has_pdf_alternative(root: ElementTree.Element) -> bool:
    for link in root.findall(".//atom:link", namespaces=NAMESPACES):
        if link.attrib.get("type") == "application/pdf":
            return True
    for alternative in root.findall(".//ukm:Alternative", namespaces=NAMESPACES):
        uri = alternative.attrib.get("URI", "")
        if uri.lower().endswith(".pdf"):
            return True
    return False


def _path_status(path: Path, exists: bool) -> str:
    return str(path) if exists else f"{path} (missing)"


def _format_fetch_failure(failure: object) -> str:
    if not isinstance(failure, dict):
        return f"- {failure}"
    failure_data = cast("dict[str, object]", failure)
    year = failure_data.get("year")
    number = failure_data.get("number")
    stage = failure_data.get("stage", "unknown")
    url = failure_data.get("url")
    error = failure_data.get("error")
    return f"- {stage} {year}/{number}: {error} ({url})"


def _format_convert_failure(failure: object) -> str:
    if not isinstance(failure, dict):
        return f"- {failure}"
    failure_data = cast("dict[str, object]", failure)
    input_path = failure_data.get("input_path")
    source_path_value = failure_data.get("source_path", [])
    source_path = "/".join(str(part) for part in source_path_value) if isinstance(source_path_value, list) else ""
    error = failure_data.get("error")
    label = source_path or input_path
    return f"- {label}: {error} ({input_path})"


def _failure_stage(failure: object) -> str:
    if not isinstance(failure, dict):
        return "unknown"
    failure_data = cast("dict[str, object]", failure)
    return str(failure_data.get("stage", "unknown"))


def _failure_error(failure: object) -> object:
    if not isinstance(failure, dict):
        return ""
    failure_data = cast("dict[str, object]", failure)
    return failure_data.get("error", "")


def _summarize_error(error: object) -> str:
    message = str(error)
    if "not legislation XML" in message:
        return "non-legislation XML response"
    if "not parseable legislation XML" in message:
        return "unparseable XML response"
    if "HTTP status" in message:
        return message.split(" for ", maxsplit=1)[0]
    if "Connection reset" in message:
        return "connection reset"
    if "timed out" in message.lower():
        return "timeout"
    if "no element found" in message:
        return "empty or malformed XML"
    return message


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
