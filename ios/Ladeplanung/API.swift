import Foundation

enum APIFehler: LocalizedError {
    case keineAdresse
    case ungueltigeAdresse
    case server(String)
    case netz(String)

    var errorDescription: String? {
        switch self {
        case .keineAdresse: return "Bitte zuerst die Adresse der Ladeplanung in den Einstellungen eintragen."
        case .ungueltigeAdresse: return "Die Adresse ist ungültig. Beispiel: http://192.168.178.62:5055"
        case .server(let text): return text
        case .netz(let text): return "Keine Verbindung zur Ladeplanung: \(text)"
        }
    }
}

/// Spricht die Webapp/das Add-on im Heimnetz an.
final class APIClient {
    static let shared = APIClient()
    static let adresseSchluessel = "serverAdresse"

    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    var basis: URL? {
        let text = UserDefaults.standard.string(forKey: Self.adresseSchluessel) ?? ""
        let bereinigt = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !bereinigt.isEmpty else { return nil }
        return URL(string: bereinigt.hasSuffix("/") ? String(bereinigt.dropLast()) : bereinigt)
    }

    func get<T: Decodable>(_ pfad: String, query: [URLQueryItem] = []) async throws -> T {
        var anfrage = URLRequest(url: try url(pfad, query: query))
        anfrage.timeoutInterval = 60
        return try await senden(anfrage)
    }

    func post<T: Decodable, B: Encodable>(_ pfad: String, body: B) async throws -> T {
        var anfrage = URLRequest(url: try url(pfad, query: []))
        anfrage.httpMethod = "POST"
        anfrage.setValue("application/json", forHTTPHeaderField: "Content-Type")
        anfrage.httpBody = try encoder.encode(body)
        anfrage.timeoutInterval = 60
        return try await senden(anfrage)
    }

    private func url(_ pfad: String, query: [URLQueryItem]) throws -> URL {
        guard let basis else { throw APIFehler.keineAdresse }
        guard var komponenten = URLComponents(url: basis.appendingPathComponent(pfad), resolvingAgainstBaseURL: false) else {
            throw APIFehler.ungueltigeAdresse
        }
        if !query.isEmpty { komponenten.queryItems = query }
        guard let ziel = komponenten.url else { throw APIFehler.ungueltigeAdresse }
        return ziel
    }

    private func senden<T: Decodable>(_ anfrage: URLRequest) async throws -> T {
        let daten: Data
        let antwort: URLResponse
        do {
            (daten, antwort) = try await URLSession.shared.data(for: anfrage)
        } catch {
            throw APIFehler.netz(error.localizedDescription)
        }
        let status = (antwort as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            if let fehler = try? decoder.decode(ServerFehler.self, from: daten) {
                throw APIFehler.server(fehler.fehler)
            }
            throw APIFehler.server("Fehler \(status) vom Server.")
        }
        return try decoder.decode(T.self, from: daten)
    }
}

/// Antwort von POST /api/benachrichtigung/test: {"ok": true}
struct TestAntwort: Codable { let ok: Bool? }
