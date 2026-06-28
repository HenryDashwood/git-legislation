import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "leg": "http://www.legislation.gov.uk/namespaces/legislation",
    "ukm": "http://www.legislation.gov.uk/namespaces/metadata",
}
CONVERSION_LOG_INTERVAL = 500


@dataclass(frozen=True)
class DocumentMetadata:
    title: str
    document_uri: str
    status: str | None
    extent: str | None
    pdf_alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentPrelims:
    title: str
    number: str
    long_title: str


@dataclass(frozen=True)
class DocumentSection:
    number: str
    title: str
    lines: list[str]
    commentary_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarkdownOutputTarget:
    source_path: tuple[str, ...]
    as_enacted: bool
    at: str | None = None


@dataclass
class ConversionFailure:
    input_path: str
    source_path: tuple[str, ...]
    error: str


@dataclass
class ConversionReport:
    mode: str
    legislation_type: str
    at: str | None = None
    converted_paths: list[str] = field(default_factory=list)
    failures: list[ConversionFailure] = field(default_factory=list)

    @classmethod
    def enacted(cls, legislation_type: str) -> "ConversionReport":
        return cls(mode="enacted", legislation_type=legislation_type)

    @classmethod
    def point_in_time(cls, legislation_type: str, at: str) -> "ConversionReport":
        return cls(mode="point-in-time", legislation_type=legislation_type, at=at)


def document_title(xml_path: Path) -> str:
    root = ElementTree.parse(xml_path).getroot()
    title = root.findtext(".//dc:title", namespaces=NAMESPACES)
    if title is None:
        raise ValueError(f"No document title found in {xml_path}")
    return title


def document_metadata(xml_path: Path) -> DocumentMetadata:
    root = ElementTree.parse(xml_path).getroot()
    return document_metadata_from_root(root, source=str(xml_path))


def document_metadata_from_root(root: ElementTree.Element, source: str = "XML document") -> DocumentMetadata:
    title = root.findtext(".//dc:title", namespaces=NAMESPACES)
    if title is None:
        raise ValueError(f"No document title found in {source}")

    document_uri = root.attrib.get("DocumentURI")
    if document_uri is None:
        raise ValueError(f"No DocumentURI found in {source}")

    return DocumentMetadata(
        title=title,
        document_uri=document_uri,
        status=root.attrib.get("Status"),
        extent=root.attrib.get("RestrictExtent"),
        pdf_alternatives=_pdf_alternatives(root),
    )


def document_prelims(xml_path: Path) -> DocumentPrelims:
    root = ElementTree.parse(xml_path).getroot()
    return document_prelims_from_root(root, source=str(xml_path))


def document_prelims_from_root(root: ElementTree.Element, source: str = "XML document") -> DocumentPrelims:
    title = root.findtext(".//leg:PrimaryPrelims/leg:Title", namespaces=NAMESPACES) or root.findtext(
        ".//dc:title", namespaces=NAMESPACES
    )
    number = root.findtext(".//leg:PrimaryPrelims/leg:Number", namespaces=NAMESPACES) or _metadata_number(root)
    long_title_element = root.find(".//leg:PrimaryPrelims/leg:LongTitle", namespaces=NAMESPACES)

    if title is None:
        raise ValueError(f"No document title found in {source}")

    return DocumentPrelims(
        title=title,
        number=number or "",
        long_title=_element_text(long_title_element) if long_title_element is not None else "",
    )


def document_sections(xml_path: Path) -> list[DocumentSection]:
    root = ElementTree.parse(xml_path).getroot()
    return document_sections_from_root(root)


def document_sections_from_root(root: ElementTree.Element) -> list[DocumentSection]:
    body = root.find(".//leg:Body", namespaces=NAMESPACES)
    if body is None:
        return []
    return _body_sections(body)


def document_commentaries(xml_path: Path) -> dict[str, str]:
    root = ElementTree.parse(xml_path).getroot()
    return document_commentaries_from_root(root)


def document_commentaries_from_root(root: ElementTree.Element) -> dict[str, str]:
    commentaries: dict[str, str] = {}

    for commentary in root.findall(".//leg:Commentaries/leg:Commentary", namespaces=NAMESPACES):
        commentary_id = commentary.attrib.get("id")
        if commentary_id is None:
            continue

        text = _element_text(commentary)
        if text:
            commentaries[commentary_id] = text

    return commentaries


def render_document_markdown(xml_path: Path) -> str:
    metadata = document_metadata(xml_path)
    prelims = document_prelims(xml_path)
    sections = document_sections(xml_path)
    commentaries = document_commentaries(xml_path)
    return render_document_markdown_from_parts(metadata, prelims, sections, commentaries)


def render_document_markdown_from_xml(content: bytes | str) -> str:
    root = ElementTree.fromstring(content)
    metadata = document_metadata_from_root(root)
    prelims = document_prelims_from_root(root)
    sections = document_sections_from_root(root)
    commentaries = document_commentaries_from_root(root)
    return render_document_markdown_from_parts(metadata, prelims, sections, commentaries)


def render_document_markdown_from_parts(
    metadata: DocumentMetadata,
    prelims: DocumentPrelims,
    sections: list[DocumentSection],
    commentaries: dict[str, str],
) -> str:
    blocks = [_frontmatter(metadata), f"# {prelims.title}"]
    blocks.extend(block for block in [prelims.number, prelims.long_title] if block)

    if not sections and not prelims.long_title:
        blocks.append("Source XML contains metadata only; full text may be available in PDF or another source format.")
        if metadata.pdf_alternatives:
            blocks.append("\n".join(["PDF alternatives:", *[f"- {url}" for url in metadata.pdf_alternatives]]))

    for section in sections:
        blocks.append(_section_heading(section))
        blocks.extend(f"> Commentary: {commentaries[ref]}" for ref in section.commentary_refs if ref in commentaries)
        blocks.extend(section.lines)

    return "\n\n".join(blocks) + "\n"


def markdown_output_target_from_xml_path(xml_path: Path, output_root: Path) -> MarkdownOutputTarget:
    try:
        relative_path = xml_path.resolve().relative_to((output_root / "xml").resolve())
    except ValueError as error:
        raise ValueError(f"{xml_path} is not under {output_root / 'xml'}") from error

    parts = relative_path.parts
    if len(parts) < 4 or parts[-1] != "data.xml":
        raise ValueError(f"{xml_path} does not look like fetched XML")

    if parts[0] == "enacted":
        return MarkdownOutputTarget(source_path=parts[1:-1], as_enacted=True)

    if parts[0] == "point-in-time":
        if len(parts) < 5:
            raise ValueError(f"{xml_path} does not include a point-in-time snapshot date")
        return MarkdownOutputTarget(source_path=parts[2:-1], as_enacted=False, at=parts[1])

    raise ValueError(f"{xml_path} is not in an enacted or point-in-time XML tree")


def write_document_markdown(
    markdown: str,
    output_root: Path,
    source_path: tuple[str, ...],
    as_enacted: bool = False,
    at: str | None = None,
) -> Path:
    if as_enacted and at is not None:
        raise ValueError("Cannot write enacted Markdown at a point in time.")
    if not source_path:
        raise ValueError("Cannot write Markdown without a document source path.")

    output_path = Path(*source_path[:-1]) / f"{source_path[-1]}.md"
    if as_enacted:
        path = output_root / "markdown" / "enacted" / output_path
    else:
        if at is None:
            raise ValueError("Point-in-time Markdown requires a snapshot date.")
        path = output_root / "markdown" / "point-in-time" / at / output_path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown)
    return path


def convert_document_markdown(xml_path: Path, output_root: Path) -> Path:
    target = markdown_output_target_from_xml_path(xml_path, output_root)
    return write_document_markdown(
        render_document_markdown(xml_path),
        output_root=output_root,
        source_path=target.source_path,
        as_enacted=target.as_enacted,
        at=target.at,
    )


def convert_xml_tree(
    xml_root: Path,
    output_root: Path,
    report: ConversionReport | None = None,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    paths: list[Path] = []

    for index, xml_path in enumerate(sorted(xml_root.rglob("data.xml")), start=1):
        try:
            path = convert_document_markdown(xml_path, output_root=output_root)
        except Exception as error:
            failure = ConversionFailure(
                input_path=str(xml_path),
                source_path=_source_path_for_failure(xml_path, output_root),
                error=str(error),
            )
            if report is not None:
                report.failures.append(failure)
            _log(log, f"Failed converting {xml_path}: {error}")
        else:
            paths.append(path)
            if report is not None:
                report.converted_paths.append(str(path))

        if index % CONVERSION_LOG_INTERVAL == 0:
            failure_count = len(report.failures) if report is not None else 0
            _log(
                log,
                f"Processed {index} XML documents under {xml_root}: {len(paths)} converted, {failure_count} failures",
            )

    return paths


def write_conversion_report(report: ConversionReport, output_root: Path) -> Path:
    if report.mode == "enacted":
        path = output_root / "reports" / "convert" / "enacted" / report.legislation_type / "report.json"
    elif report.mode == "point-in-time":
        if report.at is None:
            raise ValueError("Point-in-time conversion reports require a snapshot date.")
        path = output_root / "reports" / "convert" / "point-in-time" / report.at / f"{report.legislation_type}.json"
    else:
        raise ValueError(f"Unknown conversion report mode: {report.mode}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_report_json(report), indent=2) + "\n")
    return path


def _source_path_for_failure(xml_path: Path, output_root: Path) -> tuple[str, ...]:
    try:
        return markdown_output_target_from_xml_path(xml_path, output_root).source_path
    except ValueError:
        return ()


def _report_json(report: ConversionReport) -> dict[str, object]:
    return {
        "mode": report.mode,
        "legislation_type": report.legislation_type,
        "at": report.at,
        "converted_paths": report.converted_paths,
        "failures": [
            {
                "input_path": failure.input_path,
                "source_path": list(failure.source_path),
                "error": failure.error,
            }
            for failure in report.failures
        ],
    }


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log is not None:
        log(message)


def _body_sections(element: ElementTree.Element) -> list[DocumentSection]:
    sections: list[DocumentSection] = []

    for child in element:
        tag = _local_name(child.tag)
        if tag == "P1group":
            sections.append(_p1group_section(child))
        elif tag == "P":
            section = _loose_paragraph_section(child)
            if section.lines:
                sections.append(section)
        elif tag == "P1":
            section = _numbered_section(child)
            if section.lines:
                sections.append(section)
        elif tag in {"Pblock", "Part", "Chapter"}:
            child_sections = _body_sections(child)
            if child_sections:
                sections.extend(child_sections)
            else:
                section = _container_section(child)
                if section.lines:
                    sections.append(section)
        else:
            sections.extend(_body_sections(child))

    return sections


def _p1group_section(group: ElementTree.Element) -> DocumentSection:
    title = group.findtext("leg:Title", namespaces=NAMESPACES) or ""
    number_element = group.find("leg:P1/leg:Pnumber", namespaces=NAMESPACES)
    return DocumentSection(
        number=_element_text(number_element) if number_element is not None else "",
        title=" ".join(title.split()),
        lines=_section_lines(group),
        commentary_refs=_commentary_refs(number_element),
    )


def _loose_paragraph_section(paragraph: ElementTree.Element) -> DocumentSection:
    return DocumentSection(
        number="",
        title="",
        lines=_paragraph_lines(paragraph) or [_element_text(paragraph)],
        commentary_refs=_commentary_refs(paragraph),
    )


def _numbered_section(paragraph: ElementTree.Element) -> DocumentSection:
    number_element = paragraph.find("leg:Pnumber", namespaces=NAMESPACES)
    para_element = paragraph.find(f"leg:{_local_name(paragraph.tag)}para", namespaces=NAMESPACES)
    return DocumentSection(
        number=_element_text(number_element) if number_element is not None else "",
        title="",
        lines=_paragraph_lines(para_element) if para_element is not None else _paragraph_lines(paragraph),
        commentary_refs=_commentary_refs(number_element),
    )


def _container_section(container: ElementTree.Element) -> DocumentSection:
    title = container.findtext("leg:Title", namespaces=NAMESPACES) or ""
    return DocumentSection(
        number="",
        title=" ".join(title.split()),
        lines=_paragraph_lines(container) or [_element_text(container)],
        commentary_refs=_commentary_refs(container),
    )


def _section_lines(group: ElementTree.Element) -> list[str]:
    paragraph = group.find("leg:P1/leg:P1para", namespaces=NAMESPACES)
    if paragraph is not None:
        return _paragraph_lines(paragraph)
    return _paragraph_lines(group)


def _section_heading(section: DocumentSection) -> str:
    heading = " ".join(part for part in [section.number, section.title] if part)
    return f"## {heading or 'Section'}"


def _commentary_refs(element: ElementTree.Element | None) -> list[str]:
    if element is None:
        return []
    return [
        ref
        for commentary_ref in element.findall(".//leg:CommentaryRef", namespaces=NAMESPACES)
        if (ref := commentary_ref.attrib.get("Ref")) is not None
    ]


def _metadata_number(root: ElementTree.Element) -> str | None:
    year = root.find(".//ukm:Year", namespaces=NAMESPACES)
    number = root.find(".//ukm:Number", namespaces=NAMESPACES)
    year_value = year.attrib.get("Value") if year is not None else None
    number_value = number.attrib.get("Value") if number is not None else None
    if year_value is None or number_value is None:
        return None
    return f"{year_value} Chapter {number_value}"


def _pdf_alternatives(root: ElementTree.Element) -> tuple[str, ...]:
    urls: list[str] = []

    for link in root.findall(".//atom:link", namespaces=NAMESPACES):
        if link.attrib.get("type") == "application/pdf" and (href := link.attrib.get("href")) is not None:
            urls.append(href)

    for alternative in root.findall(".//ukm:Alternative", namespaces=NAMESPACES):
        uri = alternative.attrib.get("URI")
        if uri is not None and uri.lower().endswith(".pdf"):
            urls.append(uri)

    return tuple(dict.fromkeys(urls))


def _frontmatter(metadata: DocumentMetadata) -> str:
    lines = [
        "---",
        f'title: "{_yaml_string(metadata.title)}"',
        f'document_uri: "{_yaml_string(metadata.document_uri)}"',
    ]
    if metadata.status is not None:
        lines.append(f'status: "{_yaml_string(metadata.status)}"')
    if metadata.extent is not None:
        lines.append(f'extent: "{_yaml_string(metadata.extent)}"')
    if metadata.pdf_alternatives:
        lines.append("pdf_alternatives:")
        lines.extend(f'  - "{_yaml_string(url)}"' for url in metadata.pdf_alternatives)
    lines.append("---")
    return "\n".join(lines)


def _yaml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _paragraph_lines(paragraph: ElementTree.Element) -> list[str]:
    lines: list[str] = []

    for child in paragraph:
        tag = _local_name(child.tag)
        if tag == "Text":
            lines.append(_element_text(child))
        elif tag in {"P1", "P2", "P3"}:
            lines.extend(_numbered_paragraph_lines(child))

    return [line for line in lines if line]


def _numbered_paragraph_lines(paragraph: ElementTree.Element) -> list[str]:
    number_element = paragraph.find("leg:Pnumber", namespaces=NAMESPACES)
    para_element = paragraph.find(f"leg:{_local_name(paragraph.tag)}para", namespaces=NAMESPACES)

    if number_element is None or para_element is None:
        return []

    number = _element_text(number_element)
    child_lines = _paragraph_lines(para_element)
    if child_lines:
        return [f"({number}) {child_lines[0]}", *child_lines[1:]]

    text = _element_text(para_element)
    if text:
        return [f"({number}) {text}"]

    return []


def _element_text(element: ElementTree.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
