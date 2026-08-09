from statutory_duties import (
    INFERENCE_VALUES,
    PRIORITY_VALUES,
    STAGING_COLUMNS,
    document_id_from_enactment_uri,
    normalize_enum,
    normalize_modality,
    provision_kind_and_number,
    section_path_from_uris,
    staging_row_from_csv_row,
)

CSV_ROW = {
    "dutyTempId": "554637",
    "duty_uri": "http://www.legislation.gov.uk/id/duties/ukpga/Vict/52-53/39/2025-12-15/power/0001",
    "enactment": "http://www.legislation.gov.uk/id/ukpga/Vict/52-53/39",
    "enactmentTitle": "Judicial Factors (Scotland) Act 1889",
    "enactmentYear": "Vict/52-53",
    "enactmentType": "ukpga",
    "enactmentNum": "39",
    "section": "http://www.legislation.gov.uk/id/ukpga/Vict/52-53/39/section/7",
    "subsection": "2|3",
    "actor": "court",
    "actorIsBody": "court",
    "actorIsAlias": "",
    "actorDefinition": "",
    "body_uri": "",
    "modality": "power",
    "action": "determine whether a person has failed to comply",
    "condition": "",
    "inference": "implicit",
    "priority": "primary",
}


def test_document_id_from_enactment_uri_keeps_regnal_segments():
    assert (
        document_id_from_enactment_uri("http://www.legislation.gov.uk/id/ukpga/Vict/52-53/39") == "ukpga/Vict/52-53/39"
    )
    assert document_id_from_enactment_uri("https://example.com/other") is None


def test_section_path_is_relative_to_the_enactment():
    assert (
        section_path_from_uris(
            "http://www.legislation.gov.uk/id/ukpga/Vict/52-53/39/section/7",
            "http://www.legislation.gov.uk/id/ukpga/Vict/52-53/39",
        )
        == "section/7"
    )
    # Section URI under a different root than the enactment column still loses
    # the generic prefix.
    assert (
        section_path_from_uris(
            "http://www.legislation.gov.uk/id/uksi/2005/1803/regulation/3",
            "http://www.legislation.gov.uk/id/ukpga/2000/1",
        )
        == "uksi/2005/1803/regulation/3"
    )


def test_provision_kind_and_number_handles_simple_and_structured_paths():
    assert provision_kind_and_number("section/28D") == ("section", "28D")
    assert provision_kind_and_number("regulation/3") == ("regulation", "3")
    assert provision_kind_and_number("schedule/2/paragraph/5") == ("schedule", "2")
    # 'paragraph' is structure, not a number, so no top-level number is claimed.
    assert provision_kind_and_number("schedule/paragraph/3") == ("schedule", None)
    assert provision_kind_and_number("schedule/FIRST/paragraph/2") == ("schedule", None)
    assert provision_kind_and_number("schedule") == ("schedule", None)
    assert provision_kind_and_number("") == (None, None)


def test_modality_normalization_covers_dirty_values():
    assert normalize_modality("power") == "power"
    assert normalize_modality("duty") == "duty"
    assert normalize_modality("power and duty") == "both"
    assert normalize_modality("duty|power") == "both"
    assert normalize_modality("Missing") == "unknown"


def test_enum_normalization_drops_missing():
    assert normalize_enum("explicit", INFERENCE_VALUES) == "explicit"
    assert normalize_enum("Missing", INFERENCE_VALUES) is None
    assert normalize_enum("secondary", PRIORITY_VALUES) == "secondary"


def test_staging_row_from_csv_row():
    row = staging_row_from_csv_row(CSV_ROW, "duties_ukpga_20260330_part01.csv")
    staged = dict(zip(STAGING_COLUMNS, row, strict=True))
    assert staged["document_id"] == "ukpga/Vict/52-53/39"
    assert staged["enactment_type"] == "ukpga"
    assert staged["section_path"] == "section/7"
    assert staged["provision_kind"] == "section"
    assert staged["provision_number"] == "7"
    assert staged["subsections"] == ["2", "3"]
    assert staged["actor_is_body"] == "court"
    assert staged["actor_is_alias"] is None
    assert staged["condition"] is None
    assert staged["source_temp_id"] == 554637
    assert staged["source_file"] == "duties_ukpga_20260330_part01.csv"


def test_staging_row_prefers_uri_type_over_csv_label():
    row = dict(CSV_ROW)
    row["enactment"] = "http://www.legislation.gov.uk/id/asp/2025/9"
    row["section"] = "http://www.legislation.gov.uk/id/asp/2025/9/section/1"
    row["enactmentType"] = "ScottishAct"
    staged = dict(zip(STAGING_COLUMNS, staging_row_from_csv_row(row, "f.csv"), strict=True))
    assert staged["enactment_type"] == "asp"
    assert staged["document_id"] == "asp/2025/9"
