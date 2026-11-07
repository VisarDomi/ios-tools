#if targetEnvironment(simulator)
import UIKit
import KitCore
import KitImages
import KitLists
import KitNavigation
import KitReader
import KitTestHooks

// Real UIKit coordinates and durable navigation; no provider, player or network.
@MainActor
final class ViewportRestorationChecks: UIViewController, StripReaderDelegate {
    private let pipeline = ImagePipeline(memoryLimit: 32 << 20, concurrency: 1)
    private var report: [String: Any] = ["complete": false]
    private var started = false
    private var cachedImage: URL?
    private var visual: StripReaderView?
    override func viewDidLoad() {
        super.viewDidLoad(); view.backgroundColor = .black
        TestHooks.shared.register("viewport-restoration-state") { [self] _ in
            var value = report; value["visual"] = visual?.state ?? [:]; return value
        }
        TestHooks.shared.start()
    }
    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !started else { return }; started = true
        do { try run(); report["pass"] = true }
        catch { report["error"] = String(describing: error) }
        report["complete"] = true
    }
    private struct Failure: Error { let message: String }
    private func require(_ condition: Bool, _ message: String) throws { if !condition { throw Failure(message: message) } }
    private func near(_ a: Double, _ b: Double, _ label: String) throws {
        try require(abs(a-b) < 0.01, "\(label): \(a) != \(b)")
    }
    private func pages(_ prefix: String) -> [StripPage] {
        (0..<12).map { StripPage(key: "\(prefix)-\($0)", aspect: [0.5, 0.8, 0.35][$0 % 3]) }
    }
    private func strip(_ prefix: String, size: CGSize, position: StripPosition, layout: Bool = true) -> StripReaderView {
        let strip = StripReaderView(pipeline: pipeline); strip.delegate = self; strip.locksPageDimensions = true
        view.addSubview(strip)
        strip.setPages(pages(prefix), position: position)
        strip.frame = CGRect(origin: .zero, size: size)
        if layout { strip.setNeedsLayout(); strip.layoutIfNeeded() }
        return strip
    }
    private func position(_ strip: StripReaderView, _ expected: StripPosition, _ label: String) throws {
        guard let actual = strip.currentPosition else { throw Failure(message: label+": no applied position") }
        try require(actual.index == expected.index, label+": wrong page")
        try near(actual.fraction, expected.fraction, label+" fraction")
        try near(actual.zoom?.scale ?? 1, expected.zoom?.scale ?? 1, label+" zoom")
        if let x = expected.zoom?.x { try near(actual.zoom?.x ?? 0.5, x, label+" horizontal point") }
    }
    private func samePicture(_ a: [String: Any], _ b: [String: Any], _ label: String) throws {
        guard let first = a["picture"] as? [CGFloat], let second = b["picture"] as? [CGFloat], first.count == 4, second.count == 4 else {
            throw Failure(message: label+": missing actual rendered rectangle")
        }
        for index in first.indices { try near(Double(first[index]), Double(second[index]), label+" rectangle \(index)") }
    }
    private func run() throws {
        let size = view.bounds.size
        try require(size.width > 0 && size.height > 0, "Fixture is not attached to a viewport")
        let wanted = StripPosition(index: 4, fraction: 0.631247891, zoom: ZoomState(scale: 2.375, x: 0.673812345), aspect: 0.8)
        let early = strip("early", size: size, position: wanted, layout: false)
        try require(early.scrollView.bounds.height == 0, "Fixture must reproduce the outer-frame/inner-frame ordering")
        early.append([StripPage(key: "early-tail", aspect: 0.5)])
        try require(early.savedPosition == wanted && early.currentPosition == nil, "A provisional viewport consumed or overwrote the requested restoration")
        early.setNeedsLayout(); early.layoutIfNeeded()
        try position(early, wanted, "late first layout")
        report["lateLayout"] = early.state
        let snapshot = try JSONDecoder().decode(StripPosition.self, from: JSONEncoder().encode(early.savedPosition!))
        let restored = strip("restored", size: size, position: snapshot)
        try samePicture(early.state, restored.state, "zoom/pan relaunch")
        let baseline = restored.state
        for _ in 0..<5 {
            for resized in [CGSize(width: size.width, height: size.height-37), CGSize(width: size.height, height: size.width), size] {
                restored.frame.size = resized; restored.setNeedsLayout(); restored.layoutIfNeeded()
                try position(restored, wanted, "resized viewport")
            }
        }
        try samePicture(baseline, restored.state, "repeated viewport roundtrip")
        report["roundtrip"] = restored.state
        for end in [false, true] {
            restored.scrollView.contentOffset.y = end ? max(0, restored.scrollView.contentSize.height - restored.scrollView.bounds.height) : 0
            let boundary = restored.savedPosition!
            try require(boundary.point != nil, "Zoomed document margin must not be clamped into a page")
            let copy = strip("boundary", size: size, position: boundary)
            try samePicture(restored.state, copy.state, "zoomed margin roundtrip")
            copy.removeFromSuperview()
        }
        early.removeFromSuperview(); restored.removeFromSuperview()

        let file = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("viewport-image.png")
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        let data = UIGraphicsImageRenderer(size: CGSize(width: 200, height: 600), format: format).pngData { context in
            UIColor.systemTeal.setFill(); context.fill(CGRect(x: 0, y: 0, width: 200, height: 600))
            UIColor.white.setFill(); context.fill(CGRect(x: 30, y: 170, width: 140, height: 3))
        }
        try data.write(to: file); cachedImage = file
        let legacyPosition = StripPosition(index: 1, fraction: 0.4312791, zoom: ZoomState(scale: 2.1, x: 0.63))
        let legacy = strip("legacy", size: size, position: legacyPosition)
        try position(legacy, legacyPosition, "cached legacy geometry")
        try near(legacy.currentPosition!.aspect!, 1.0/3, "cached image metadata")
        let legacyFrame = legacy.state
        legacy.setAspect(1.0/3, at: 0)
        legacy.setAspect(1.0/3, at: 1)
        try samePicture(legacyFrame, legacy.state, "image arrival after legacy restore")
        report["legacyGeometry"] = legacy.state
        visual = legacy
        cachedImage = nil // Keep the checked page visible for the fixture screenshot.

        let list = UIScrollView(frame: CGRect(origin: .zero, size: size))
        list.contentInsetAdjustmentBehavior = .never; list.contentSize = CGSize(width: size.width, height: 5_000)
        let y = 700.375
        list.contentOffset.y = y
        let capturedY = list.contentOffset.y
        let row = CGRect(x: 0, y: y + size.height / 2 + 37, width: size.width, height: 300)
        let anchor = ScrollAnchoring.anchor(in: list, items: [("row", row)])!
        let savedAnchor = try JSONDecoder().decode(ScrollAnchor.self, from: JSONEncoder().encode(anchor))
        list.contentOffset.y = 0
        ScrollAnchoring.restore(savedAnchor, in: list, frame: CGRect(x: row.minX, y: row.minY, width: row.width, height: 500))
        try near(Double(list.contentOffset.y), Double(capturedY), "header/gap exact list anchor")
        report["listAnchor"] = ["offset": list.contentOffset.y, "fraction": savedAnchor.fraction, "pixelOffset": savedAnchor.offset!]

        let thumbnails = ThumbnailStripView(pipeline: pipeline)
        thumbnails.setKeys((0..<20).map { "thumbnail-\($0)" }, offset: 537)
        try near(Double(thumbnails.offset), 537, "pending thumbnail offset")
        thumbnails.frame = CGRect(x: 0, y: 0, width: size.width, height: 300)
        thumbnails.setNeedsLayout(); thumbnails.layoutIfNeeded()
        try near(Double(thumbnails.collectionView.contentOffset.x), 537, "thumbnail first layout")
        thumbnails.collectionView.contentOffset.x = 623
        thumbnails.setNeedsLayout(); thumbnails.layoutIfNeeded()
        try near(Double(thumbnails.offset), 623, "thumbnail movement supersedes restore")
        report["thumbnailOffset"] = thumbnails.offset

        let root = CaptureScreen("root"), child = CaptureScreen("child")
        let navigationFile = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("viewport-navigation.json")
        try? FileManager.default.removeItem(at: navigationFile)
        let nav = LiveNavigationController(file: navigationFile, factory: { _, _ in nil }, root: root)
        root.visiblePoint = 123.375
        nav.open(child, animated: false)
        try near(root.capturedPoint, 123.375, "departure capture")
        root.visiblePoint = 999 // hidden screens must not overwrite current progress
        child.visiblePoint = 456.8125
        nav.flush()
        let stack = try DurableFile.readJSON(SavedStack.self, from: navigationFile)!
        let points = try stack.back.map { try JSONDecoder().decode(Double.self, from: $0.state!) }
        try require(points == [123.375,456.8125], "Durable capture used stale or hidden viewport values: \(points)")
        report["boundaryCapture"] = points
    }
    func strip(_ strip: StripReaderView, sourceFor index: Int) -> ImageSource {
        if let cachedImage { return .file(cachedImage) }
        return .load { throw CancellationError() }
    }
    func strip(_ strip: StripReaderView, localFileFor index: Int) -> URL? { cachedImage }
    func strip(_ strip: StripReaderView, settledAt position: StripPosition) {}
}

@MainActor
private final class CaptureScreen: UIViewController, LiveScreen {
    let name: String
    var visiblePoint = 0.0
    var capturedPoint = 0.0
    init(_ name: String) { self.name = name; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError() }
    var route: Data { Data(name.utf8) }
    func captureState() { capturedPoint = visiblePoint }
    func savedState() -> Data? { try? JSONEncoder().encode(capturedPoint) }
}
#endif
