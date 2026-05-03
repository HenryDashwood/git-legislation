from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

NAMESPACES = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "leg": "http://www.legislation.gov.uk/namespaces/legislation",
}


@dataclass(frozen=True)
class DocumentMetadata:
    title: str
    document_uri: str
    status: str | None
    extent: str | None


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


def document_title(xml_path: Path) -> str:
    root = ElementTree.parse(xml_path).getroot()
    title = root.findtext(".//dc:title", namespaces=NAMESPACES)
    if title is None:
        raise ValueError(f"No document title found in {xml_path}")
    return title


def document_metadata(xml_path: Path) -> DocumentMetadata:
    root = ElementTree.parse(xml_path).getroot()
    title = root.findtext(".//dc:title", namespaces=NAMESPACES)
    if title is None:
        raise ValueError(f"No document title found in {xml_path}")

    document_uri = root.attrib.get("DocumentURI")
    if document_uri is None:
        raise ValueError(f"No DocumentURI found in {xml_path}")

    return DocumentMetadata(
        title=title,
        document_uri=document_uri,
        status=root.attrib.get("Status"),
        extent=root.attrib.get("RestrictExtent"),
    )


def document_prelims(xml_path: Path) -> DocumentPrelims:
    root = ElementTree.parse(xml_path).getroot()
    title = root.findtext(".//leg:PrimaryPrelims/leg:Title", namespaces=NAMESPACES)
    number = root.findtext(".//leg:PrimaryPrelims/leg:Number", namespaces=NAMESPACES)
    long_title_element = root.find(".//leg:PrimaryPrelims/leg:LongTitle", namespaces=NAMESPACES)

    if title is None:
        raise ValueError(f"No prelims title found in {xml_path}")
    if number is None:
        raise ValueError(f"No prelims number found in {xml_path}")
    if long_title_element is None:
        raise ValueError(f"No long title found in {xml_path}")

    return DocumentPrelims(
        title=title, number=number, long_title=" ".join("".join(long_title_element.itertext()).split())
    )


def document_sections(xml_path: Path) -> list[DocumentSection]:
    root = ElementTree.parse(xml_path).getroot()
    sections: list[DocumentSection] = []

    for group in root.findall(".//leg:Body/leg:P1group", namespaces=NAMESPACES):
        title = group.findtext("leg:Title", namespaces=NAMESPACES)
        number_element = group.find("leg:P1/leg:Pnumber", namespaces=NAMESPACES)

        if title is None:
            raise ValueError(f"Section without title found in {xml_path}")
        if number_element is None:
            raise ValueError(f"Section without number found in {xml_path}")

        sections.append(
            DocumentSection(
                number=" ".join("".join(number_element.itertext()).split()),
                title=" ".join(title.split()),
                lines=_section_lines(group),
            )
        )

    return sections


def render_document_markdown(xml_path: Path) -> str:
    prelims = document_prelims(xml_path)
    sections = document_sections(xml_path)

    blocks = [f"# {prelims.title}", prelims.number, prelims.long_title]

    for section in sections:
        blocks.append(f"## {section.number} {section.title}")
        blocks.extend(section.lines)

    return "\n\n".join(blocks) + "\n"


def write_document_markdown(
    markdown: str, legislation_type: str, year: int, number: int, output_root: Path
) -> Path:
    path = output_root / "markdown" / "enacted" / legislation_type / str(year) / f"{number}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown)
    return path


def _section_lines(group: ElementTree.Element) -> list[str]:
    paragraph = group.find("leg:P1/leg:P1para", namespaces=NAMESPACES)
    if paragraph is None:
        return []
    return _paragraph_lines(paragraph)


def _paragraph_lines(paragraph: ElementTree.Element) -> list[str]:
    lines: list[str] = []

    for child in paragraph:
        tag = _local_name(child.tag)
        if tag == "Text":
            lines.append(_element_text(child))
        elif tag in {"P2", "P3"}:
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
