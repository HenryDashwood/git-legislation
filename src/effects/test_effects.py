from effects import textual_kind
from fetchers.legislationdotgovdotuk import (
    document_id_from_legislation_uri,
    effects_feed_url,
    parse_effects_feed,
    provision_kind_and_number,
)

EFFECTS_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:leg="http://www.legislation.gov.uk/namespaces/legislation"
      xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">
  <leg:page>1</leg:page>
  <leg:morePages>3</leg:morePages>
  <entry>
    <content type="text/xml">
      <ukm:Effect Type="words inserted" Applied="true" RequiresApplied="true"
          Modified="2026-07-14T11:48:17Z" EffectId="key-abc"
          URI="http://www.legislation.gov.uk/id/effect/key-abc"
          AffectedURI="http://www.legislation.gov.uk/id/ukpga/1971/77"
          AffectedProvisions="s. 28D(4)" AffectedYear="1971" AffectedNumber="77"
          AffectingURI="http://www.legislation.gov.uk/id/ukpga/2025/31"
          AffectingProvisions="s. 21(9)(b)" AffectingYear="2025" AffectingNumber="31">
        <ukm:AffectedTitle>Immigration Act 1971</ukm:AffectedTitle>
        <ukm:AffectedProvisions>
          <ukm:Section Ref="section-28D-4"
              URI="http://www.legislation.gov.uk/id/ukpga/1971/77/section/28D/4">s. 28D(4)</ukm:Section>
        </ukm:AffectedProvisions>
        <ukm:AffectingTitle>Border Security, Asylum and Immigration Act 2025</ukm:AffectingTitle>
        <ukm:AffectingProvisions>
          <ukm:Section Ref="section-21-9-b"
              URI="http://www.legislation.gov.uk/id/ukpga/2025/31/section/21/9/b">s. 21(9)(b)</ukm:Section>
        </ukm:AffectingProvisions>
        <ukm:CommencementAuthority>
          <ukm:Section Ref="regulation-2-d"
              URI="http://www.legislation.gov.uk/id/uksi/2025/1318/regulation/2/d">reg. 2(d)</ukm:Section>
        </ukm:CommencementAuthority>
        <ukm:InForceDates>
          <ukm:InForce Applied="true" Prospective="true" Qualification=""/>
          <ukm:InForce Date="2026-01-05" Qualification="wholly in force"
              CommencingURI="http://www.legislation.gov.uk/id/uksi/2025/1318"/>
        </ukm:InForceDates>
      </ukm:Effect>
    </content>
  </entry>
  <entry>
    <content type="text/xml">
      <ukm:Effect Type="inserted" Applied="false" RequiresApplied="true" EffectId="key-pending"
          AffectedProvisions="s. 3(1A)"
          AffectingURI="http://www.legislation.gov.uk/id/ukpga/2025/31" AffectingProvisions="s. 22(4)">
        <ukm:AffectedTitle></ukm:AffectedTitle>
        <ukm:InForceDates>
          <ukm:InForce Applied="false" Prospective="true" Qualification=""/>
        </ukm:InForceDates>
      </ukm:Effect>
    </content>
  </entry>
</feed>
"""


def test_parse_effects_feed_reads_effect_and_more_pages() -> None:
    effects, more_pages = parse_effects_feed(EFFECTS_FEED)

    assert more_pages == 3
    assert len(effects) == 2
    effect = effects[0]
    assert effect.id == "key-abc"
    assert effect.effect_type == "words inserted"
    assert effect.applied
    assert effect.affected_document_id == "ukpga/1971/77"
    assert effect.affected_title == "Immigration Act 1971"
    assert effect.affecting_document_id == "ukpga/2025/31"
    assert effect.affecting_provisions == "s. 21(9)(b)"


def test_parse_effects_feed_picks_dated_in_force_over_prospective_placeholder() -> None:
    effect = parse_effects_feed(EFFECTS_FEED)[0][0]

    assert effect.in_force_date == "2026-01-05"
    assert effect.in_force_qualification == "wholly in force"
    assert effect.commencing_document_id == "uksi/2025/1318"
    assert not effect.prospective


def test_parse_effects_feed_marks_undated_effect_prospective() -> None:
    effect = parse_effects_feed(EFFECTS_FEED)[0][1]

    assert effect.prospective
    assert effect.in_force_date is None
    assert effect.affected_document_id is None
    assert effect.affected_title is None


def test_parse_effects_feed_extracts_provision_refs_per_side() -> None:
    effect = parse_effects_feed(EFFECTS_FEED)[0][0]
    by_side = {provision.side: provision for provision in effect.provisions}

    assert by_side["affected"].section_number == "28D"
    assert by_side["affected"].provision_kind == "section"
    assert by_side["affected"].label == "s. 28D(4)"
    assert by_side["affecting"].section_number == "21"
    assert by_side["commencing"].provision_kind == "regulation"
    assert by_side["commencing"].section_number == "2"


def test_document_id_from_legislation_uri_strips_id_prefix() -> None:
    assert document_id_from_legislation_uri("http://www.legislation.gov.uk/id/ukpga/1971/77") == "ukpga/1971/77"
    assert document_id_from_legislation_uri("https://www.legislation.gov.uk/uksi/2025/1318") == "uksi/2025/1318"
    assert document_id_from_legislation_uri(None) is None
    assert document_id_from_legislation_uri("") is None


def test_effects_feed_url_supports_both_directions() -> None:
    assert effects_feed_url(("ukpga", "1971", "77"), page=2) == (
        "https://www.legislation.gov.uk/changes/affected/ukpga/1971/77/data.feed?page=2"
    )
    assert effects_feed_url(("ukpga", "2025", "31"), direction="affecting") == (
        "https://www.legislation.gov.uk/changes/affecting/ukpga/2025/31/data.feed?page=1"
    )


def test_textual_kind_separates_textual_non_textual_and_commencement() -> None:
    assert textual_kind("words inserted") == "T"
    assert textual_kind("repealed") == "T"
    assert textual_kind("applied") == "NT"
    assert textual_kind("power to amend") == "NT"
    assert textual_kind("commencement order") == "CO"
    assert textual_kind("coming into force") == "CO"
    assert textual_kind("in force") == "CO"
    assert textual_kind("") == "UN"
    assert textual_kind("   ") == "UN"


SAME_DATE_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:leg="http://www.legislation.gov.uk/namespaces/legislation"
      xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">
  <leg:morePages>0</leg:morePages>
  <entry><content type="text/xml">
    <ukm:Effect Type="repealed" EffectId="key-same-date" AffectedProvisions="s. 1">
      <ukm:InForceDates>
        <ukm:InForce Date="2001-04-01" Qualification="for specified purposes"/>
        <ukm:InForce Date="2001-04-01" CommencingURI="http://www.legislation.gov.uk/id/uksi/2001/1"/>
      </ukm:InForceDates>
    </ukm:Effect>
  </content></entry>
</feed>
"""


def test_parse_effects_feed_handles_duplicate_in_force_dates_with_partial_fields() -> None:
    effects, _ = parse_effects_feed(SAME_DATE_FEED)

    assert effects[0].in_force_date == "2001-04-01"


def test_provision_kind_and_number_prefers_ref() -> None:
    assert provision_kind_and_number("section-28D-4", "s. 28D(4)") == ("section", "28D")
    assert provision_kind_and_number("schedule-5-paragraph-1", "Sch. 5 para. 1") == ("schedule", "5")


def test_provision_kind_and_number_falls_back_to_label_when_ref_is_unusable() -> None:
    assert provision_kind_and_number(None, "s. 24(3)") == ("section", "24")
    assert provision_kind_and_number("part-I", "Pt. 1") == ("part", "1")
    assert provision_kind_and_number(None, "Sch. 12 para. 4") == ("schedule", "12")
    assert provision_kind_and_number(None, "reg. 2(d)") == ("regulation", "2")


def test_provision_kind_and_number_gives_up_on_ambiguous_labels() -> None:
    assert provision_kind_and_number(None, "(4)-(7)") == (None, None)
    assert provision_kind_and_number(None, "7") == (None, None)
    assert provision_kind_and_number(None, "") == (None, None)
