import Foundation

/// Einstellungen, so wie das Add-on sie liefert und speichert.
struct Einstellungen: Codable, Equatable {
    var benachrichtigungAktiv: Bool = false
    var uhrzeit: String = "18:00"
    var bedarfKwh: Double = 10.0
    var notifyDienst: String = ""
    var ladeleistungKw: Double = 11.0
    var preisgrenzeCt: Double = 36.0
    var sockelCt: Double = 19.5
    var fensterStart: Int = 22
    var fensterEnde: Int = 6
    var tage: Int = 7

    enum CodingKeys: String, CodingKey {
        case benachrichtigungAktiv = "benachrichtigung_aktiv"
        case uhrzeit
        case bedarfKwh = "bedarf_kwh"
        case notifyDienst = "notify_dienst"
        case ladeleistungKw = "ladeleistung_kw"
        case preisgrenzeCt = "preisgrenze_ct"
        case sockelCt = "sockel_ct"
        case fensterStart = "fenster_start"
        case fensterEnde = "fenster_ende"
        case tage
    }
}

struct Ladeblock: Codable, Hashable {
    let von: String
    let bis: String
    let stunden: Double
}

/// Ergebnis von /api/entscheidung
struct Entscheidung: Codable {
    let lohnt: Bool
    let grund: String
    let heuteKwh: Double
    let bedarfKwh: Double
    let nacht: String
    let ladebloecke: [Ladeblock]

    enum CodingKeys: String, CodingKey {
        case lohnt, grund, nacht, ladebloecke
        case heuteKwh = "heute_kwh"
        case bedarfKwh = "bedarf_kwh"
    }
}

struct Nacht: Codable, Identifiable {
    let datum: String
    let label: String
    let ladbarKwh: Double
    let stundenGuenstig: Double
    let schnittBruttoCt: Double?
    let kostenEur: Double
    let datenbasis: String
    let ladebloecke: [Ladeblock]

    var id: String { datum }

    enum CodingKeys: String, CodingKey {
        case datum, label, datenbasis, ladebloecke
        case ladbarKwh = "ladbar_kwh"
        case stundenGuenstig = "stunden_guenstig"
        case schnittBruttoCt = "schnitt_brutto_ct"
        case kostenEur = "kosten_eur"
    }
}

struct Gesamt: Codable {
    let stunden: Double
    let kwh: Double
    let kostenEur: Double
    let preisCt: Double?

    enum CodingKeys: String, CodingKey {
        case stunden, kwh
        case kostenEur = "kosten_eur"
        case preisCt = "preis_ct"
    }
}

/// Ergebnis von /api/plan
struct Plan: Codable {
    let erstellt: String
    let naechte: [Nacht]
    let gesamt: Gesamt
}

/// Fehlerantwort des Servers: {"fehler": "..."}
struct ServerFehler: Codable {
    let fehler: String
}
