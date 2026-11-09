import Cocoa
import Foundation

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

guard
    let resources = Bundle.main.resourceURL?.appendingPathComponent("群聊问题整理"),
    FileManager.default.fileExists(atPath: resources.path)
else {
    let alert = NSAlert()
    alert.alertStyle = .critical
    alert.messageText = "软件包不完整"
    alert.informativeText = "未找到应用资源，请重新下载完整软件包。"
    alert.runModal()
    exit(1)
}

let script = resources.appendingPathComponent("start-mac.sh")
let process = Process()
process.executableURL = URL(fileURLWithPath: "/bin/bash")
process.arguments = [script.path]
process.currentDirectoryURL = resources

do {
    try process.run()
} catch {
    let alert = NSAlert()
    alert.alertStyle = .critical
    alert.messageText = "启动失败"
    alert.informativeText = error.localizedDescription
    alert.runModal()
    exit(1)
}

process.terminationHandler = { task in
    if task.terminationStatus != 0 {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.alertStyle = .critical
            alert.messageText = "群聊问题整理未能启动"
            alert.informativeText = "请查看 ~/Library/Application Support/群聊问题整理/logs/app.log。"
            alert.runModal()
            app.terminate(nil)
        }
    } else {
        DispatchQueue.main.async { app.terminate(nil) }
    }
}

app.run()
