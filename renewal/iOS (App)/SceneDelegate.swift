//
//  SceneDelegate.swift
//  iOS (App)
//
//  Created by Visar on 7.9.26.
//

import UIKit

class SceneDelegate: UIResponder, UIWindowSceneDelegate {

    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: windowScene)
        let controller = UIViewController()
        controller.view.backgroundColor = .systemBackground
        let label = UILabel()
        label.numberOfLines = 0
        label.text = "Reader Extensions\n\nEnable each extension separately in Settings → Apps → Safari → Extensions.\n\nGallery Reader: Hitomi and IMHentai.\nKM Explorer: ytboob.com.\nStream Viewer: tango.me.\nManga Reader: EzManga, Qi Manga, Yaksha Comics, Asura Scans, Scythe Scans and Lua Comic.\n\nDisable the matching userscript while its extension is enabled. Reload the site after granting access.\n\nEach extension keeps its existing website data and server connections. This is separate from the offline Gallery Reader app."
        label.translatesAutoresizingMaskIntoConstraints = false
        controller.view.addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: controller.view.safeAreaLayoutGuide.leadingAnchor, constant: 24),
            label.trailingAnchor.constraint(equalTo: controller.view.safeAreaLayoutGuide.trailingAnchor, constant: -24),
            label.centerYAnchor.constraint(equalTo: controller.view.centerYAnchor),
        ])
        window.rootViewController = controller
        self.window = window
        window.makeKeyAndVisible()
    }

}
