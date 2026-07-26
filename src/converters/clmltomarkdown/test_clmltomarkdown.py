from pathlib import Path
from xml.etree import ElementTree

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
    render_document_markdown_from_xml,
    write_conversion_report,
    write_document_markdown,
)

SAMPLE_XML = Path(__file__).parent / "fixtures" / "ukpga-2026-14.xml"
METADATA_ONLY_XML = """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  DocumentURI="http://www.legislation.gov.uk/ukpga/1963/1/enacted">
  <ukm:Metadata
    xmlns:atom="http://www.w3.org/2005/Atom"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">
    <dc:title>Consolidated Fund Act 1963</dc:title>
    <atom:link
      rel="alternate"
      href="http://www.legislation.gov.uk/ukpga/1963/1/pdfs/ukpga_19630001_en.pdf"
      type="application/pdf"
      title="Original PDF"/>
    <ukm:PrimaryMetadata>
      <ukm:Year Value="1963"/>
      <ukm:Number Value="1"/>
    </ukm:PrimaryMetadata>
    <ukm:Alternatives>
      <ukm:Alternative URI="http://www.legislation.gov.uk/ukpga/1963/1/pdfs/ukpga_19630001_en.pdf"/>
    </ukm:Alternatives>
  </ukm:Metadata>
</Legislation>
"""


def test_document_title_reads_metadata_title() -> None:
    assert document_title(SAMPLE_XML) == "Industry and Exports (Financial Assistance) Act 2026"


def test_document_metadata_reads_frontmatter_fields() -> None:
    metadata = document_metadata(SAMPLE_XML)

    assert metadata.title == "Industry and Exports (Financial Assistance) Act 2026"
    assert metadata.document_uri == "http://www.legislation.gov.uk/ukpga/2026/14/2026-05-03"
    assert metadata.status == "Prospective"
    assert metadata.extent == "E+W+S+N.I."
    assert metadata.pdf_alternatives == ()


def test_document_metadata_reads_pdf_alternatives(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(METADATA_ONLY_XML)

    metadata = document_metadata(xml_path)

    assert metadata.pdf_alternatives == ("http://www.legislation.gov.uk/ukpga/1963/1/pdfs/ukpga_19630001_en.pdf",)


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


def test_document_sections_handles_unnumbered_p1groups(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(
        """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
  <Body>
    <P1group>
      <Title>Recital</Title>
      <P>
        <Text>Whereas this Act begins with an unnumbered recital.</Text>
      </P>
    </P1group>
  </Body>
</Legislation>
"""
    )

    sections = document_sections(xml_path)

    assert sections[0].number == ""
    assert sections[0].title == "Recital"
    assert sections[0].commentary_refs == []


def test_document_sections_reads_direct_body_paragraphs(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(
        """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
  <Body>
    <P>
      <Text>Item To eschow the gret herschip <CommentaryRef Ref="f1"/> And gif the creditour takkis.</Text>
    </P>
  </Body>
</Legislation>
"""
    )

    sections = document_sections(xml_path)

    assert len(sections) == 1
    assert sections[0].number == ""
    assert sections[0].title == ""
    assert sections[0].lines == ["Item To eschow the gret herschip And gif the creditour takkis."]
    assert sections[0].commentary_refs == ["f1"]


def test_document_sections_recurses_into_pblocks(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(
        """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
  <Body>
    <Pblock>
      <Title>Introduction</Title>
      <P1group>
        <Title>The Convention Rights.</Title>
        <P1>
          <Pnumber>1</Pnumber>
          <P1para>
            <P2>
              <Pnumber>1</Pnumber>
              <P2para>
                <Text>In this Act the Convention rights means the rights set out in—</Text>
                <P3>
                  <Pnumber>a</Pnumber>
                  <P3para><Text>Articles 2 to 12 and 14 of the Convention,</Text></P3para>
                </P3>
              </P2para>
            </P2>
          </P1para>
        </P1>
      </P1group>
    </Pblock>
  </Body>
</Legislation>
"""
    )

    sections = document_sections(xml_path)

    assert [(section.number, section.title) for section in sections] == [("1", "The Convention Rights.")]
    assert sections[0].lines == [
        "(1) In this Act the Convention rights means the rights set out in—",
        "(a) Articles 2 to 12 and 14 of the Convention,",
    ]


def test_document_sections_recurses_into_parts(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(
        """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
  <Body>
    <Part>
      <Title>Part 1 Introductory</Title>
      <P1group>
        <Title>Meaning of example</Title>
        <P1>
          <Pnumber>1</Pnumber>
          <P1para><Text>Example body text.</Text></P1para>
        </P1>
      </P1group>
    </Part>
  </Body>
</Legislation>
"""
    )

    sections = document_sections(xml_path)

    assert [(section.number, section.title) for section in sections] == [("1", "Meaning of example")]
    assert sections[0].lines == ["Example body text."]


def test_document_sections_reads_commentary_refs() -> None:
    sections = document_sections(SAMPLE_XML)

    assert sections[0].commentary_refs == ["key-section-1"]
    assert sections[1].commentary_refs == []


def test_document_commentaries_reads_commentary_text() -> None:
    assert document_commentaries(SAMPLE_XML) == {"key-section-1": "S. 1 in force at 18.5.2026, see s. 3(2)"}


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


def test_render_document_markdown_renders_metadata_only_xml(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(METADATA_ONLY_XML)

    markdown = render_document_markdown(xml_path)

    assert markdown.startswith(
        "---\n"
        'title: "Consolidated Fund Act 1963"\n'
        'document_uri: "http://www.legislation.gov.uk/ukpga/1963/1/enacted"\n'
        "pdf_alternatives:\n"
        '  - "http://www.legislation.gov.uk/ukpga/1963/1/pdfs/ukpga_19630001_en.pdf"\n'
        "---\n\n"
        "# Consolidated Fund Act 1963\n\n"
        "1963 Chapter 1\n\n"
        "Source XML contains metadata only; full text may be available in PDF or another source format."
    )
    assert "- http://www.legislation.gov.uk/ukpga/1963/1/pdfs/ukpga_19630001_en.pdf" in markdown


def test_render_document_markdown_from_xml_renders_without_filesystem_staging() -> None:
    markdown = render_document_markdown_from_xml(METADATA_ONLY_XML.encode())

    assert "# Consolidated Fund Act 1963" in markdown
    assert "Source XML contains metadata only" in markdown


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


def test_element_text_is_stable_across_pretty_printed_inline_markup() -> None:
    from converters.clmltomarkdown import _element_text

    compact = ElementTree.fromstring(
        '<Text xmlns="http://www.legislation.gov.uk/namespaces/legislation">'
        "in <Substitution>subsection (1)(d)</Substitution><Addition>, omit the reference.</Addition></Text>"
    )
    pretty = ElementTree.fromstring(
        '<Text xmlns="http://www.legislation.gov.uk/namespaces/legislation">'
        "in <Substitution>subsection (1)(d)\n"
        "                      </Substitution><Addition>, omit the reference.</Addition></Text>"
    )

    assert _element_text(compact) == "in subsection (1)(d), omit the reference."
    assert _element_text(pretty) == _element_text(compact)


def test_element_text_keeps_spaced_omission_dots() -> None:
    from converters.clmltomarkdown import _element_text

    element = ElementTree.fromstring(
        '<Text xmlns="http://www.legislation.gov.uk/namespaces/legislation">sections 25A . . . and 26A</Text>'
    )

    assert _element_text(element) == "sections 25A . . . and 26A"


def test_element_text_strips_space_before_sentence_dot_but_not_omission_dots() -> None:
    from converters.clmltomarkdown import _element_text

    element = ElementTree.fromstring(
        '<Text xmlns="http://www.legislation.gov.uk/namespaces/legislation">'
        "the Immigration Act 2016 <Addition>.</Addition> But sections 25A . . . apply.</Text>"
    )

    assert _element_text(element) == "the Immigration Act 2016. But sections 25A . . . apply."


SCHEDULE_XML = """\
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
  <Primary>
    <Body>
      <P1group>
        <Title>Opening section</Title>
        <P1><Pnumber>1</Pnumber><P1para><Text>Body text.</Text></P1para></P1>
      </P1group>
    </Body>
    <Schedules>
      <Title>Schedules</Title>
      <Schedule>
        <Number>SCHEDULE 1</Number>
        <TitleBlock><Title>Disability: supplementary provision</Title></TitleBlock>
        <ScheduleBody>
          <Part>
            <Title>Part 1 Determination of disability</Title>
            <P1group>
              <Title>Certain medical conditions</Title>
              <P1><Pnumber>2</Pnumber><P1para><Text>Cancer is a disability.</Text></P1para></P1>
            </P1group>
          </Part>
        </ScheduleBody>
      </Schedule>
      <Schedule>
        <Number>SCHEDULE 2</Number>
        <TitleBlock><Title>Services and public functions</Title></TitleBlock>
        <ScheduleBody><P><Text>Flat schedule text.</Text></P></ScheduleBody>
      </Schedule>
    </Schedules>
  </Primary>
</Legislation>
"""


def test_document_sections_includes_schedules_after_body(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(SCHEDULE_XML)

    sections = document_sections(xml_path)

    assert [(section.number, section.title) for section in sections] == [
        ("1", "Opening section"),
        ("SCHEDULE 1", "Disability: supplementary provision"),
        ("SCHEDULE 2", "Services and public functions"),
    ]


def test_schedule_section_keeps_internal_structure_as_nested_headings(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(SCHEDULE_XML)

    schedule = document_sections(xml_path)[1]

    assert schedule.lines == ["### 2 Certain medical conditions", "Cancer is a disability."]


def test_schedule_section_falls_back_to_flat_body_text(tmp_path: Path) -> None:
    xml_path = tmp_path / "data.xml"
    xml_path.write_text(SCHEDULE_XML)

    assert document_sections(xml_path)[2].lines == ["Flat schedule text."]


def test_render_document_markdown_emits_schedule_headings() -> None:
    xml = SCHEDULE_XML.replace(
        "<Primary>",
        """<ukm:Metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
             xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">
             <dc:title>Equality Act 2010</dc:title>
           </ukm:Metadata>
           <Primary>""",
    ).replace("<Legislation ", '<Legislation DocumentURI="http://www.legislation.gov.uk/ukpga/2010/15" ')

    markdown = render_document_markdown_from_xml(xml)

    # The heading must start with "SCHEDULE" so publishing types the provision
    # as a schedule rather than a section.
    assert "## SCHEDULE 1 Disability: supplementary provision" in markdown
    assert "## SCHEDULE 2 Services and public functions" in markdown
    assert "### 2 Certain medical conditions" in markdown
