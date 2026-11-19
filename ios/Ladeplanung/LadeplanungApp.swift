import SwiftUI

@main
struct LadeplanungApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                UebersichtView()
                    .tabItem { Label("Übersicht", systemImage: "bolt.car") }
                EinstellungenView()
                    .tabItem { Label("Einstellungen", systemImage: "slider.horizontal.3") }
            }
        }
    }
}
