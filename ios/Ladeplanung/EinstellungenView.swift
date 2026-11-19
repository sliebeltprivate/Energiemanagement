import SwiftUI

@MainActor
final class EinstellungenModell: ObservableObject {
    @Published var einstellungen = Einstellungen()
    @Published var uhrzeit = Date()
    @Published var meldung: String?
    @Published var istFehler = false
    @Published var laedt = false

    func laden() async {
        laedt = true
        defer { laedt = false }
        do {
            let geladen: Einstellungen = try await APIClient.shared.get("api/einstellungen")
            einstellungen = geladen
            uhrzeit = Self.datum(aus: geladen.uhrzeit)
            meldung = nil
        } catch {
            meldung = error.localizedDescription
            istFehler = true
        }
    }

    func speichern() async {
        einstellungen.uhrzeit = Self.text(aus: uhrzeit)
        do {
            let gespeichert: Einstellungen = try await APIClient.shared.post("api/einstellungen", body: einstellungen)
            einstellungen = gespeichert
            meldung = "Gespeichert."
            istFehler = false
        } catch {
            meldung = error.localizedDescription
            istFehler = true
        }
    }

    func testen() async {
        do {
            let _: TestAntwort = try await APIClient.shared.post("api/benachrichtigung/test", body: EmptyBody())
            meldung = "Testnachricht gesendet."
            istFehler = false
        } catch {
            meldung = error.localizedDescription
            istFehler = true
        }
    }

    private static func datum(aus text: String) -> Date {
        let teile = text.split(separator: ":").compactMap { Int($0) }
        var komp = DateComponents()
        komp.hour = teile.first ?? 18
        komp.minute = teile.count > 1 ? teile[1] : 0
        return Calendar.current.date(from: komp) ?? Date()
    }

    private static func text(aus datum: Date) -> String {
        let komp = Calendar.current.dateComponents([.hour, .minute], from: datum)
        return String(format: "%02d:%02d", komp.hour ?? 18, komp.minute ?? 0)
    }
}

struct EmptyBody: Codable {}

struct EinstellungenView: View {
    @StateObject private var modell = EinstellungenModell()
    @AppStorage(APIClient.adresseSchluessel) private var serverAdresse = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Verbindung") {
                    TextField("http://192.168.178.62:5055", text: $serverAdresse)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Adresse der Ladeplanung im Heimnetz (Port 5055).")
                        .font(.caption).foregroundStyle(.secondary)
                }

                Section("Benachrichtigung") {
                    Toggle("Benachrichtigung aktiv", isOn: $modell.einstellungen.benachrichtigungAktiv)
                    DatePicker("Uhrzeit", selection: $modell.uhrzeit, displayedComponents: .hourAndMinute)
                    VStack(alignment: .leading) {
                        Text("Energiebedarf über Nacht: \(String(format: "%.1f", modell.einstellungen.bedarfKwh)) kWh")
                        Slider(value: $modell.einstellungen.bedarfKwh, in: 1...40, step: 0.5)
                    }
                    TextField("Dienst, z. B. mobile_app_iphone", text: $modell.einstellungen.notifyDienst)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("Testnachricht senden") {
                        Task { await modell.testen() }
                    }
                }

                Section("Laden") {
                    Picker("Ladeleistung", selection: $modell.einstellungen.ladeleistungKw) {
                        Text("2,3 kW").tag(2.3)
                        Text("11 kW").tag(11.0)
                    }
                    VStack(alignment: .leading) {
                        Text("Preisgrenze brutto: \(Int(modell.einstellungen.preisgrenzeCt)) ct/kWh")
                        Slider(value: $modell.einstellungen.preisgrenzeCt, in: 20...50, step: 1)
                    }
                    Picker("Fenster von", selection: $modell.einstellungen.fensterStart) {
                        ForEach(0..<24, id: \.self) { Text(String(format: "%02d Uhr", $0)).tag($0) }
                    }
                    Picker("Fenster bis", selection: $modell.einstellungen.fensterEnde) {
                        ForEach(0..<24, id: \.self) { Text(String(format: "%02d Uhr", $0)).tag($0) }
                    }
                    Picker("Anzahl Nächte", selection: $modell.einstellungen.tage) {
                        ForEach(1...7, id: \.self) { Text("\($0)").tag($0) }
                    }
                }

                if let meldung = modell.meldung {
                    Section {
                        Text(meldung)
                            .foregroundStyle(modell.istFehler ? .red : .green)
                    }
                }

                Section {
                    Button("Speichern") {
                        Task { await modell.speichern() }
                    }
                    .bold()
                }
            }
            .navigationTitle("Einstellungen")
            .task { await modell.laden() }
            .overlay {
                if modell.laedt { ProgressView() }
            }
        }
    }
}
