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
        label.text = "Gallery Reader Extension\n\nEnable in Settings → Apps → Safari → Extensions. Allow Hitomi and IMHentai.\n\nDisable the Gallery Reader userscript while testing. Reload the site after granting access.\n\nThis is separate from the offline Gallery Reader app."
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
