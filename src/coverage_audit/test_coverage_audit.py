import json
from pathlib import Path

from coverage_audit import (
    audit_point_in_time_coverage,
    clean_point_in_time_xml,
    find_point_in_time_xml_problems,
    render_cleanup_result,
    render_coverage_audit,
    render_point_in_time_failure_details,
)

FULL_TEXT_XML = """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  DocumentURI="http://www.legislation.gov.uk/ukpga/2026/14">
  <dc:title>Example Act</dc:title>
  <Primary>
    <Body>
      <P1group>
        <Title>Example section</Title>
      </P1group>
    </Body>
  </Primary>
</Legislation>
"""

METADATA_ONLY_XML = """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
  xmlns:atom="http://www.w3.org/2005/Atom"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  DocumentURI="http://www.legislation.gov.uk/ukpga/1963/1">
  <dc:title>Metadata Only Act</dc:title>
  <atom:link
    rel="alternate"
    href="http://www.legislation.gov.uk/ukpga/1963/1/pdfs/ukpga_19630001_en.pdf"
    type="application/pdf"/>
</Legislation>
"""


def test_audit_point_in_time_coverage_counts_reports_and_local_files(tmp_path: Path) -> None:
    xml_root = tmp_path / "xml" / "point-in-time" / "2026-05-04" / "ukpga"
    markdown_root = tmp_path / "markdown" / "point-in-time" / "2026-05-04" / "ukpga"
    fetch_report = tmp_path / "reports" / "fetch" / "point-in-time" / "2026-05-04.json"
    convert_report = tmp_path / "reports" / "convert" / "point-in-time" / "2026-05-04" / "ukpga.json"

    (xml_root / "2026" / "14").mkdir(parents=True)
    (xml_root / "1963" / "1").mkdir(parents=True)
    (xml_root / "2006" / "46").mkdir(parents=True)
    (xml_root / "bad" / "html").mkdir(parents=True)
    (markdown_root / "2026").mkdir(parents=True)
    fetch_report.parent.mkdir(parents=True)
    convert_report.parent.mkdir(parents=True)

    (xml_root / "2026" / "14" / "data.xml").write_text(FULL_TEXT_XML)
    (xml_root / "1963" / "1" / "data.xml").write_text(METADATA_ONLY_XML)
    (xml_root / "2006" / "46" / "data.xml").write_text("")
    (xml_root / "bad" / "html" / "data.xml").write_text("<html />")
    (markdown_root / "2026" / "14.md").write_text("# Example Act\n")

    fetch_report.write_text(
        json.dumps(
            {
                "fetched": ["a", "b"],
                "failures": [
                    {
                        "stage": "document",
                        "error": "Response from https://example.test/data.xml is 'html', not legislation XML",
                    }
                ],
            }
        )
    )
    convert_report.write_text(
        json.dumps(
            {
                "converted_paths": ["a"],
                "failures": [{"error": "no element found: line 1, column 0"}],
            }
        )
    )

    audit = audit_point_in_time_coverage(at="2026-05-04", legislation_type="ukpga", output_root=tmp_path)

    assert audit.expected_from_fetch_report == 3
    assert audit.fetch_report_fetched == 2
    assert audit.fetch_report_failures == 1
    assert audit.xml_files == 4
    assert audit.valid_legislation_xml == 2
    assert audit.full_text_xml == 1
    assert audit.metadata_only_xml == 1
    assert audit.pdf_linked_xml == 1
    assert audit.empty_xml == 1
    assert audit.non_legislation_xml == 1
    assert audit.markdown_files == 1
    assert audit.convert_report_converted == 1
    assert audit.convert_report_failures == 1
    assert audit.fetch_failure_errors["non-legislation XML response"] == 1
    assert audit.convert_failure_errors["empty or malformed XML"] == 1


def test_render_coverage_audit_outputs_human_summary(tmp_path: Path) -> None:
    audit = audit_point_in_time_coverage(at="2026-05-04", legislation_type="ukpga", output_root=tmp_path)

    summary = render_coverage_audit(audit)

    assert "Coverage audit for ukpga at 2026-05-04" in summary
    assert "fetch report:" in summary
    assert "expected documents from fetch report: 0" in summary
    assert "valid legislation XML: 0" in summary


def test_find_and_clean_point_in_time_xml_problems(tmp_path: Path) -> None:
    xml_root = tmp_path / "xml" / "point-in-time" / "2026-05-04" / "ukpga"
    valid_path = xml_root / "2026" / "14" / "data.xml"
    empty_path = xml_root / "2006" / "46" / "data.xml"
    malformed_path = xml_root / "bad" / "malformed" / "data.xml"
    html_path = xml_root / "bad" / "html" / "data.xml"

    valid_path.parent.mkdir(parents=True)
    empty_path.parent.mkdir(parents=True)
    malformed_path.parent.mkdir(parents=True)
    html_path.parent.mkdir(parents=True)
    valid_path.write_text(FULL_TEXT_XML)
    empty_path.write_text("")
    malformed_path.write_text("<Legislation")
    html_path.write_text("<html />")

    problems = find_point_in_time_xml_problems(at="2026-05-04", legislation_type="ukpga", output_root=tmp_path)

    assert [(problem.path, problem.reason) for problem in problems] == [
        (empty_path, "empty"),
        (html_path, "non-legislation XML"),
        (malformed_path, "malformed"),
    ]

    dry_run = clean_point_in_time_xml(
        at="2026-05-04",
        legislation_type="ukpga",
        output_root=tmp_path,
        dry_run=True,
    )

    assert dry_run.removed == []
    assert empty_path.exists()
    assert "Would remove 3 local XML problem files" in render_cleanup_result(dry_run)

    result = clean_point_in_time_xml(
        at="2026-05-04",
        legislation_type="ukpga",
        output_root=tmp_path,
    )

    assert result.removed == [empty_path, html_path, malformed_path]
    assert valid_path.exists()
    assert not empty_path.exists()
    assert not malformed_path.exists()
    assert not html_path.exists()
    assert "Removed 3 local XML problem files" in render_cleanup_result(result)


def test_render_point_in_time_failure_details_lists_fetch_and_conversion_failures(tmp_path: Path) -> None:
    fetch_report = tmp_path / "reports" / "fetch" / "point-in-time" / "2026-05-04.json"
    convert_report = tmp_path / "reports" / "convert" / "point-in-time" / "2026-05-04" / "ukpga.json"
    fetch_report.parent.mkdir(parents=True)
    convert_report.parent.mkdir(parents=True)
    fetch_report.write_text(
        json.dumps(
            {
                "failures": [
                    {
                        "stage": "document",
                        "year": 2006,
                        "number": 46,
                        "url": "https://www.legislation.gov.uk/ukpga/2006/46/data.xml",
                        "error": "Response was not parseable legislation XML",
                    }
                ]
            }
        )
    )
    convert_report.write_text(
        json.dumps(
            {
                "failures": [
                    {
                        "input_path": str(
                            tmp_path / "xml" / "point-in-time" / "2026-05-04" / "ukpga" / "2006" / "46" / "data.xml"
                        ),
                        "source_path": ["ukpga", "2006", "46"],
                        "error": "no element found: line 1, column 0",
                    }
                ]
            }
        )
    )

    details = render_point_in_time_failure_details(at="2026-05-04", legislation_type="ukpga", output_root=tmp_path)

    assert "Failure details for ukpga at 2026-05-04" in details
    assert "Fetch failures:" in details
    assert "document 2006/46: Response was not parseable legislation XML" in details
    assert "Conversion failures:" in details
    assert "ukpga/2006/46: no element found: line 1, column 0" in details
