import UIKit
import WebKit

@main @MainActor
final class HealthApp: UIResponder, UIApplicationDelegate {
    func application(_ application: UIApplication, configurationForConnecting session: UISceneSession,
                     options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let configuration = UISceneConfiguration(name: nil, sessionRole: session.role)
        configuration.delegateClass = HealthScene.self
        return configuration
    }
}
@MainActor final class HealthScene: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let scene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: scene)
        window.rootViewController = HealthController()
        self.window = window
        window.makeKeyAndVisible()
    }
}
@MainActor final class HealthController: UIViewController, WKNavigationDelegate {
    private let label = UILabel()
    private let button = UIButton(configuration: .borderedProminent())
    private var web: WKWebView!
    private let webHolder = UIView()
    private var timer: Timer?
    private var sequence = -1
    private var counter = 0
    private var terminations = 0
    private let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        label.font = .preferredFont(forTextStyle: .title2)
        label.numberOfLines = 0
        label.text = "Native iOS controls are running"
        button.setTitle("Test native control", for: .normal)
        button.addAction(UIAction { [weak self] _ in
            guard let self else { return }; counter += 1; label.text = "Native control count: \(counter)"
        }, for: .touchUpInside)
        let stack = UIStackView(arrangedSubviews: [label, button, webHolder])
        stack.axis = .vertical; stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -20),
            webHolder.heightAnchor.constraint(greaterThanOrEqualToConstant: 300),
        ])
        timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.readCommand() }
        }
    }
    private func startWeb() {
        guard web == nil else { return }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: webHolder.bounds, configuration: configuration)
        web.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        web.navigationDelegate = self
        web.isInspectable = true
        webHolder.addSubview(web)
        web.loadHTMLString("<meta name='viewport' content='width=device-width'><body style='font:22px system-ui;background:#eef6ff;padding:16px'><h2>WebKit diagnostic</h2><p id='state'>Plain HTML and JavaScript</p><canvas id='canvas' width='240' height='90'></canvas><script>let c=document.getElementById('canvas').getContext('2d');c.fillStyle='#2463eb';c.fillRect(0,0,240,90);window.healthReady=true;</script></body>", baseURL: nil)
    }
    private func readCommand() {
        guard let data = try? Data(contentsOf: root.appendingPathComponent("command.json")),
              let command = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let sequence = command["sequence"] as? Int, sequence != self.sequence else { return }
        self.sequence = sequence
        if command["action"] as? String == "native" {
            button.sendActions(for: .touchUpInside)
            respond(sequence, value: ["counter": counter, "width": view.bounds.width, "height": view.bounds.height,
                                      "labelHeight": label.bounds.height, "terminations": terminations])
        } else if command["action"] as? String == "web" {
            startWeb(); respond(sequence, value: "WebKit starting")
        } else if let script = command["script"] as? String, web != nil {
            web.evaluateJavaScript(script) { [weak self] value, error in self?.respond(sequence, value: value ?? NSNull(), error: error) }
        }
    }
    private func respond(_ sequence: Int, value: Any, error: Error? = nil) {
        let body: [String: Any] = ["sequence": sequence, "value": value, "error": error?.localizedDescription ?? "", "terminations": terminations]
        if let data = try? JSONSerialization.data(withJSONObject: body) { try? data.write(to: root.appendingPathComponent("response.json"), options: .atomic) }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { terminations += 1 }
}
