"""Shared API parameter types."""

from enum import StrEnum


class LegislationTypeCode(StrEnum):
    AEP = "aep"
    AOSP = "aosp"
    AIP = "aip"
    APGB = "apgb"
    GBPPA = "gbppa"
    GBLA = "gbla"
    UKPGA = "ukpga"
    UKLA = "ukla"
    UKPPA = "ukppa"
    APNI = "apni"
    UKCM = "ukcm"
    NISRO = "nisro"
    UKSI = "uksi"
    NISI = "nisi"
    MNIA = "mnia"
    NISR = "nisr"
    ASP = "asp"
    SSI = "ssi"
    WSI = "wsi"
    NIA = "nia"
    MWA = "mwa"
    ANAW = "anaw"
    UKCI = "ukci"
    ASC = "asc"
    UKMO = "ukmo"


LEGISLATION_TYPE_LABELS: dict[LegislationTypeCode, str] = {
    LegislationTypeCode.AEP: "Acts of the English Parliament",
    LegislationTypeCode.AOSP: "Acts of the Old Scottish Parliament",
    LegislationTypeCode.AIP: "Acts of the Old Irish Parliament",
    LegislationTypeCode.APGB: "Acts of the Parliament of Great Britain",
    LegislationTypeCode.GBPPA: "Private and Personal Acts of the Parliament of Great Britain",
    LegislationTypeCode.GBLA: "Local Acts of the Parliament of Great Britain",
    LegislationTypeCode.UKPGA: "UK Public General Acts",
    LegislationTypeCode.UKLA: "UK Local Acts",
    LegislationTypeCode.UKPPA: "UK Private and Personal Acts",
    LegislationTypeCode.APNI: "Acts of the Northern Ireland Parliament",
    LegislationTypeCode.UKCM: "UK Church Measures",
    LegislationTypeCode.NISRO: "Northern Ireland Statutory Rules and Orders",
    LegislationTypeCode.UKSI: "UK Statutory Instruments",
    LegislationTypeCode.NISI: "Northern Ireland Orders in Council",
    LegislationTypeCode.MNIA: "Measures of the Northern Ireland Assembly",
    LegislationTypeCode.NISR: "Northern Ireland Statutory Rules",
    LegislationTypeCode.ASP: "Acts of the Scottish Parliament",
    LegislationTypeCode.SSI: "Scottish Statutory Instruments",
    LegislationTypeCode.WSI: "Wales Statutory Instruments",
    LegislationTypeCode.NIA: "Acts of the Northern Ireland Assembly",
    LegislationTypeCode.MWA: "Measures of the Welsh Assembly",
    LegislationTypeCode.ANAW: "Acts of the Welsh Assembly",
    LegislationTypeCode.UKCI: "UK Church Instruments",
    LegislationTypeCode.ASC: "Acts of Senedd Cymru",
    LegislationTypeCode.UKMO: "UK Ministerial Orders",
}
