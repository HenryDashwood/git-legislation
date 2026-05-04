from pathlib import Path

from converters.clmltomarkdown import (
    ConversionReport,
    convert_document_markdown,
    convert_xml_tree,
    document_commentaries,
    document_metadata,
    document_prelims,
    document_sections,
    document_title,
    markdown_output_target_from_xml_path,
    render_document_markdown,
    write_conversion_report,
    write_document_markdown,
)

SAMPLE_XML = Path(__file__).parent / "fixtures" / "ukpga-2026-14.xml"


def test_document_title_reads_metadata_title() -> None:
    assert document_title(SAMPLE_XML) == "Industry and Exports (Financial Assistance) Act 2026"


def test_document_metadata_reads_frontmatter_fields() -> None:
    metadata = document_metadata(SAMPLE_XML)

    assert metadata.title == "Industry and Exports (Financial Assistance) Act 2026"
    assert metadata.document_uri == "http://www.legislation.gov.uk/ukpga/2026/14/2026-05-03"
    assert metadata.status == "Prospective"
    assert metadata.extent == "E+W+S+N.I."


def test_document_prelims_reads_title_number_and_long_title() -> None:
    prelims = document_prelims(SAMPLE_XML)

    assert prelims.title == "Industry and Exports (Financial Assistance) Act 2026"
    assert prelims.number == "2026 Chapter 14"
    assert (
        prelims.long_title == "An Act to amend section 8(5) of the Industrial Development Act 1982 "
        "and section 6 of the Export and Investment Guarantees Act 1991."
    )


def test_document_sections_reads_section_numbers_and_titles() -> None:
    sections = document_sections(SAMPLE_XML)

    assert [(section.number, section.title) for section in sections] == [
        ("1", "Limit on selective financial assistance for industry"),
        ("2", "Financial assistance for exports and overseas investment: commitment limits"),
        ("3", "Extent, commencement and short title"),
    ]


def test_document_sections_reads_commentary_refs() -> None:
    sections = document_sections(SAMPLE_XML)

    assert sections[0].commentary_refs == ["key-section-1"]
    assert sections[1].commentary_refs == []


def test_document_commentaries_reads_commentary_text() -> None:
    assert document_commentaries(SAMPLE_XML) == {
        "key-section-1": "S. 1 in force at 18.5.2026, see s. 3(2)"
    }


def test_document_sections_reads_first_section_body_lines() -> None:
    section = document_sections(SAMPLE_XML)[0]

    assert section.lines == [
        "In section 8 of the Industrial Development Act 1982 "
        "(selective financial assistance: general powers), in subsection (5)—",
        "(a) for “£12,000 million” substitute “£20 billion”;",
        "(b) for “£1,000 million” substitute “£1.5 billion”.",
    ]


def test_render_document_markdown_renders_prelims_and_sections() -> None:
    markdown = render_document_markdown(SAMPLE_XML)

    assert markdown.startswith(
        "---\n"
        'title: "Industry and Exports (Financial Assistance) Act 2026"\n'
        'document_uri: "http://www.legislation.gov.uk/ukpga/2026/14/2026-05-03"\n'
        'status: "Prospective"\n'
        'extent: "E+W+S+N.I."\n'
        "---\n\n"
        "# Industry and Exports (Financial Assistance) Act 2026\n\n"
        "2026 Chapter 14\n\n"
        "An Act to amend section 8(5) of the Industrial Development Act 1982 "
        "and section 6 of the Export and Investment Guarantees Act 1991.\n"
    )
    assert "## 1 Limit on selective financial assistance for industry" in markdown
    assert "> Commentary: S. 1 in force at 18.5.2026, see s. 3(2)" in markdown
    assert "(a) for “£12,000 million” substitute “£20 billion”;" in markdown


def test_markdown_output_target_from_xml_path_reads_enacted_source_path(tmp_path: Path) -> None:
    xml_path = tmp_path / "xml" / "enacted" / "ukpga" / "Vict" / "1-2" / "42" / "data.xml"

    target = markdown_output_target_from_xml_path(xml_path, output_root=tmp_path)

    assert target.source_path == ("ukpga", "Vict", "1-2", "42")
    assert target.as_enacted is True
    assert target.at is None


def test_markdown_output_target_from_xml_path_reads_point_in_time_source_path(tmp_path: Path) -> None:
    xml_path = tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"

    target = markdown_output_target_from_xml_path(xml_path, output_root=tmp_path)

    assert target.source_path == ("ukpga", "2026", "14")
    assert target.as_enacted is False
    assert target.at == "2026-05-03"


def test_write_document_markdown_writes_to_the_enacted_markdown_output_folder(tmp_path: Path) -> None:
    markdown = "# Example\n"

    path = write_document_markdown(
        markdown,
        output_root=tmp_path,
        source_path=("ukpga", "2026", "14"),
        as_enacted=True,
    )

    assert path == tmp_path / "markdown" / "enacted" / "ukpga" / "2026" / "14.md"
    assert path.read_text() == markdown


def test_write_document_markdown_writes_to_the_point_in_time_markdown_output_folder(tmp_path: Path) -> None:
    markdown = "# Example\n"

    path = write_document_markdown(
        markdown,
        output_root=tmp_path,
        source_path=("ukpga", "Vict", "1-2", "42"),
        at="2026-05-03",
    )

    assert path == tmp_path / "markdown" / "point-in-time" / "2026-05-03" / "ukpga" / "Vict" / "1-2" / "42.md"
    assert path.read_text() == markdown


def test_convert_document_markdown_uses_fetched_xml_layout(tmp_path: Path) -> None:
    xml_path = tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"
    xml_path.parent.mkdir(parents=True)
    xml_path.write_text(SAMPLE_XML.read_text())

    path = convert_document_markdown(xml_path, output_root=tmp_path)

    assert path == tmp_path / "markdown" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14.md"
    assert "# Industry and Exports (Financial Assistance) Act 2026" in path.read_text()


def test_convert_xml_tree_converts_all_fetched_xml_documents(tmp_path: Path) -> None:
    xml_root = tmp_path / "xml" / "enacted" / "ukpga"
    first = xml_root / "2026" / "14" / "data.xml"
    second = xml_root / "Vict" / "1-2" / "42" / "data.xml"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(SAMPLE_XML.read_text())
    second.write_text(SAMPLE_XML.read_text())

    paths = convert_xml_tree(xml_root, output_root=tmp_path)

    assert paths == [
        tmp_path / "markdown" / "enacted" / "ukpga" / "2026" / "14.md",
        tmp_path / "markdown" / "enacted" / "ukpga" / "Vict" / "1-2" / "42.md",
    ]


def test_convert_xml_tree_records_failures_and_continues(tmp_path: Path) -> None:
    xml_root = tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga"
    good = xml_root / "2026" / "14" / "data.xml"
    bad = xml_root / "2026" / "13" / "data.xml"
    good.parent.mkdir(parents=True)
    bad.parent.mkdir(parents=True)
    good.write_text(SAMPLE_XML.read_text())
    bad.write_text("")
    messages: list[str] = []
    report = ConversionReport.point_in_time(legislation_type="ukpga", at="2026-05-03")

    paths = convert_xml_tree(xml_root, output_root=tmp_path, report=report, log=messages.append)

    assert paths == [tmp_path / "markdown" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14.md"]
    assert report.converted_paths == [str(paths[0])]
    assert len(report.failures) == 1
    assert report.failures[0].source_path == ("ukpga", "2026", "13")
    assert "no element found" in report.failures[0].error
    assert messages == [f"Failed converting {bad}: no element found: line 1, column 0"]


def test_write_conversion_report_writes_point_in_time_report(tmp_path: Path) -> None:
    report = ConversionReport.point_in_time(legislation_type="ukpga", at="2026-05-03")
    report.converted_paths.append("output/markdown/point-in-time/2026-05-03/ukpga/2026/14.md")

    path = write_conversion_report(report, output_root=tmp_path)

    assert path == tmp_path / "reports" / "convert" / "point-in-time" / "2026-05-03" / "ukpga.json"
    assert '"mode": "point-in-time"' in path.read_text()
    assert '"legislation_type": "ukpga"' in path.read_text()
