import SwiftUI

@MainActor
final class UebersichtModell: ObservableObject {
    @Published var entscheidung: Entscheidung?
    @Published var plan: Plan?
    @Published var fehler: String?
    @Published var laedt = false

    func laden() async {
        laedt = true
        defer { laedt = false }
        do {
            async let e: Entscheidung = APIClient.shared.get("api/entscheidung")
            async let p: Plan = APIClient.shared.get("api/plan")
            entscheidung = try await e
            plan = try await p
            fehler = nil
        } catch {
            fehler = error.localizedDescription
        }
    }
}

struct UebersichtView: View {
    @StateObject private var modell = UebersichtModell()

    var body: some View {
        NavigationStack {
            List {
                if let fehler = modell.fehler {
                    Section {
                        Label(fehler, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                    }
                }

                if let e = modell.entscheidung {
                    Section {
                        EntscheidungKarte(entscheidung: e)
                    }
                }

                if let p = modell.plan {
                    Section("Gesamt") {
                        KennzahlZeile(titel: "kWh", wert: String(format: "%.1f", p.gesamt.kwh))
                        KennzahlZeile(titel: "Ladezeit", wert: String(format: "%.1f h", p.gesamt.stunden))
                        KennzahlZeile(titel: "Kosten ca.", wert: String(format: "%.2f €", p.gesamt.kostenEur))
                        if let preis = p.gesamt.preisCt {
                            KennzahlZeile(titel: "Ø Preis pro kWh", wert: String(format: "%.1f ct brutto", preis))
                        }
                    }

                    Section("Nächte") {
                        ForEach(p.naechte) { nacht in
                            NachtZeile(nacht: nacht)
                        }
                    }
                }
            }
            .navigationTitle("Ladeplanung")
            .refreshable { await modell.laden() }
            .overlay {
                if modell.laedt && modell.plan == nil {
                    ProgressView("Lade Strompreise …")
                }
            }
            .task { await modell.laden() }
        }
    }
}

struct EntscheidungKarte: View {
    let entscheidung: Entscheidung

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(
                entscheidung.lohnt ? "Heute Nacht anstecken" : "Heute Nacht nicht nötig",
                systemImage: entscheidung.lohnt ? "checkmark.circle.fill" : "minus.circle"
            )
            .font(.headline)
            .foregroundStyle(entscheidung.lohnt ? .green : .secondary)

            Text(entscheidung.grund)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if entscheidung.lohnt && !entscheidung.ladebloecke.isEmpty {
                ForEach(entscheidung.ladebloecke, id: \.self) { block in
                    Text("\(block.von) – \(block.bis) Uhr (\(String(format: "%.1f", block.stunden)) h)")
                        .font(.callout.monospacedDigit())
                }
            }
        }
        .padding(.vertical, 4)
    }
}

struct NachtZeile: View {
    let nacht: Nacht

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(nacht.label).font(.headline)
                Spacer()
                Text(nacht.datenbasis)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(String(format: "%.1f kWh · %.1f h · %.2f €", nacht.ladbarKwh, nacht.stundenGuenstig, nacht.kostenEur))
                .font(.subheadline)
            if let preis = nacht.schnittBruttoCt {
                Text(String(format: "Ø %.1f ct brutto", preis))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }
}

struct KennzahlZeile: View {
    let titel: String
    let wert: String

    var body: some View {
        HStack {
            Text(titel)
            Spacer()
            Text(wert).monospacedDigit().foregroundStyle(.secondary)
        }
    }
}
