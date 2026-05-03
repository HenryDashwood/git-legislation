from pathlib import Path

from converters.clmltomarkdown import (
    document_metadata,
    document_prelims,
    document_sections,
    document_title,
    render_document_markdown,
    write_document_markdown,
)

SAMPLE_XML = Path("output/xml/point-in-time/2026-05-03/ukpga/2026/14.xml")


def test_document_title_reads_metadata_title() -> None:
    assert document_title(SAMPLE_XML) == "Industry and Exports (Financial Assistance) Act 2026"


def test_document_metadata_reads_frontmatter_fields() -> None:
    metadata = document_metadata(SAMPLE_XML)

    assert metadata.title == "Industry and Exports (Financial Assistance) Act 2026"
    assert metadata.document_uri == "http://www.legislation.gov.uk/ukpga/2026/14"
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
        "# Industry and Exports (Financial Assistance) Act 2026\n\n"
        "2026 Chapter 14\n\n"
        "An Act to amend section 8(5) of the Industrial Development Act 1982 "
        "and section 6 of the Export and Investment Guarantees Act 1991.\n"
    )
    assert "## 1 Limit on selective financial assistance for industry" in markdown
    assert "(a) for “£12,000 million” substitute “£20 billion”;" in markdown


def test_write_document_markdown_writes_to_the_markdown_output_folder(tmp_path: Path) -> None:
    markdown = "# Example\n"

    path = write_document_markdown(
        markdown,
        legislation_type="ukpga",
        year=2026,
        number=14,
        output_root=tmp_path,
    )

    assert path == tmp_path / "markdown" / "enacted" / "ukpga" / "2026" / "14.md"
    assert path.read_text() == markdown
